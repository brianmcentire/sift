"""FastAPI application — all endpoints."""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

import json

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sift.server")

from server import db
from server.models import (
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
    TrimRequest,
    TrimResponse,
    UpsertResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("SIFT_DB_PATH") or db.get_db_path()
    db.init_db(db_path)
    yield


# ---------------------------------------------------------------------------
# Periodic host stats refresh (during active scans)
# ---------------------------------------------------------------------------

_STATS_REFRESH_INTERVAL = 60  # seconds between mid-scan refreshes
_last_stats_refresh: dict[str, float] = {}  # host -> monotonic time
_stats_refresh_lock = threading.Lock()


def _maybe_refresh_host_stats(host: str) -> None:
    """Refresh host_stats if it's been ≥10 min since last refresh for this host.

    Runs in a background thread so it doesn't add latency to the flush response.
    Skips if a refresh is already in progress for this host.
    """
    now = time.monotonic()
    with _stats_refresh_lock:
        if now - _last_stats_refresh.get(host, 0) < _STATS_REFRESH_INTERVAL:
            return
        _last_stats_refresh[host] = now

    def _do_refresh():
        try:
            db.refresh_host_stats(host)
            _invalidate_stats_cache()
        except Exception:
            pass

    threading.Thread(target=_do_refresh, daemon=True, name=f"stats-refresh-{host}").start()


app = FastAPI(title="sift", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - start
    path = request.url.path
    # Skip static asset noise
    if path.startswith("/assets/") or path == "/favicon.ico":
        return response
    if elapsed > 1.0:
        logger.warning(
            "%s %s %d — %.1fs", request.method, path, response.status_code, elapsed
        )
    elif request.method in ("POST", "PATCH"):
        logger.info(
            "%s %s %d — %.3fs", request.method, path, response.status_code, elapsed
        )
    return response


# Static frontend is mounted AFTER all API routes (see bottom of file)


# ---------------------------------------------------------------------------
# Scan runs
# ---------------------------------------------------------------------------


@app.post("/scan-runs", response_model=ScanRunCreatedResponse)
def create_scan_run(body: ScanRunCreate):
    # Abandon any prior 'running' scans for same host + root_path
    stale = db.query(
        "SELECT id FROM scan_runs WHERE host = ? AND root_path = ? AND status = 'running'",
        [body.host, body.root_path],
    )
    if stale:
        db.execute(
            "UPDATE scan_runs SET status = 'failed' "
            "WHERE host = ? AND root_path = ? AND status = 'running'",
            [body.host, body.root_path],
        )
        # Crashed/stale scan — refresh stats so they reflect reality
        db.refresh_host_stats(body.host)
        _invalidate_stats_cache()
    db.execute(
        "INSERT INTO scan_runs (host, root_path, root_path_display, started_at, status) "
        "VALUES (?, ?, ?, ?, 'running')",
        [
            body.host,
            body.root_path,
            body.root_path_display,
            body.started_at.isoformat(),
        ],
    )
    row = db.query_one(
        "SELECT id FROM scan_runs WHERE host = ? AND root_path = ? AND status = 'running' "
        "ORDER BY id DESC LIMIT 1",
        [body.host, body.root_path],
    )
    if row is None:
        raise HTTPException(500, "failed to create scan run")
    return {"id": row[0]}


@app.patch("/scan-runs/{run_id}")
def patch_scan_run(run_id: int, body: ScanRunPatch):
    if body.status not in ("complete", "failed", "interrupted"):
        raise HTTPException(
            400, "status must be 'complete', 'failed', or 'interrupted'"
        )
    # Look up host before UPDATE so we can refresh its stats
    row = db.query_one("SELECT host FROM scan_runs WHERE id = ?", [run_id])
    db.execute(
        "UPDATE scan_runs SET status = ? WHERE id = ?",
        [body.status, run_id],
    )
    if row:
        host = row[0]
        # Reset throttle so the end-of-scan refresh always runs immediately.
        with _stats_refresh_lock:
            _last_stats_refresh.pop(host, None)
        db.refresh_host_stats(host)
        _invalidate_stats_cache()
    return {"ok": True}


@app.get("/scan-runs", response_model=list[ScanRunResponse])
def list_scan_runs(host: Optional[str] = None, limit: int = Query(50, le=500)):
    if host:
        rows = db.query(
            "SELECT id, host, root_path, root_path_display, started_at, status FROM scan_runs "
            "WHERE host = ? ORDER BY id DESC LIMIT ?",
            [host, limit],
        )
    else:
        rows = db.query(
            "SELECT id, host, root_path, root_path_display, started_at, status FROM scan_runs "
            "ORDER BY id DESC LIMIT ?",
            [limit],
        )
    return [
        ScanRunResponse(
            id=r[0],
            host=r[1],
            root_path=r[2],
            root_path_display=r[3],
            started_at=r[4],
            status=r[5],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# File ingest
# ---------------------------------------------------------------------------


@app.post("/files", response_model=UpsertResponse)
def upsert_files(records: list[FileRecord]):
    if not records:
        return {"upserted": 0}
    start = time.monotonic()

    # Build a single multi-row INSERT so DuckDB can batch index lookups and
    # updates in one pass.  executemany runs each row as a separate statement
    # which is catastrophically slow on a columnar DB with many indexes.
    row_ph = "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    values_ph = ", ".join([row_ph] * len(records))
    sql = f"""
        INSERT INTO files (
            host, drive, path, path_display, filename, ext, file_category,
            size_bytes, hash, mtime, last_checked, source_os, skipped_reason, last_seen_at,
            inode, device
        ) VALUES {values_ph}
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
            last_seen_at   = excluded.last_seen_at,
            inode          = excluded.inode,
            device         = excluded.device
    """
    params: list = []
    for r in records:
        params.extend(
            [
                r.host,
                r.drive,
                r.path,
                r.path_display,
                r.filename,
                r.ext,
                r.file_category,
                r.size_bytes,
                r.hash,
                r.mtime,
                r.last_checked.isoformat(),
                r.source_os,
                r.skipped_reason,
                r.last_seen_at.isoformat(),
                r.inode,
                r.device,
            ]
        )
    db.execute(sql, params)
    elapsed = time.monotonic() - start
    if elapsed > 2.0:
        logger.warning("POST /files: %d records in %.1fs", len(records), elapsed)
    _invalidate_stats_cache()
    # Periodically refresh host stats mid-scan so sift status stays current.
    # Throttled to once per 10 min per host; runs in background thread.
    if records:
        _maybe_refresh_host_stats(records[0].host)
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
# Trim
# ---------------------------------------------------------------------------


def _glob_to_like(glob_pat: str) -> str:
    return (
        glob_pat.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("*", "%")
        .replace("?", "_")
    )


def _trim_scope_sql(path_prefix: str, recursive: bool) -> tuple[str, list]:
    prefix = path_prefix.lower().rstrip("/")
    if recursive:
        return "(f.path = ? OR f.path LIKE ?)", [prefix, prefix + "/%"]

    if prefix == "":
        # Direct children of root only: '/a' yes, '/a/b' no
        return (
            "(f.path LIKE '/%' AND POSITION('/' IN SUBSTR(f.path, 2)) = 0)",
            [],
        )

    # Direct children of /a/b only: /a/b/x yes, /a/b/x/y no
    base = prefix + "/"
    start_idx = len(base) + 1  # DuckDB SUBSTR is 1-indexed
    return (
        "(f.path LIKE ? AND POSITION('/' IN SUBSTR(f.path, ?)) = 0)",
        [base + "%", start_idx],
    )


def _trim_candidates_cte(body: TrimRequest) -> tuple[str, list]:
    where = ["f.host = ?"]
    params: list = [body.host]

    scope_sql, scope_params = _trim_scope_sql(body.path_prefix, body.recursive)
    where.append(scope_sql)
    params.extend(scope_params)

    if body.patterns:
        clauses = []
        for pat in body.patterns:
            clauses.append("f.filename LIKE ? ESCAPE '\\'")
            params.append(_glob_to_like(pat))
        where.append("(" + " OR ".join(clauses) + ")")

    base_where = " AND ".join(where)

    if not body.deleted_only:
        sql = f"""
            candidates AS (
                SELECT f.host, f.drive, f.path
                FROM files f
                WHERE {base_where}
            )
        """
        return sql, params

    # deleted_only: only rows stale relative to latest covering COMPLETE scan.
    # Rows with no covering complete scan are intentionally excluded.
    sql = f"""
        covered AS (
            SELECT
                f.host, f.drive, f.path,
                MAX(sr.started_at) AS latest_complete_started_at
            FROM files f
            JOIN scan_runs sr
              ON sr.host = f.host
             AND sr.status = 'complete'
             AND (f.path = sr.root_path OR f.path LIKE sr.root_path || '/%')
            WHERE {base_where}
            GROUP BY f.host, f.drive, f.path
        ),
        candidates AS (
            SELECT f.host, f.drive, f.path
            FROM files f
            JOIN covered c
              ON c.host = f.host AND c.drive = f.drive AND c.path = f.path
            WHERE f.last_seen_at < c.latest_complete_started_at
        )
    """
    return sql, params


@app.post("/trim", response_model=TrimResponse)
def trim_files(body: TrimRequest):
    if body.limit < 1 or body.limit > 100_000:
        raise HTTPException(400, "limit must be between 1 and 100000")
    if body.offset < 0:
        raise HTTPException(400, "offset must be >= 0")

    body.path_prefix = body.path_prefix.lower().rstrip("/")
    if body.path_prefix == ".":
        body.path_prefix = ""

    cte_sql, cte_params = _trim_candidates_cte(body)

    count_row = db.query_one(
        f"""
        WITH {cte_sql}
        SELECT COUNT(*) FROM candidates
        """,
        cte_params,
    )
    matched = count_row[0] if count_row else 0

    if body.count_only or matched == 0:
        preview_paths: list[str] = []
        if body.preview and matched > 0:
            preview_rows = db.query(
                f"""
                WITH {cte_sql}
                SELECT f.path_display
                FROM files f
                JOIN candidates c
                  ON c.host = f.host AND c.drive = f.drive AND c.path = f.path
                ORDER BY f.path
                LIMIT ? OFFSET ?
                """,
                cte_params + [body.limit, body.offset],
            )
            preview_paths = [r[0] for r in preview_rows]
        return {"matched": matched, "deleted": 0, "preview_paths": preview_paths}

    to_delete_sql = f"""
        WITH {cte_sql},
        to_delete AS (
            SELECT host, drive, path
            FROM candidates
            LIMIT ?
        )
        DELETE FROM files f
        USING to_delete d
        WHERE f.host = d.host AND f.drive = d.drive AND f.path = d.path
    """
    db.execute(to_delete_sql, cte_params + [body.limit])
    deleted = min(matched, body.limit)

    if deleted > 0:
        db.refresh_host_stats(body.host)
        _invalidate_stats_cache()

    return {"matched": matched, "deleted": deleted, "preview_paths": []}


# ---------------------------------------------------------------------------
# Cache endpoint (rehash optimization)
# ---------------------------------------------------------------------------


@app.get("/files/cache")
def get_cache(host: str, root: str):
    # Returns a compact array-of-arrays [path, mtime, size_bytes] to minimize
    # JSON payload size and avoid per-row Pydantic model instantiation overhead.
    root_lower = root.lower()
    rows = db.query(
        "SELECT path, mtime, size_bytes FROM files "
        "WHERE host = ? AND (path LIKE ? OR path = ?)",
        [host, root_lower + "/%", root_lower],
    )
    return {"files": [[r[0], r[1], r[2]] for r in rows]}


@app.get("/files/cache/stream")
def get_cache_stream(host: str, root: str):
    """Stream cache entries as NDJSON — one JSON array per line.
    Rows are fetched under the lock then streamed from memory, so the
    lock is held only for the DB query, not the entire HTTP transfer."""
    root_lower = root.lower()
    rows = db.query(
        "SELECT path, mtime, size_bytes FROM files "
        "WHERE host = ? AND (path LIKE ? OR path = ?)",
        [host, root_lower + "/%", root_lower],
    )

    def generate():
        for r in rows:
            yield json.dumps([r[0], r[1], r[2]]) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# File listing
# ---------------------------------------------------------------------------


@app.get("/files/ls/dup-hash")
def ls_dup_hash(path: str = Query("/"), host: str = Query(""), min_size: int = Query(0, ge=0)):
    """Return the first duplicated hash found within the given subtree for a host.
    Uses the same hard-link exclusion logic as the dupes CTE in ls_files so the
    returned hash is guaranteed to appear >= 2 times in /files?hash=X."""
    prefix = path.lower().rstrip("/")
    row = db.query_one(
        """
        WITH hard_linked_inodes AS (
            SELECT device, inode FROM files
            WHERE host = ? AND inode IS NOT NULL AND device IS NOT NULL
            GROUP BY device, inode HAVING COUNT(*) > 1
        )
        SELECT f.hash
        FROM files f
        WHERE f.host = ?
          AND f.hash IS NOT NULL
          AND (f.path LIKE ? OR f.path = ?)
          AND f.size_bytes >= ?
          AND NOT (f.inode IS NOT NULL AND f.device IS NOT NULL
                   AND (f.device, f.inode) IN (SELECT device, inode FROM hard_linked_inodes))
          AND f.hash IN (
              SELECT hash FROM files
              WHERE host = ? AND hash IS NOT NULL
                AND size_bytes >= ?
                AND NOT (inode IS NOT NULL AND device IS NOT NULL
                         AND (device, inode) IN (SELECT device, inode FROM hard_linked_inodes))
              GROUP BY hash HAVING COUNT(*) > 1
          )
        LIMIT 1
    """,
        [host, host, prefix + "/%", prefix, min_size, host, min_size],
    )
    if row is None:
        raise HTTPException(
            status_code=404, detail="No duplicate hash found in subtree"
        )
    return {"hash": row[0]}


@app.get("/files/duplicates-in-subtree", response_model=list[FileEntry])
def duplicates_in_subtree(
    host: str = Query(...),
    path_prefix: str = Query(...),
    min_size: int = Query(0, ge=0),
    limit: int = Query(1000, le=10000),
):
    """Return all files that are duplicated within a subtree, grouped by hash."""
    prefix = path_prefix.lower().rstrip("/")
    sql = """
    WITH hard_linked_inodes AS (
        SELECT device, inode FROM files
        WHERE host = ? AND inode IS NOT NULL AND device IS NOT NULL
        GROUP BY device, inode HAVING COUNT(*) > 1
    ),
    dup_hashes AS (
        SELECT hash FROM files
        WHERE host = ? AND hash IS NOT NULL
          AND (path LIKE ? OR path = ?)
          AND size_bytes >= ?
          AND NOT (inode IS NOT NULL AND device IS NOT NULL
                   AND (device, inode) IN (SELECT device, inode FROM hard_linked_inodes))
        GROUP BY hash HAVING COUNT(*) > 1
    )
    SELECT f.host, f.drive, f.path_display, f.filename, f.ext, f.file_category,
           f.size_bytes, f.hash, f.mtime, f.last_seen_at
    FROM files f
    WHERE f.host = ? AND f.hash IN (SELECT hash FROM dup_hashes)
      AND (f.path LIKE ? OR f.path = ?)
    ORDER BY f.hash, f.path_display
    LIMIT ?
    """
    params = [
        host,                       # hard_linked_inodes
        host, prefix + "/%", prefix, min_size,  # dup_hashes
        host, prefix + "/%", prefix,  # result rows
        limit,
    ]
    rows = db.query(sql, params)
    return [
        FileEntry(
            host=r[0], drive=r[1], path_display=r[2], filename=r[3],
            ext=r[4], file_category=r[5], size_bytes=r[6], hash=r[7],
            mtime=r[8], last_seen_at=r[9], other_hosts=None,
        )
        for r in rows
    ]


@app.get("/files/dup-ancestor-dirs")
def dup_ancestor_dirs(
    host: str = Query(...),
    path_prefix: str = Query(...),
    min_size: int = Query(0, ge=0),
):
    """Return directory paths that contain duplicate files under a subtree.
    Walks up from each leaf dir to path_prefix to fill in intermediate ancestors."""
    prefix = path_prefix.lower().rstrip("/")
    sql = """
    WITH hard_linked_inodes AS (
        SELECT device, inode FROM files
        WHERE host = ? AND inode IS NOT NULL AND device IS NOT NULL
        GROUP BY device, inode HAVING COUNT(*) > 1
    ),
    dupes AS (
        SELECT hash FROM files
        WHERE hash IS NOT NULL AND host = ?
          AND size_bytes >= ?
          AND NOT (inode IS NOT NULL AND device IS NOT NULL
                   AND (device, inode) IN (SELECT device, inode FROM hard_linked_inodes))
        GROUP BY hash HAVING COUNT(*) > 1
    )
    SELECT DISTINCT regexp_replace(f.path, '/[^/]+$', '') AS dir_path
    FROM files f
    WHERE f.host = ?
      AND f.hash IS NOT NULL
      AND f.hash IN (SELECT hash FROM dupes)
      AND (f.path LIKE ? OR f.path = ?)
    ORDER BY dir_path
    """
    params = [host, host, min_size, host, prefix + "/%", prefix]
    rows = db.query(sql, params)

    leaf_dirs = {r[0] for r in rows if r[0]}
    all_paths = set(leaf_dirs)
    for leaf in leaf_dirs:
        d = leaf
        while d != prefix and '/' in d:
            d = d.rsplit('/', 1)[0]
            if d and d != prefix and (d == prefix or d.startswith(prefix + '/')):
                all_paths.add(d)
    return {"paths": sorted(all_paths)}


@app.get("/files/ls", response_model=list[LsEntry])
def ls_files(
    path: str = "/",
    host: str = "",
    depth: int = Query(1, ge=1),
    min_size: int = Query(0, ge=0),
):
    prefix = path.lower().rstrip("/")
    # SPLIT_PART is 1-indexed; paths start with '/' → position 1 is empty.
    # For prefix '' (root), segment is at SPLIT_PART index 2.
    # For prefix '/a/b', segment is at index 4 (2 slashes + 1 + 1 for leading empty).
    split_idx = prefix.count("/") + depth + 1

    sql = f"""
    WITH hard_linked_inodes AS (
        -- (host, device, inode) tuples that appear on more than one path.
        -- These are hard links: multiple directory entries → same physical file.
        -- We use this to exclude them from same-host dup counts.
        SELECT device, inode FROM files
        WHERE host = ? AND inode IS NOT NULL AND device IS NOT NULL
        GROUP BY device, inode HAVING COUNT(*) > 1
    ),
    dupes AS (
        -- Same-host duplicates: same hash, but NOT because they're hard links
        -- (hard links are the same physical file; counting them as dups is misleading).
        SELECT hash FROM files
        WHERE hash IS NOT NULL AND host = ?
          AND size_bytes >= ?
          AND NOT (inode IS NOT NULL AND device IS NOT NULL
                   AND (device, inode) IN (SELECT device, inode FROM hard_linked_inodes))
        GROUP BY hash HAVING COUNT(*) > 1
    ),
    scoped AS (
        SELECT
            f.path, f.path_display, f.filename, f.size_bytes,
            f.hash, f.mtime, f.last_seen_at, f.file_category, f.host, f.drive,
            f.inode, f.device,
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
        COUNT(DISTINCT CASE WHEN s.hash IN (SELECT hash FROM dupes) THEN s.hash END) AS dup_hash_count,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.filename END) AS filename,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.size_bytes END) AS leaf_size,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.hash END) AS leaf_hash,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.mtime END) AS leaf_mtime,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.last_seen_at END) AS leaf_last_seen_at,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.file_category END) AS leaf_file_category,
        MAX(CASE WHEN s.entry_type = 'file' THEN s.path_display END) AS leaf_path_display,
        ANY_VALUE(s.segment_display) AS segment_display,
        STRING_AGG(DISTINCT f2.host ORDER BY f2.host) AS other_hosts,
        BOOL_OR(
            s.entry_type = 'file'
            AND s.inode IS NOT NULL AND s.device IS NOT NULL
            AND (s.device, s.inode) IN (SELECT device, inode FROM hard_linked_inodes)
        ) AS is_hard_linked
    FROM scoped s
    LEFT JOIN files f2 ON f2.hash = s.hash AND f2.host != ? AND s.hash IS NOT NULL
                       AND s.entry_type = 'file'
    WHERE s.segment IS NOT NULL AND s.segment != ''
    GROUP BY s.segment
    ORDER BY ANY_VALUE(s.entry_type) ASC, s.segment
    """

    # param order: hard_linked host, dupes host, dupes min_size, scoped host, path LIKE, path =, join host
    params = [host, host, min_size, host, prefix + "/%", prefix, host]
    rows = db.query(sql, params)
    result = []
    for r in rows:
        result.append(
            LsEntry(
                segment=r[0],
                entry_type=r[1],
                file_count=r[2] or 0,
                total_bytes=r[3],
                dup_count=r[4] or 0,
                dup_hash_count=r[5] or 0,
                filename=r[6],
                size_bytes=r[7],
                hash=r[8],
                mtime=r[9],
                last_seen_at=r[10],
                file_category=r[11],
                path_display=r[12],
                segment_display=r[13],
                other_hosts=r[14],
                is_hard_linked=bool(r[15]),
            )
        )
    return result


@app.get("/files", response_model=list[FileEntry])
def list_files(
    host: Optional[str] = None,
    path_prefix: Optional[str] = None,
    path_contains: Optional[str] = None,
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
    if path_contains:
        conditions.append("f.path LIKE '%' || ? || '%'")
        params.append(path_contains.lower())
    if hash:
        h = hash.lower()
        if len(h) == 64:
            conditions.append("f.hash = ?")
        else:
            conditions.append("f.hash LIKE '%' || ? || '%'")
        params.append(h)
    if name:
        # glob-style: convert * → %, ? → _, escape literal % and _ with backslash.
        # ESCAPE '\' tells DuckDB to treat \ as the escape character in this LIKE.
        sql_pat = (
            name.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            .replace("*", "%")
            .replace("?", "_")
        )
        conditions.append("f.filename LIKE ? ESCAPE '\\'")
        params.append(sql_pat)
    if iname:
        sql_pat = (
            iname.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            .replace("*", "%")
            .replace("?", "_")
        )
        conditions.append("LOWER(f.filename) LIKE LOWER(?) ESCAPE '\\'")
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
        f.file_category, f.size_bytes, f.hash, f.mtime, f.last_seen_at,
        STRING_AGG(DISTINCT f2.host ORDER BY f2.host) AS other_hosts
    FROM files f
    LEFT JOIN files f2 ON f2.hash = f.hash AND f2.host != f.host AND f.hash IS NOT NULL
    WHERE {where} {dup_clause}
    GROUP BY f.host, f.drive, f.path_display, f.filename, f.ext,
             f.file_category, f.size_bytes, f.hash, f.mtime, f.last_seen_at
    ORDER BY f.path_display
    LIMIT ?
    """
    params.append(limit)

    rows = db.query(sql, params)
    return [
        FileEntry(
            host=r[0],
            drive=r[1],
            path_display=r[2],
            filename=r[3],
            ext=r[4],
            file_category=r[5],
            size_bytes=r[6],
            hash=r[7],
            mtime=r[8],
            last_seen_at=r[9],
            other_hosts=r[10],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------


@app.get("/init")
def init_data(request: Request, path: str = "/", min_size: int = Query(0, ge=0)):
    """Combined startup endpoint: returns hosts + root ls in one round trip."""
    hosts = list_hosts()
    root_ls = {
        h.host: ls_files(path=path, host=h.host, depth=1, min_size=min_size)
        for h in hosts
    }
    # Attempt reverse-DNS on the client IP so the frontend can pre-select the
    # matching host. Fails gracefully (returns None) on any lookup error.
    client_host = None
    try:
        client_ip = request.client.host if request.client else None
        if client_ip in ("127.0.0.1", "::1"):
            # Browser is on the same machine as the server
            client_host = socket.gethostname().split(".")[0]
        elif client_ip:
            name, _, _ = socket.gethostbyaddr(client_ip)
            client_host = name.split(".")[0]
    except Exception:
        pass
    return {"hosts": hosts, "root_ls": root_ls, "client_host": client_host}


@app.get("/hosts", response_model=list[HostEntry])
def list_hosts():
    rows = db.query("""
        WITH all_hosts AS (
            SELECT host FROM host_stats
            UNION
            SELECT DISTINCT host FROM scan_runs
        ),
        latest_run AS (
            SELECT host, root_path, root_path_display, started_at,
                   ROW_NUMBER() OVER (PARTITION BY host ORDER BY id DESC) AS rn
            FROM scan_runs
        ),
        latest_complete AS (
            SELECT host, MAX(started_at) AS last_scan_at
            FROM scan_runs WHERE status = 'complete'
            GROUP BY host
        )
        SELECT ah.host, lc.last_scan_at,
               COALESCE(lr.root_path_display, lr.root_path) AS last_scan_root,
               COALESCE(hs.total_files, 0), hs.total_bytes, COALESCE(hs.total_hashed, 0)
        FROM all_hosts ah
        LEFT JOIN host_stats hs ON hs.host = ah.host
        LEFT JOIN latest_run lr ON lr.host = ah.host AND lr.rn = 1
        LEFT JOIN latest_complete lc ON lc.host = ah.host
        ORDER BY ah.host
    """)
    return [
        HostEntry(
            host=r[0],
            last_scan_at=r[1],
            last_scan_root=r[2],
            total_files=r[3],
            total_bytes=r[4],
            total_hashed=r[5],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

# Simple TTL cache for /stats/overview — the dup aggregation is expensive
# on large tables. Cache keyed by (min_size, categories, hosts); entries
# expire after SIFT_STATS_CACHE_TTL seconds (default 60).
_stats_cache: dict[tuple, tuple] = {}  # key -> (StatsOverview, timestamp)
_STATS_CACHE_TTL = int(os.environ.get("SIFT_STATS_CACHE_TTL", "60"))


def _invalidate_stats_cache() -> None:
    """Call after any write that changes file counts or hashes."""
    _stats_cache.clear()


@app.get("/stats/overview", response_model=StatsOverview)
def stats_overview(
    min_size: int = Query(0, ge=0),
    categories: str = Query(
        "", description="Comma-separated file categories to filter dup stats"
    ),
    hosts: str = Query("", description="Comma-separated host names to filter stats"),
):
    cache_key = (min_size, categories, hosts)
    cached = _stats_cache.get(cache_key)
    if cached is not None:
        result, ts = cached
        if time.monotonic() - ts < _STATS_CACHE_TTL:
            return result

    host_list = [h.strip() for h in hosts.split(",") if h.strip()] if hosts else []
    host_where = ""
    if host_list:
        placeholders = ", ".join(["?" for _ in host_list])
        host_where = f"AND host IN ({placeholders})"

    row = db.query_one(
        f"""
        WITH dup_hashes AS (
            SELECT hash FROM files
            WHERE hash IS NOT NULL {host_where}
            GROUP BY hash HAVING COUNT(*) > 1
        )
        SELECT
            COUNT(*) AS total_files,
            COUNT(DISTINCT f.host) AS total_hosts,
            COUNT(DISTINCT f.hash) FILTER (WHERE f.hash IS NOT NULL) AS unique_hashes,
            COUNT(*) FILTER (WHERE dh.hash IS NOT NULL) AS dup_files,
            SUM(f.size_bytes) AS total_bytes
        FROM files f
        LEFT JOIN dup_hashes dh ON f.hash = dh.hash
        WHERE 1=1 {host_where}
    """,
        host_list + host_list,
    )

    # Dup sets / wasted bytes, optionally filtered by min_size, categories, and hosts
    category_list = (
        [c.strip() for c in categories.split(",") if c.strip()] if categories else []
    )
    cat_clause = ""
    dup_params = [min_size] + host_list
    if category_list:
        placeholders = ", ".join(["?" for _ in category_list])
        cat_clause = f"AND file_category IN ({placeholders})"
        dup_params += category_list

    dup_row = db.query_one(
        f"""
        SELECT
            COUNT(DISTINCT hash) AS dup_sets,
            SUM(size_bytes) - SUM(min_size) AS wasted
        FROM (
            SELECT hash, COUNT(*) AS cnt, SUM(size_bytes) AS size_bytes,
                   MIN(size_bytes) AS min_size
            FROM files
            WHERE hash IS NOT NULL AND size_bytes >= ?
              {host_where}
              {cat_clause}
            GROUP BY hash
            HAVING COUNT(*) > 1
        ) t
    """,
        dup_params,
    )

    total_files = row[0] if row else 0
    total_hosts = row[1] if row else 0
    unique_hashes = row[2] if row else 0
    total_bytes = row[4] if row else None
    duplicate_sets = dup_row[0] if dup_row else 0
    wasted_bytes = dup_row[1] if dup_row else None

    result = StatsOverview(
        total_files=total_files,
        total_hosts=total_hosts,
        unique_hashes=unique_hashes,
        duplicate_sets=duplicate_sets,
        wasted_bytes=wasted_bytes,
        total_bytes=total_bytes,
    )
    _stats_cache[cache_key] = (result, time.monotonic())
    return result


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
        result.append(
            DuplicateSet(
                hash=hash_val,
                filename=filename,
                size_bytes=size_bytes,
                copy_count=copy_count,
                wasted_bytes=wasted_bytes,
                locations=locations,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Directory autocomplete
# ---------------------------------------------------------------------------


@app.get("/directories")
def list_directories(q: str = "", limit: int = Query(20, le=100)):
    q = q.strip()
    if len(q) < 2:
        return []
    rows = db.query(
        """
        SELECT dir_path, dir_display FROM (
            SELECT
                regexp_replace(path, '/[^/]+$', '') AS dir_path,
                ANY_VALUE(regexp_replace(path_display, '/[^/]+$', '')) AS dir_display
            FROM files
            GROUP BY regexp_replace(path, '/[^/]+$', '')
            HAVING regexp_replace(path, '/[^/]+$', '') != ''
        ) sub
        WHERE lower(dir_path) LIKE '%' || lower(?) || '%'
        ORDER BY dir_path
        LIMIT ?
        """,
        [q, limit],
    )
    results = {r[0]: r[1] or r[0] for r in rows}

    # Also include any ancestor paths that contain the query but have no files
    # directly in them (e.g. BetterZip.app only has files in Contents/).
    # Without this the UI expands the ancestor as a non-highlighted node.
    q_lower = q.lower()
    extra = {}
    for dir_path in list(results):
        parts = dir_path.split(
            "/"
        )  # ['', 'users', 'brian', 'downloads', 'betterzip.app', ...]
        for i in range(2, len(parts)):
            ancestor = "/".join(parts[:i])
            if (
                q_lower in ancestor.lower()
                and ancestor not in results
                and ancestor not in extra
            ):
                extra[ancestor] = ancestor  # no display path available; use raw path

    results.update(extra)
    return [{"dir_path": p, "dir_display": results[p]} for p in sorted(results)[:limit]]


# ---------------------------------------------------------------------------
# Static frontend — mounted LAST so API routes take precedence
# ---------------------------------------------------------------------------

_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if not os.path.isdir(_frontend_dist):
    # Fallback for non-editable installs: check current working directory
    _frontend_dist = os.path.join(os.getcwd(), "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
