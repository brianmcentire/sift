"""FastAPI application — all endpoints."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from server import db
from server.models import (
    CacheResponse,
    CacheEntry,
    DuplicateLocation,
    DuplicateSet,
    FileEntry,
    FileRecord,
    HostEntry,
    LsEntry,
    ScanRunCreate,
    ScanRunCreatedResponse,
    ScanRunPatch,
    ScanRunResponse,
    SeenRequest,
    SeenResponse,
    StatsOverview,
    UpsertResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("SIFT_DB_PATH") or db.get_db_path()
    db.init_db(db_path)
    yield


app = FastAPI(title="sift", version="0.1.0", lifespan=lifespan)

# Mount static frontend if it exists
_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/app", StaticFiles(directory=_frontend_dist, html=True), name="frontend")


# ---------------------------------------------------------------------------
# Scan runs
# ---------------------------------------------------------------------------

@app.post("/scan-runs", response_model=ScanRunCreatedResponse)
def create_scan_run(body: ScanRunCreate):
    # Abandon any prior 'running' scans for same host + root_path
    db.execute(
        "UPDATE scan_runs SET status = 'failed' "
        "WHERE host = ? AND root_path = ? AND status = 'running'",
        [body.host, body.root_path],
    )
    db.execute(
        "INSERT INTO scan_runs (host, root_path, started_at, status) VALUES (?, ?, ?, 'running')",
        [body.host, body.root_path, body.started_at.isoformat()],
    )
    row = db.query_one(
        "SELECT id FROM scan_runs WHERE host = ? AND root_path = ? AND status = 'running' "
        "ORDER BY id DESC LIMIT 1",
        [body.host, body.root_path],
    )
    return {"id": row[0]}


@app.patch("/scan-runs/{run_id}")
def patch_scan_run(run_id: int, body: ScanRunPatch):
    if body.status not in ("complete", "failed"):
        raise HTTPException(400, "status must be 'complete' or 'failed'")
    db.execute(
        "UPDATE scan_runs SET status = ? WHERE id = ?",
        [body.status, run_id],
    )
    return {"ok": True}


@app.get("/scan-runs", response_model=list[ScanRunResponse])
def list_scan_runs(host: Optional[str] = None, limit: int = Query(50, le=500)):
    if host:
        rows = db.query(
            "SELECT id, host, root_path, started_at, status FROM scan_runs "
            "WHERE host = ? ORDER BY id DESC LIMIT ?",
            [host, limit],
        )
    else:
        rows = db.query(
            "SELECT id, host, root_path, started_at, status FROM scan_runs "
            "ORDER BY id DESC LIMIT ?",
            [limit],
        )
    return [
        ScanRunResponse(id=r[0], host=r[1], root_path=r[2], started_at=r[3], status=r[4])
        for r in rows
    ]


# ---------------------------------------------------------------------------
# File ingest
# ---------------------------------------------------------------------------

@app.post("/files", response_model=UpsertResponse)
def upsert_files(records: list[FileRecord]):
    if not records:
        return {"upserted": 0}

    sql = """
        INSERT INTO files (
            host, drive, path, path_display, filename, ext, file_category,
            size_bytes, hash, mtime, last_checked, source_os, skipped_reason, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (host, drive, path) DO UPDATE SET
            path_display   = excluded.path_display,
            filename       = excluded.filename,
            ext            = excluded.ext,
            file_category  = excluded.file_category,
            size_bytes     = excluded.size_bytes,
            hash           = excluded.hash,
            mtime          = excluded.mtime,
            last_checked   = excluded.last_checked,
            source_os      = excluded.source_os,
            skipped_reason = excluded.skipped_reason,
            last_seen_at   = excluded.last_seen_at
    """
    data = [
        [
            r.host, r.drive, r.path, r.path_display, r.filename, r.ext, r.file_category,
            r.size_bytes, r.hash, r.mtime,
            r.last_checked.isoformat(), r.source_os, r.skipped_reason,
            r.last_seen_at.isoformat(),
        ]
        for r in records
    ]
    db.executemany(sql, data)
    return {"upserted": len(records)}


@app.post("/files/seen", response_model=SeenResponse)
def mark_files_seen(body: SeenRequest):
    if not body.paths:
        return {"updated": 0}

    # Single bulk UPDATE via VALUES subquery — far faster than executemany
    # individual row updates in DuckDB's columnar engine.
    placeholders = ", ".join(["(?, ?)"] * len(body.paths))
    sql = f"""
        UPDATE files
        SET last_seen_at = ?
        WHERE host = ?
          AND (drive, path) IN (VALUES {placeholders})
    """
    params: list = [body.last_seen_at.isoformat(), body.host]
    for entry in body.paths:
        params.extend([entry.drive, entry.path])
    db.execute(sql, params)
    return {"updated": len(body.paths)}


# ---------------------------------------------------------------------------
# Cache endpoint (rehash optimization)
# ---------------------------------------------------------------------------

@app.get("/files/cache", response_model=CacheResponse)
def get_cache(host: str, root: str):
    root_lower = root.lower()
    rows = db.query(
        "SELECT path, mtime, size_bytes FROM files "
        "WHERE host = ? AND (path LIKE ? OR path = ?)",
        [host, root_lower + "/%", root_lower],
    )
    files = [CacheEntry(path=r[0], mtime=r[1], size_bytes=r[2]) for r in rows]
    return {"files": files}


# ---------------------------------------------------------------------------
# File listing
# ---------------------------------------------------------------------------

@app.get("/files/ls", response_model=list[LsEntry])
def ls_files(
    path: str = "/",
    host: str = "",
    depth: int = Query(1, ge=1),
):
    prefix = path.lower().rstrip("/")
    # SPLIT_PART is 1-indexed; paths start with '/' → position 1 is empty.
    # For prefix '' (root), segment is at SPLIT_PART index 2.
    # For prefix '/a/b', segment is at index 4 (2 slashes + 1 + 1 for leading empty).
    split_idx = prefix.count("/") + depth + 1

    sql = f"""
    WITH dupes AS (
        SELECT hash FROM files
        WHERE hash IS NOT NULL
        GROUP BY hash HAVING COUNT(*) > 1
    ),
    scoped AS (
        SELECT
            f.path, f.path_display, f.filename, f.size_bytes,
            f.hash, f.mtime, f.host, f.drive,
            SPLIT_PART(f.path, '/', {split_idx}) AS segment,
            SPLIT_PART(f.path_display, '/', {split_idx}) AS segment_display,
            CASE WHEN SPLIT_PART(f.path, '/', {split_idx + 1}) = ''
                 THEN 'file' ELSE 'dir' END AS entry_type
        FROM files f
        WHERE f.host = ?
          AND (f.path LIKE ? OR f.path = ?)
    )
    SELECT
        s.segment,
        ANY_VALUE(s.entry_type) AS entry_type,
        COUNT(*) AS file_count,
        SUM(s.size_bytes) AS total_bytes,
        COUNT(CASE WHEN s.hash IN (SELECT hash FROM dupes) THEN 1 END) AS dup_count,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.filename END) AS filename,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.size_bytes END) AS leaf_size,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.hash END) AS leaf_hash,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.mtime END) AS leaf_mtime,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.path_display END) AS leaf_path_display,
        ANY_VALUE(s.segment_display) AS segment_display,
        STRING_AGG(DISTINCT f2.host ORDER BY f2.host) AS other_hosts
    FROM scoped s
    LEFT JOIN files f2 ON f2.hash = s.hash AND f2.host != ? AND s.hash IS NOT NULL
                       AND s.entry_type = 'file'
    WHERE s.segment IS NOT NULL AND s.segment != ''
    GROUP BY s.segment
    ORDER BY ANY_VALUE(s.entry_type) DESC, s.segment
    """

    params = [host, prefix + "/%", prefix, host]
    rows = db.query(sql, params)
    result = []
    for r in rows:
        result.append(LsEntry(
            segment=r[0],
            entry_type=r[1],
            file_count=r[2] or 0,
            total_bytes=r[3],
            dup_count=r[4] or 0,
            filename=r[5],
            size_bytes=r[6],
            hash=r[7],
            mtime=r[8],
            path_display=r[9],
            segment_display=r[10],
            other_hosts=r[11],
        ))
    return result


@app.get("/files", response_model=list[FileEntry])
def list_files(
    host: Optional[str] = None,
    path_prefix: Optional[str] = None,
    ext: Optional[str] = None,
    category: Optional[str] = None,
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    has_duplicates: Optional[bool] = None,
    hash: Optional[str] = None,
    name: Optional[str] = None,
    iname: Optional[str] = None,
    limit: int = Query(100, le=1_000_000),
):
    conditions = ["1=1"]
    params: list = []

    if host:
        conditions.append("f.host = ?")
        params.append(host)
    if path_prefix:
        prefix_lower = path_prefix.lower().rstrip("/")
        conditions.append("(f.path LIKE ? OR f.path = ?)")
        params.extend([prefix_lower + "/%", prefix_lower])
    if ext:
        conditions.append("f.ext = ?")
        params.append(ext.lower().lstrip("."))
    if category:
        conditions.append("f.file_category = ?")
        params.append(category)
    if min_size is not None:
        conditions.append("f.size_bytes >= ?")
        params.append(min_size)
    if max_size is not None:
        conditions.append("f.size_bytes <= ?")
        params.append(max_size)
    if hash:
        conditions.append("f.hash = ?")
        params.append(hash)
    if name:
        # glob-style: convert * to SQL %, ? to _
        sql_pat = name.replace("%", "\\%").replace("_", "\\_").replace("*", "%").replace("?", "_")
        conditions.append("f.filename LIKE ?")
        params.append(sql_pat)
    if iname:
        sql_pat = iname.replace("%", "\\%").replace("_", "\\_").replace("*", "%").replace("?", "_")
        conditions.append("LOWER(f.filename) LIKE LOWER(?)")
        params.append(sql_pat)

    if has_duplicates is True:
        dup_clause = (
            " AND f.hash IN (SELECT hash FROM files WHERE hash IS NOT NULL "
            "GROUP BY hash HAVING COUNT(*) > 1)"
        )
    elif has_duplicates is False:
        dup_clause = (
            " AND (f.hash IS NULL OR f.hash NOT IN "
            "(SELECT hash FROM files WHERE hash IS NOT NULL "
            "GROUP BY hash HAVING COUNT(*) > 1))"
        )
    else:
        dup_clause = ""

    where = " AND ".join(conditions)

    sql = f"""
    SELECT
        f.host, f.drive, f.path_display, f.filename, f.ext,
        f.file_category, f.size_bytes, f.hash, f.mtime,
        STRING_AGG(DISTINCT f2.host ORDER BY f2.host) AS other_hosts
    FROM files f
    LEFT JOIN files f2 ON f2.hash = f.hash AND f2.host != f.host AND f.hash IS NOT NULL
    WHERE {where} {dup_clause}
    GROUP BY f.host, f.drive, f.path_display, f.filename, f.ext,
             f.file_category, f.size_bytes, f.hash, f.mtime
    ORDER BY f.path_display
    LIMIT ?
    """
    params.append(limit)

    rows = db.query(sql, params)
    return [
        FileEntry(
            host=r[0], drive=r[1], path_display=r[2], filename=r[3],
            ext=r[4], file_category=r[5], size_bytes=r[6], hash=r[7],
            mtime=r[8], other_hosts=r[9],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------

@app.get("/hosts", response_model=list[HostEntry])
def list_hosts():
    rows = db.query("""
        WITH latest_run AS (
            SELECT host, root_path, started_at,
                   ROW_NUMBER() OVER (PARTITION BY host ORDER BY id DESC) AS rn
            FROM scan_runs
        )
        SELECT
            f.host,
            MAX(sr.started_at) AS last_scan_at,
            ANY_VALUE(lr.root_path) AS last_scan_root,
            COUNT(*) AS total_files,
            SUM(f.size_bytes) AS total_bytes,
            COUNT(CASE WHEN f.hash IS NOT NULL THEN 1 END) AS total_hashed
        FROM files f
        LEFT JOIN scan_runs sr ON sr.host = f.host AND sr.status = 'complete'
        LEFT JOIN latest_run lr ON lr.host = f.host AND lr.rn = 1
        GROUP BY f.host
        ORDER BY f.host
    """)
    return [
        HostEntry(
            host=r[0], last_scan_at=r[1], last_scan_root=r[2],
            total_files=r[3], total_bytes=r[4], total_hashed=r[5],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.get("/stats/overview", response_model=StatsOverview)
def stats_overview():
    row = db.query_one("""
        SELECT
            COUNT(*) AS total_files,
            COUNT(DISTINCT host) AS total_hosts,
            COUNT(DISTINCT hash) FILTER (WHERE hash IS NOT NULL) AS unique_hashes,
            COUNT(*) FILTER (WHERE hash IN (
                SELECT hash FROM files WHERE hash IS NOT NULL
                GROUP BY hash HAVING COUNT(*) > 1
            )) AS dup_files,
            SUM(size_bytes) FILTER (WHERE hash IN (
                SELECT hash FROM files WHERE hash IS NOT NULL
                GROUP BY hash HAVING COUNT(*) > 1
            )) - SUM(
                (SELECT MIN(size_bytes) FROM files f2 WHERE f2.hash = files.hash)
            ) FILTER (WHERE hash IN (
                SELECT hash FROM files WHERE hash IS NOT NULL
                GROUP BY hash HAVING COUNT(*) > 1
            )) AS wasted_bytes,
            SUM(size_bytes) AS total_bytes
        FROM files
    """)

    # Simpler wasted_bytes calculation
    dup_row = db.query_one("""
        SELECT
            COUNT(DISTINCT hash) AS dup_sets,
            SUM(size_bytes) - SUM(min_size) AS wasted
        FROM (
            SELECT hash, COUNT(*) AS cnt, SUM(size_bytes) AS size_bytes,
                   MIN(size_bytes) AS min_size
            FROM files
            WHERE hash IS NOT NULL
            GROUP BY hash
            HAVING COUNT(*) > 1
        ) t
    """)

    total_files = row[0] if row else 0
    total_hosts = row[1] if row else 0
    unique_hashes = row[2] if row else 0
    total_bytes = row[5] if row else None
    duplicate_sets = dup_row[0] if dup_row else 0
    wasted_bytes = dup_row[1] if dup_row else None

    return StatsOverview(
        total_files=total_files,
        total_hosts=total_hosts,
        unique_hashes=unique_hashes,
        duplicate_sets=duplicate_sets,
        wasted_bytes=wasted_bytes,
        total_bytes=total_bytes,
    )


@app.get("/stats/duplicates", response_model=list[DuplicateSet])
def stats_duplicates(
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    min_copies: int = Query(2, ge=2),
):
    # Get duplicate sets
    sets_rows = db.query(
        """
        SELECT hash, MAX(filename) AS filename, MAX(size_bytes) AS size_bytes,
               COUNT(*) AS copy_count,
               SUM(size_bytes) - MIN(size_bytes) AS wasted_bytes
        FROM files
        WHERE hash IS NOT NULL
        GROUP BY hash
        HAVING COUNT(*) >= ?
        ORDER BY wasted_bytes DESC NULLS LAST, copy_count DESC
        LIMIT ? OFFSET ?
        """,
        [min_copies, limit, offset],
    )

    result = []
    for sr in sets_rows:
        hash_val, filename, size_bytes, copy_count, wasted_bytes = sr
        loc_rows = db.query(
            "SELECT host, drive, path_display FROM files WHERE hash = ? ORDER BY host, path_display",
            [hash_val],
        )
        locations = [
            DuplicateLocation(host=lr[0], drive=lr[1], path_display=lr[2])
            for lr in loc_rows
        ]
        result.append(DuplicateSet(
            hash=hash_val,
            filename=filename,
            size_bytes=size_bytes,
            copy_count=copy_count,
            wasted_bytes=wasted_bytes,
            locations=locations,
        ))
    return result
