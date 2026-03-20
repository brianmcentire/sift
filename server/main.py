"""FastAPI application — all endpoints."""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

import json

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sift.server")


def _env_flag(name: str, default: str = "0") -> bool:
    value = os.environ.get(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


_PERF_LOG_ENABLED = _env_flag("SIFT_PERF_LOG", "0")


def _log_perf(endpoint: str, start: float, **fields) -> None:
    """Emit endpoint-level performance metrics when perf logging is enabled."""
    if not _PERF_LOG_ENABLED:
        return
    elapsed_ms = (time.monotonic() - start) * 1000.0
    parts = [f"{k}={v}" for k, v in fields.items()]
    suffix = f" {' '.join(parts)}" if parts else ""
    logger.info("perf endpoint=%s elapsed_ms=%.1f%s", endpoint, elapsed_ms, suffix)


_query_cache_lock = threading.Lock()
_QUERY_CACHE_TTL = int(os.environ.get("SIFT_QUERY_CACHE_TTL", "300"))
_REPORT_SIZE_DISTRIBUTION_CACHE_TTL = int(
    os.environ.get(
        "SIFT_REPORT_SIZE_DISTRIBUTION_CACHE_TTL", str(_QUERY_CACHE_TTL * 10)
    )
)
_QUERY_CACHE_MAX = int(os.environ.get("SIFT_QUERY_CACHE_MAX", "2000"))
_ls_cache: dict[tuple, tuple] = {}
_directories_cache: dict[tuple, tuple] = {}
_tree_children_cache: dict[tuple, tuple] = {}
_tree_dup_metrics_cache: dict[tuple, tuple] = {}
_stats_overview_cache: dict[tuple, tuple] = {}
_hosts_cache: dict[tuple, tuple] = {}
_report_size_distribution_cache: dict[tuple, tuple] = {}


_MAINTENANCE_ENABLED = _env_flag("SIFT_MAINTENANCE_ENABLED", "1")
_MAINTENANCE_COOLDOWN_SEC = int(os.environ.get("SIFT_MAINTENANCE_COOLDOWN_SEC", "10"))
_MAINTENANCE_MIN_IDLE_SEC = int(os.environ.get("SIFT_MAINTENANCE_MIN_IDLE_SEC", "120"))
_DUP_METRICS_LIVE_MAX_FILES = int(
    os.environ.get("SIFT_DUP_METRICS_LIVE_MAX_FILES", "200000")
)
_maintenance_stop_event = threading.Event()
_maintenance_thread: threading.Thread | None = None
_startup_thread: threading.Thread | None = None
_maintenance_lock = threading.Lock()
_last_api_activity = time.monotonic()


def _cache_get(cache: dict, key: tuple, ttl_sec: int | None = None):
    now = time.monotonic()
    ttl = _QUERY_CACHE_TTL if ttl_sec is None else max(0, int(ttl_sec))
    with _query_cache_lock:
        item = cache.get(key)
        if item is None:
            return None
        value, ts = item
        if now - ts > ttl:
            cache.pop(key, None)
            return None
        return value


def _cache_set(cache: dict, key: tuple, value) -> None:
    now = time.monotonic()
    with _query_cache_lock:
        cache[key] = (value, now)
        if len(cache) <= _QUERY_CACHE_MAX:
            return
        oldest_key = None
        oldest_ts = now
        for k, (_, ts) in cache.items():
            if ts < oldest_ts:
                oldest_ts = ts
                oldest_key = k
        if oldest_key is not None:
            cache.pop(oldest_key, None)


def _invalidate_query_caches() -> None:
    with _query_cache_lock:
        _ls_cache.clear()
        _directories_cache.clear()
        _tree_children_cache.clear()
        _tree_dup_metrics_cache.clear()
        _stats_overview_cache.clear()
        _hosts_cache.clear()
        _report_size_distribution_cache.clear()


from server import db
from server.models import (
    DuplicateLocation,
    DuplicateSet,
    ReportCrossHostSummary,
    ReportDuplicatesResponse,
    ReportGlobalDuplicateSummary,
    ReportHostOnlyRow,
    ReportInventoryResponse,
    ReportSizeBucketRow,
    ReportSizeDistributionResponse,
    ReportTombstonesResponse,
    ReportTopOpportunity,
    FileEntry,
    FilePageResponse,
    DuplicateHashCountResponse,
    FileRecord,
    HashCheckRequest,
    HostEntry,
    HostRootEntry,
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
    TreeChildrenResponse,
    TreeDupMetric,
    TreeDupMetricsResponse,
    UpsertResponse,
)


def _startup_refresh() -> None:
    """Refresh host_stats (cheap) then bootstrap aggregates if needed."""
    if _maintenance_stop_event.is_set():
        return
    try:
        hosts = db.query("SELECT DISTINCT host FROM files")
        for (host,) in hosts:
            db.refresh_host_stats(host)
        if hosts:
            logger.info("Refreshed host_stats for %d host(s)", len(hosts))
            _invalidate_query_caches()
    except Exception:
        logger.exception("host_stats refresh failed")
    _bootstrap_aggregates()


def _bootstrap_aggregates() -> None:
    """Populate aggregate tables on startup if they're empty but files exist.

    Runs in a background thread so server startup isn't blocked.
    """
    try:
        if _maintenance_stop_event.is_set():
            return
        hhs_row = db.query_one("SELECT COUNT(*) FROM host_hash_stats")
        hhs_count = int(hhs_row[0]) if hhs_row else 0
        if hhs_count > 0:
            return  # already populated

        hosts_with_files = db.query(
            "SELECT DISTINCT host FROM files WHERE hash IS NOT NULL"
        )
        if not hosts_with_files:
            return

        for (host,) in hosts_with_files:
            if _maintenance_stop_event.is_set():
                return
            logger.info("Bootstrapping aggregates for host %s ...", host)
            start = time.monotonic()
            db.refresh_host_hash_stats(host)
            db.set_aggregate_meta(f"host_hash_stats:{host}", "fresh")
            elapsed = time.monotonic() - start
            logger.info("Bootstrapped host_hash_stats for %s in %.1fs", host, elapsed)

        if _maintenance_stop_event.is_set():
            return
        logger.info("Bootstrapping global hash_stats ...")
        start = time.monotonic()
        db.refresh_hash_stats()
        db.set_aggregate_meta("hash_stats", "fresh")
        logger.info("Bootstrapped hash_stats in %.1fs", time.monotonic() - start)

        if _maintenance_stop_event.is_set():
            return
        logger.info("Bootstrapping directory_index ...")
        start = time.monotonic()
        db.refresh_directory_index()
        db.set_aggregate_meta("directory_index", "fresh")
        logger.info("Bootstrapped directory_index in %.1fs", time.monotonic() - start)

        if _maintenance_stop_event.is_set():
            return
        _invalidate_query_caches()
        logger.info("Aggregate bootstrap complete.")
    except Exception:
        logger.exception("Aggregate bootstrap failed")


def _cleanup_stale_scan_runs():
    """Mark any scan_runs left in 'running' state as 'interrupted'.

    Called once at startup before accepting requests so that
    _running_scan_count() returns correct values from the first request.
    """
    stale = db.query("SELECT id, host FROM scan_runs WHERE status = 'running'")
    if stale:
        db.execute(
            "UPDATE scan_runs SET status = 'interrupted' WHERE status = 'running'"
        )
        hosts = {r[1] for r in stale}
        logger.info(
            "Marked %d stale running scan_run(s) as interrupted (hosts: %s)",
            len(stale),
            ", ".join(sorted(hosts)),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _maintenance_thread
    db_path = os.environ.get("SIFT_DB_PATH") or db.get_db_path()
    db.init_db(db_path)
    _cleanup_stale_scan_runs()
    _maintenance_stop_event.clear()
    if _MAINTENANCE_ENABLED:
        _maintenance_thread = threading.Thread(
            target=_maintenance_loop,
            daemon=True,
            name="maintenance-worker",
        )
        _maintenance_thread.start()
    # Refresh host_stats on startup (cheap) and bootstrap aggregates if empty
    global _startup_thread
    t = threading.Thread(
        target=_startup_refresh,
        daemon=True,
        name="startup-refresh",
    )
    t.start()
    _startup_thread = t
    try:
        yield
    finally:
        _maintenance_stop_event.set()
        if _maintenance_thread and _maintenance_thread.is_alive():
            _maintenance_thread.join(timeout=1.0)
        _maintenance_thread = None
        if _startup_thread is not None and _startup_thread.is_alive():
            _startup_thread.join(timeout=2.0)
            if _startup_thread.is_alive():
                logger.warning("startup-refresh thread did not exit within 2s")
        _startup_thread = None
        # Join any outstanding stats-refresh threads
        with _stats_refresh_lock:
            threads = list(_stats_refresh_threads.values())
            _stats_refresh_threads.clear()
        for t in threads:
            if t.is_alive():
                t.join(timeout=2.0)
                if t.is_alive():
                    logger.warning("stats-refresh thread %s did not exit within 2s", t.name)


# ---------------------------------------------------------------------------
# Periodic host stats refresh (during active scans)
# ---------------------------------------------------------------------------

_STATS_REFRESH_INTERVAL = 60  # seconds between mid-scan refreshes
_last_stats_refresh: dict[str, float] = {}  # host -> monotonic time
_stats_refresh_lock = threading.Lock()
_stats_refresh_threads: dict[str, threading.Thread] = {}


def _maybe_refresh_host_stats(host: str) -> None:
    """Refresh host_stats if it's been ≥60s since last refresh for this host.

    Runs in a background thread so it doesn't add latency to the flush response.
    Skips if a refresh is already in progress for this host or shutdown is underway.
    """
    if _maintenance_stop_event.is_set():
        return
    now = time.monotonic()
    with _stats_refresh_lock:
        if now - _last_stats_refresh.get(host, 0) < _STATS_REFRESH_INTERVAL:
            return
        # Skip if a refresh thread for this host is still alive
        existing = _stats_refresh_threads.get(host)
        if existing is not None and existing.is_alive():
            return
        _last_stats_refresh[host] = now

    def _do_refresh():
        try:
            if _maintenance_stop_event.is_set():
                return
            db.refresh_host_stats(host)
            _invalidate_query_caches()
        except Exception:
            pass

    t = threading.Thread(
        target=_do_refresh, daemon=True, name=f"stats-refresh-{host}"
    )
    t.start()
    with _stats_refresh_lock:
        _stats_refresh_threads[host] = t


app = FastAPI(title="sift", version="0.9.3", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)


def _running_scan_count(exclude_host: str | None = None) -> int:
    if exclude_host:
        row = db.query_one(
            "SELECT COUNT(*) FROM scan_runs WHERE status = 'running' AND host != ?",
            [exclude_host],
        )
    else:
        row = db.query_one("SELECT COUNT(*) FROM scan_runs WHERE status = 'running'")
    return int(row[0]) if row else 0


def _maintenance_mode() -> tuple[str, int]:
    """Return mode + max priority allowed for current activity state."""
    running = _running_scan_count()
    idle_for = max(0.0, time.monotonic() - _last_api_activity)
    if running > 0:
        return "ACTIVE", 40
    if idle_for < _MAINTENANCE_MIN_IDLE_SEC:
        return "WARM", 60
    return "IDLE", 100


def _run_maintenance_job(job: dict) -> None:
    job_type = job.get("job_type")
    host = job.get("host")
    label = f"{job_type}" + (f" ({host})" if host else "")
    logger.info("maintenance: starting %s", label)
    start = time.monotonic()
    if job_type == "refresh_hash_stats":
        db.set_aggregate_meta("hash_stats", "building")
        db.refresh_hash_stats()
        db.set_aggregate_meta("hash_stats", "fresh")
    elif job_type == "refresh_directory_index":
        db.set_aggregate_meta("directory_index", "building")
        db.refresh_directory_index()
        db.set_aggregate_meta("directory_index", "fresh")
    elif job_type == "refresh_host_hash_stats":
        if not host:
            raise ValueError("refresh_host_hash_stats requires host")
        db.set_aggregate_meta(f"host_hash_stats:{host}", "building")
        db.refresh_host_hash_stats(host)
        db.set_aggregate_meta(f"host_hash_stats:{host}", "fresh")
    elif job_type == "refresh_aggregates_for_host":
        if not host:
            raise ValueError("refresh_aggregates_for_host requires host")
        db.set_aggregate_meta(f"host_hash_stats:{host}", "building")
        db.refresh_host_hash_stats(host)
        db.set_aggregate_meta(f"host_hash_stats:{host}", "fresh")
        db.set_aggregate_meta("hash_stats", "building")
        db.refresh_hash_stats()
        db.set_aggregate_meta("hash_stats", "fresh")
        db.set_aggregate_meta("directory_index", "building")
        db.refresh_directory_index()
        db.set_aggregate_meta("directory_index", "fresh")
    else:
        raise ValueError(f"unknown maintenance job type: {job_type}")
    elapsed = time.monotonic() - start
    logger.info("maintenance: completed %s in %.1fs", label, elapsed)


def _run_one_maintenance_cycle(force: bool = False) -> dict:
    mode, max_priority = _maintenance_mode()
    if not force and mode == "ACTIVE":
        return {"mode": mode, "ran": False, "reason": "active_scans"}

    with _maintenance_lock:
        job = db.dequeue_maintenance_job(None if force else max_priority)
        if job is None:
            return {"mode": mode, "ran": False, "reason": "no_job"}

        try:
            _run_maintenance_job(job)
            db.complete_maintenance_job(job["id"])
            return {
                "mode": mode,
                "ran": True,
                "job_id": job["id"],
                "job_type": job["job_type"],
            }
        except Exception as exc:
            requeue = int(job.get("attempts", 1)) < 3
            db.fail_maintenance_job(job["id"], str(exc), requeue=requeue)
            return {
                "mode": mode,
                "ran": True,
                "job_id": job["id"],
                "job_type": job.get("job_type"),
                "error": str(exc),
                "requeue": requeue,
            }


def _maintenance_loop() -> None:
    logger.info("maintenance worker started")
    while not _maintenance_stop_event.wait(_MAINTENANCE_COOLDOWN_SEC):
        try:
            _run_one_maintenance_cycle(force=False)
        except Exception as exc:
            logger.warning("maintenance loop error: %s", exc)
    logger.info("maintenance worker stopped")


def _detect_client_host(request: Request) -> str | None:
    """Best-effort client host detection for frontend default host selection."""
    try:
        client_ip = request.client.host if request.client else None
        if client_ip in ("127.0.0.1", "::1"):
            return socket.gethostname().split(".")[0]
        if client_ip:
            name, _, _ = socket.gethostbyaddr(client_ip)
            return name.split(".")[0]
    except Exception:
        return None
    return None


@app.middleware("http")
async def log_requests(request: Request, call_next):
    global _last_api_activity
    received = datetime.now().strftime("%H:%M:%S")
    start = time.monotonic()
    path = request.url.path
    token = db.push_request_context(f"{request.method} {path}")
    try:
        response = await call_next(request)
    finally:
        db.pop_request_context(token)
    elapsed = time.monotonic() - start
    # Skip static asset noise
    if path.startswith("/assets/") or path == "/favicon.ico":
        return response
    if not path.startswith("/maintenance") and request.method in {"POST", "PATCH", "DELETE"}:
        _last_api_activity = time.monotonic()
    if elapsed > 1.0:
        qs = str(request.url.query)
        full = f"{path}?{qs}" if qs else path
        logger.warning(
            "(recv %s) %s %s %d — %.1fs",
            received,
            request.method,
            full,
            response.status_code,
            elapsed,
        )
    elif request.method in ("POST", "PATCH"):
        logger.info(
            "%s %s %d — %.3fs", request.method, path, response.status_code, elapsed
        )
    else:
        logger.info(
            "%s %s %d — %.3fs", request.method, path, response.status_code, elapsed
        )
    return response


@app.exception_handler(db.DBTimeoutError)
async def db_timeout_handler(request: Request, exc: db.DBTimeoutError):
    logger.warning(
        "db-timeout type=%s endpoint=%s operation=%s timeout=%.1fs sql=%s",
        exc.timeout_type,
        exc.endpoint,
        exc.operation,
        exc.timeout_sec,
        exc.sql,
    )
    status_code = 503 if exc.timeout_type == "lock_wait" else 504
    return JSONResponse(status_code=status_code, content=exc.to_dict())


# Static frontend is mounted AFTER all API routes (see bottom of file)


# ---------------------------------------------------------------------------
# Scan runs
# ---------------------------------------------------------------------------


@app.post("/scan-runs", response_model=ScanRunCreatedResponse)
def create_scan_run(body: ScanRunCreate):
    # Abandon any prior 'running' scans for same host + drive + root_path
    stale = db.query(
        "SELECT id FROM scan_runs WHERE host = ? AND drive = ? AND root_path = ? AND status = 'running'",
        [body.host, body.drive, body.root_path],
    )
    if stale:
        db.execute(
            "UPDATE scan_runs SET status = 'failed' "
            "WHERE host = ? AND drive = ? AND root_path = ? AND status = 'running'",
            [body.host, body.drive, body.root_path],
        )
        # Crashed/stale scan — refresh stats so they reflect reality
        db.refresh_host_stats(body.host)
        _invalidate_query_caches()
    db.execute(
        "INSERT INTO scan_runs (host, drive, root_path, root_path_display, started_at, status) "
        "VALUES (?, ?, ?, ?, ?, 'running')",
        [
            body.host,
            body.drive,
            body.root_path,
            body.root_path_display,
            body.started_at.isoformat(),
        ],
    )
    row = db.query_one(
        "SELECT id FROM scan_runs WHERE host = ? AND drive = ? AND root_path = ? AND status = 'running' "
        "ORDER BY id DESC LIMIT 1",
        [body.host, body.drive, body.root_path],
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
        if body.status == "complete":
            # Host-local aggregates are always refreshed immediately.
            try:
                db.refresh_host_hash_stats(host)
                db.set_aggregate_meta(f"host_hash_stats:{host}", "fresh")
            except Exception as exc:
                logger.warning(
                    "host aggregate refresh failed for host %s: %s", host, exc
                )

            # Global aggregate rebuilds can be slow — always defer to
            # maintenance queue so the PATCH returns immediately.
            db.set_aggregate_meta(
                "hash_stats",
                "stale",
                "Queued for refresh after scan completion",
            )
            db.set_aggregate_meta(
                "directory_index",
                "stale",
                "Queued for refresh after scan completion",
            )
            db.enqueue_maintenance_job("refresh_hash_stats", priority=80)
            db.enqueue_maintenance_job("refresh_directory_index", priority=80)
        _invalidate_query_caches()
    return {"ok": True}


@app.get("/scan-runs", response_model=list[ScanRunResponse])
def list_scan_runs(host: Optional[str] = None, limit: int = Query(50, le=500)):
    if host:
        rows = db.query(
            "SELECT id, host, drive, root_path, root_path_display, started_at, status FROM scan_runs "
            "WHERE host = ? ORDER BY id DESC LIMIT ?",
            [host, limit],
        )
    else:
        rows = db.query(
            "SELECT id, host, drive, root_path, root_path_display, started_at, status FROM scan_runs "
            "ORDER BY id DESC LIMIT ?",
            [limit],
        )
    return [
        ScanRunResponse(
            id=r[0],
            host=r[1],
            drive=r[2],
            root_path=r[3],
            root_path_display=r[4],
            started_at=r[5],
            status=r[6],
        )
        for r in rows
    ]


@app.get("/maintenance/jobs")
def list_maintenance_jobs(limit: int = Query(50, ge=1, le=500)):
    rows = db.list_maintenance_jobs(limit)
    return {
        "jobs": [
            {
                "id": r[0],
                "job_type": r[1],
                "host": r[2],
                "status": r[3],
                "priority": r[4],
                "attempts": r[5],
                "payload": r[6],
                "created_at": r[7],
                "updated_at": r[8],
                "last_error": r[9],
            }
            for r in rows
        ]
    }


@app.post("/maintenance/run-now")
def run_maintenance_now(force: bool = Query(False)):
    if not _MAINTENANCE_ENABLED and not force:
        return {"ok": False, "reason": "maintenance_disabled"}
    result = _run_one_maintenance_cycle(force=force)
    return {"ok": True, **result}


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
    _invalidate_query_caches()
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

    if body.unsafe_not_seen_before is not None:
        cutoff_ts = body.unsafe_not_seen_before.isoformat() + "T00:00:00+00:00"
        sql = f"""
            candidates AS (
                SELECT f.host, f.drive, f.path
                FROM files f
                WHERE {base_where}
                  AND (
                      f.last_seen_at IS NULL
                      OR epoch(f.last_seen_at) < epoch(CAST(? AS TIMESTAMPTZ))
                  )
            )
        """
        return sql, [*params, cutoff_ts]

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
             AND sr.drive = f.drive
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
    if body.deleted_only and body.unsafe_not_seen_before is not None:
        raise HTTPException(
            400,
            "deleted_only and unsafe_not_seen_before cannot be combined",
        )

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
        db.set_aggregate_meta(
            f"host_hash_stats:{body.host}",
            "stale",
            "Queued for refresh after trim",
        )
        db.set_aggregate_meta(
            "hash_stats",
            "stale",
            "Queued for refresh after trim",
        )
        db.set_aggregate_meta(
            "directory_index",
            "stale",
            "Queued for refresh after trim",
        )
        db.enqueue_maintenance_job(
            "refresh_aggregates_for_host",
            host=body.host,
            priority=80,
        )
        _invalidate_query_caches()

    return {"matched": matched, "deleted": deleted, "preview_paths": []}


# ---------------------------------------------------------------------------
# Cache endpoint (rehash optimization)
# ---------------------------------------------------------------------------


@app.get("/files/cache")
def get_cache(host: str, root: str, drive: str = Query("")):
    # Returns a compact array-of-arrays [path, mtime, size_bytes] to minimize
    # JSON payload size and avoid per-row Pydantic model instantiation overhead.
    root_lower = root.lower()
    like_pattern = "/%" if root_lower == "/" else root_lower + "/%"
    rows = db.query(
        "SELECT path, mtime, size_bytes FROM files "
        "WHERE host = ? AND drive = ? AND (path LIKE ? OR path = ?)",
        [host, drive, like_pattern, root_lower],
    )
    return {"files": [[r[0], r[1], r[2]] for r in rows]}


@app.get("/files/cache/stream")
def get_cache_stream(host: str, root: str, drive: str = Query("")):
    """Stream cache entries as NDJSON — one JSON array per line.
    Rows are fetched under the lock then streamed from memory, so the
    lock is held only for the DB query, not the entire HTTP transfer."""
    root_lower = root.lower()
    like_pattern = "/%" if root_lower == "/" else root_lower + "/%"
    rows = db.query(
        "SELECT path, mtime, size_bytes FROM files "
        "WHERE host = ? AND drive = ? AND (path LIKE ? OR path = ?)",
        [host, drive, like_pattern, root_lower],
    )

    def generate():
        for r in rows:
            yield json.dumps([r[0], r[1], r[2]]) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/files/hashes")
def stream_hashes(
    host: str = Query(""),
    path_prefix: str = Query(""),
    drive: str = Query(""),
    min_size: int = Query(0, ge=0),
):
    """Stream file hashes as tab-separated text (hash\\tpath), one per line.

    Only includes entries where hash IS NOT NULL.  No result limit.
    Payload is compact (~70 bytes/row) — suitable for building large hash sets.
    """
    conditions = ["hash IS NOT NULL"]
    params: list = []
    if host:
        conditions.append("host = ?")
        params.append(host)
    if path_prefix:
        p = path_prefix.lower().rstrip("/")
        conditions.append("(path LIKE ? OR path = ?)")
        params.extend([p + "/%", p])
    if drive:
        conditions.append("drive = ?")
        params.append(drive)
    if min_size:
        conditions.append("size_bytes >= ?")
        params.append(min_size)
    where = " AND ".join(conditions)
    rows = db.query(f"SELECT hash, path FROM files WHERE {where}", params)

    def generate():
        for r in rows:
            yield r[0] + "\t" + r[1] + "\n"

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/files/hashes/check")
def check_hashes(req: HashCheckRequest):
    """Check which of the provided hashes exist in the specified scope.

    Accepts a list of hashes and returns the subset found in the datastore,
    optionally filtered by host, path prefix, drive, min size, and with
    path-level exclusions.  Batches the IN clause to keep query plans fast.
    """
    if not req.hashes:
        return []

    req_start = time.monotonic()

    # Build scope conditions
    scope_conds = ["hash IS NOT NULL"]
    scope_params: list = []

    if req.host:
        scope_conds.append("host = ?")
        scope_params.append(req.host)
    if req.path_prefix:
        p = req.path_prefix.lower().rstrip("/")
        scope_conds.append("(path LIKE ? OR path = ?)")
        scope_params.extend([p + "/%", p])
    if req.drive:
        scope_conds.append("drive = ?")
        scope_params.append(req.drive)
    if req.min_size:
        scope_conds.append("size_bytes >= ?")
        scope_params.append(req.min_size)

    for exc in req.exclude:
        prefix = exc.prefix.lower().rstrip("/")
        scope_conds.append("NOT (host = ? AND (path LIKE ? OR path = ?))")
        scope_params.extend([exc.host, prefix + "/%", prefix])

    where = " AND ".join(scope_conds)

    BATCH = 10_000
    found: set[str] = set()
    for i in range(0, len(req.hashes), BATCH):
        batch = req.hashes[i : i + BATCH]
        placeholders = ",".join(["?"] * len(batch))
        sql = (
            f"SELECT DISTINCT hash FROM files "
            f"WHERE hash IN ({placeholders}) AND {where}"
        )
        rows = db.query(sql, batch + scope_params)
        found.update(r[0] for r in rows)

    _log_perf(
        "/files/hashes/check", req_start,
        input_hashes=len(req.hashes), found=len(found),
    )
    return sorted(found)


@app.post("/files/hashes/hosts")
def hash_hosts(hashes: list[str]):
    """Return hash → comma-separated host list for the given hashes.

    Uses the pre-aggregated host_hash_stats table for fast lookup.
    Returns a dict like {"abc123": "host1,host2", ...}.
    """
    if not hashes:
        return {}

    req_start = time.monotonic()
    result: dict[str, str] = {}

    BATCH = 10_000
    for i in range(0, len(hashes), BATCH):
        batch = hashes[i : i + BATCH]
        placeholders = ",".join(["?"] * len(batch))
        rows = db.query(
            f"SELECT hash, STRING_AGG(DISTINCT host, ',' ORDER BY host) "
            f"FROM host_hash_stats WHERE hash IN ({placeholders}) GROUP BY hash",
            batch,
        )
        for r in rows:
            result[r[0]] = r[1]

    _log_perf("/files/hashes/hosts", req_start, input=len(hashes), found=len(result))
    return result


# ---------------------------------------------------------------------------
# File listing
# ---------------------------------------------------------------------------


@app.get("/files/ls/dup-hash")
def ls_dup_hash(
    path: str = Query("/"),
    host: str = Query(""),
    drive: str = Query(""),
    min_size: int = Query(0, ge=0),
):
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
          AND f.drive = ?
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
        [host, host, drive, prefix + "/%", prefix, min_size, host, min_size],
    )
    if row is None:
        raise HTTPException(
            status_code=404, detail="No duplicate hash found in subtree"
        )
    return {"hash": row[0]}


@app.get("/files/duplicates-in-subtree", response_model=list[FileEntry])
def duplicates_in_subtree(
    host: str = Query(...),
    drive: str = Query(""),
    path_prefix: str = Query(...),
    min_size: int = Query(0, ge=0),
    limit: int = Query(1000, le=10000),
):
    """Return all files that are duplicated within a subtree, grouped by hash."""
    req_start = time.monotonic()
    prefix = path_prefix.lower().rstrip("/")

    # Check for pre-aggregated host stats to run the optimized query.
    has_host_hash_stats = db.query_one(
        "SELECT 1 FROM host_hash_stats WHERE host = ? LIMIT 1",
        [host],
    )

    if has_host_hash_stats:
        sql = """
        SELECT f.host, f.drive, f.path_display, f.filename, f.ext, f.file_category,
               f.size_bytes, f.hash, f.mtime, f.last_seen_at
        FROM files f
        INNER JOIN host_hash_stats hdup
            ON hdup.host = f.host
           AND hdup.hash = f.hash
           AND hdup.copy_count_effective > 1
        WHERE f.host = ? AND f.drive = ?
          AND (f.path LIKE ? OR f.path = ?)
          AND f.size_bytes >= ?
        ORDER BY f.hash, f.path_display
        LIMIT ?
        """
        params = [
            host,
            drive,
            prefix + "/%",
            prefix,
            min_size,
            limit,
        ]
        rows = db.query(sql, params)
    else:
        # Fallback for hosts without aggregate stats: compute dupes on the fly.
        # Note: This checks for *intra-subtree* duplicates only if we use the old logic.
        # To align with semantics, we should check host-wide.
        # But doing a host-wide GROUP BY is too expensive here without aggregates.
        # So we keep the legacy behavior (intra-subtree) as a fallback, but users
        # on large hosts should have aggregates.
        sql = """
        WITH hard_linked_inodes AS (
            SELECT device, inode FROM files
            WHERE host = ? AND inode IS NOT NULL AND device IS NOT NULL
            GROUP BY device, inode HAVING COUNT(*) > 1
        ),
        dup_hashes AS (
            SELECT hash FROM files
            WHERE host = ? AND drive = ? AND hash IS NOT NULL
              AND (path LIKE ? OR path = ?)
              AND size_bytes >= ?
              AND NOT (inode IS NOT NULL AND device IS NOT NULL
                       AND (device, inode) IN (SELECT device, inode FROM hard_linked_inodes))
            GROUP BY hash HAVING COUNT(*) > 1
        )
        SELECT f.host, f.drive, f.path_display, f.filename, f.ext, f.file_category,
               f.size_bytes, f.hash, f.mtime, f.last_seen_at
        FROM files f
        WHERE f.host = ? AND f.drive = ? AND f.hash IN (SELECT hash FROM dup_hashes)
          AND (f.path LIKE ? OR f.path = ?)
        ORDER BY f.hash, f.path_display
        LIMIT ?
        """
        params = [
            host,  # hard_linked_inodes
            host,
            drive,
            prefix + "/%",
            prefix,
            min_size,  # dup_hashes
            host,
            drive,
            prefix + "/%",
            prefix,  # result rows
            limit,
        ]
        rows = db.query(sql, params)

    _log_perf(
        "/files/duplicates-in-subtree",
        req_start,
        host=host,
        prefix=prefix or "/",
        min_size=min_size,
        limit=limit,
        rows=len(rows),
        source="aggregate" if has_host_hash_stats else "legacy_scan",
    )
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
            other_hosts=None,
            in_subtree=True,
        )
        for r in rows
    ]


@app.get("/files/duplicates-by-subtree-hashes", response_model=list[FileEntry])
def duplicates_by_subtree_hashes(
    hosts: str = Query(..., description="Comma-separated selected hosts"),
    path_prefix: str = Query(...),
    drive: str = Query(""),
    min_size: int = Query(0, ge=0),
    scope: str = Query("subtree", pattern="^(subtree|context)$"),
    categories: str = Query("", description="Comma-separated categories filter"),
    limit: int = Query(2000, ge=1, le=10000),
):
    req_start = time.monotonic()
    prefix = path_prefix.lower().rstrip("/")
    lower_bound = prefix + "/"
    upper_bound = prefix + "0"

    host_list = [h.strip() for h in hosts.split(",") if h.strip()]
    if not host_list:
        raise HTTPException(status_code=400, detail="hosts is required")
    host_list = list(dict.fromkeys(host_list))
    category_list = [c.strip() for c in categories.split(",") if c.strip()]

    # Strict freshness gate: avoid expensive live fallback under lock.
    key_params = [f"host_hash_stats:{h}" for h in host_list]
    ph = ", ".join(["?" for _ in key_params])
    meta_rows = db.query(
        f"SELECT key, status FROM aggregate_meta WHERE key IN ({ph})",
        key_params,
    )
    meta_by_key = {str(r[0]): str(r[1]) for r in meta_rows}
    all_fresh = all(meta_by_key.get(k) == "fresh" for k in key_params)
    if not all_fresh:
        _log_perf(
            "/files/duplicates-by-subtree-hashes",
            req_start,
            hosts=len(host_list),
            scope=scope,
            result="pending",
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "pending",
                "detail": "Duplicate index is still building",
            },
        )

    host_ph = ", ".join(["?" for _ in host_list])
    seed_cat_clause = ""
    row_cat_clause = ""
    seed_drive_clause = ""
    row_drive_clause = ""
    if category_list:
        cat_ph = ", ".join(["?" for _ in category_list])
        seed_cat_clause = f" AND f.file_category IN ({cat_ph})"
        row_cat_clause = f" AND f.file_category IN ({cat_ph})"

    # Subtree seed should honor clicked drive when provided. Context result rows
    # intentionally do not force drive so users can see all copies for seeded hashes.
    if drive:
        seed_drive_clause = " AND f.drive = ?"
        if scope == "subtree":
            row_drive_clause = " AND f.drive = ?"

    scoped_filter = ""
    if scope == "subtree":
        scoped_filter = " AND ((f.path >= ? AND f.path < ?) OR f.path = ?)"

    sql = f"""
    WITH selected_dupe_hashes AS (
        SELECT hash, SUM(copy_count_effective) AS copies, MAX(size_bytes) AS size_bytes
        FROM host_hash_stats
        WHERE host IN ({host_ph}) AND hash IS NOT NULL
        GROUP BY hash
        HAVING SUM(copy_count_effective) > 1
           AND COALESCE(MAX(size_bytes), 0) >= ?
    ),
    seed_hashes AS (
        SELECT DISTINCT f.hash
        FROM files f
        INNER JOIN selected_dupe_hashes sdh ON sdh.hash = f.hash
        WHERE f.host IN ({host_ph})
          {seed_drive_clause}
          AND ((f.path >= ? AND f.path < ?) OR f.path = ?)
          {seed_cat_clause}
    )
    SELECT
        f.host,
        f.drive,
        f.path_display,
        f.filename,
        f.ext,
        f.file_category,
        f.size_bytes,
        f.hash,
        f.mtime,
        f.last_seen_at,
        (
            SELECT STRING_AGG(DISTINCT hhs.host, ',' ORDER BY hhs.host)
            FROM host_hash_stats hhs
            WHERE hhs.hash = f.hash
              AND hhs.host IN ({host_ph})
              AND hhs.host != f.host
        ) AS other_hosts,
        COALESCE(sdh.copies, 0) AS dup_count,
        CASE WHEN ((f.path >= ? AND f.path < ?) OR f.path = ?) THEN TRUE ELSE FALSE END AS in_subtree
    FROM files f
    INNER JOIN seed_hashes sh ON sh.hash = f.hash
    INNER JOIN selected_dupe_hashes sdh ON sdh.hash = f.hash
    WHERE f.host IN ({host_ph})
      {row_drive_clause}
      {row_cat_clause}
      {scoped_filter}
    ORDER BY LOWER(f.hash), LOWER(f.path)
    LIMIT ?
    """

    params: list = [
        *host_list,
        min_size,
        *host_list,
    ]
    if drive:
        params.append(drive)
    params.extend(
        [
            lower_bound,
            upper_bound,
            prefix,
            *category_list,
            *host_list,
            lower_bound,
            upper_bound,
            prefix,
            *host_list,
            *category_list,
        ]
    )
    if drive and scope == "subtree":
        params.append(drive)
    if scope == "subtree":
        params.extend([lower_bound, upper_bound, prefix])
    params.append(limit)

    rows = db.query(sql, params)
    _log_perf(
        "/files/duplicates-by-subtree-hashes",
        req_start,
        hosts=len(host_list),
        scope=scope,
        categories=len(category_list),
        min_size=min_size,
        rows=len(rows),
    )
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
            dup_count=r[11] or 0,
            in_subtree=bool(r[12]),
        )
        for r in rows
    ]


@app.get(
    "/files/duplicates-by-subtree-hashes/count",
    response_model=DuplicateHashCountResponse,
)
def duplicates_by_subtree_hashes_count(
    hosts: str = Query(..., description="Comma-separated selected hosts"),
    path_prefix: str = Query(...),
    drive: str = Query(""),
    min_size: int = Query(0, ge=0),
    categories: str = Query("", description="Comma-separated categories filter"),
):
    req_start = time.monotonic()
    prefix = path_prefix.lower().rstrip("/")
    lower_bound = prefix + "/"
    upper_bound = prefix + "0"

    host_list = [h.strip() for h in hosts.split(",") if h.strip()]
    if not host_list:
        raise HTTPException(status_code=400, detail="hosts is required")
    host_list = list(dict.fromkeys(host_list))
    category_list = [c.strip() for c in categories.split(",") if c.strip()]

    key_params = [f"host_hash_stats:{h}" for h in host_list]
    ph = ", ".join(["?" for _ in key_params])
    meta_rows = db.query(
        f"SELECT key, status FROM aggregate_meta WHERE key IN ({ph})",
        key_params,
    )
    meta_by_key = {str(r[0]): str(r[1]) for r in meta_rows}
    all_fresh = all(meta_by_key.get(k) == "fresh" for k in key_params)
    if not all_fresh:
        return JSONResponse(
            status_code=202,
            content={
                "status": "pending",
                "detail": "Duplicate index is still building",
            },
        )

    host_ph = ", ".join(["?" for _ in host_list])
    cat_clause = ""
    if category_list:
        cat_ph = ", ".join(["?" for _ in category_list])
        cat_clause = f" AND f.file_category IN ({cat_ph})"
    drive_clause = ""
    if drive:
        drive_clause = " AND f.drive = ?"

    sql = f"""
    WITH selected_dupe_hashes AS (
        SELECT hash
        FROM host_hash_stats
        WHERE host IN ({host_ph}) AND hash IS NOT NULL
        GROUP BY hash
        HAVING SUM(copy_count_effective) > 1
           AND COALESCE(MAX(size_bytes), 0) >= ?
    ),
    seed_hashes AS (
        SELECT DISTINCT f.hash
        FROM files f
        INNER JOIN selected_dupe_hashes sdh ON sdh.hash = f.hash
        WHERE f.host IN ({host_ph})
          {drive_clause}
          AND ((f.path >= ? AND f.path < ?) OR f.path = ?)
          {cat_clause}
    )
    SELECT COUNT(*) FROM seed_hashes
    """
    params: list = [*host_list, min_size, *host_list]
    if drive:
        params.append(drive)
    params.extend([lower_bound, upper_bound, prefix, *category_list])

    row = db.query_one(sql, params)
    count = int(row[0]) if row and row[0] is not None else 0
    _log_perf(
        "/files/duplicates-by-subtree-hashes/count",
        req_start,
        hosts=len(host_list),
        min_size=min_size,
        categories=len(category_list),
        count=count,
    )
    return DuplicateHashCountResponse(uniq_hash_count=count)


@app.get("/files/dup-ancestor-dirs")
def dup_ancestor_dirs(
    host: str = Query(...),
    drive: str = Query(""),
    path_prefix: str = Query(...),
    min_size: int = Query(0, ge=0),
    max_paths: int = Query(500, ge=1, le=5000),
):
    """Return directory paths that contain duplicate files under a subtree.
    Walks up from each leaf dir to path_prefix to fill in intermediate ancestors."""
    req_start = time.monotonic()
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
      AND f.drive = ?
      AND f.hash IS NOT NULL
      AND f.hash IN (SELECT hash FROM dupes)
      AND (f.path LIKE ? OR f.path = ?)
    ORDER BY dir_path
    """
    params = [host, host, min_size, host, drive, prefix + "/%", prefix]
    rows = db.query(sql, params)

    leaf_dirs = {r[0] for r in rows if r[0]}
    all_paths = set(leaf_dirs)
    for leaf in leaf_dirs:
        d = leaf
        while d != prefix and "/" in d:
            d = d.rsplit("/", 1)[0]
            if d and d != prefix and (d == prefix or d.startswith(prefix + "/")):
                all_paths.add(d)
                if len(all_paths) >= max_paths:
                    break
        if len(all_paths) >= max_paths:
            break
    _log_perf(
        "/files/dup-ancestor-dirs",
        req_start,
        host=host,
        prefix=prefix or "/",
        min_size=min_size,
        leaf_dirs=len(leaf_dirs),
        expanded_paths=len(all_paths),
        max_paths=max_paths,
    )
    return {"paths": sorted(all_paths)[:max_paths]}


@app.get("/files/ls", response_model=list[LsEntry])
def ls_files(
    path: str = "/",
    host: str = "",
    drive: str = Query(""),
    depth: int = Query(1, ge=1),
    min_size: int = Query(0, ge=0),
):
    req_start = time.monotonic()
    prefix = path.lower().rstrip("/")
    cache_key = (host, drive, prefix, depth, min_size)
    cached = _cache_get(_ls_cache, cache_key)
    if cached is not None:
        _log_perf(
            "/files/ls",
            req_start,
            host=host,
            path=prefix or "/",
            depth=depth,
            min_size=min_size,
            rows=len(cached),
            cache="hit",
        )
        return cached
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
          AND f.drive = ?
          AND (f.path LIKE ? OR f.path = ?)
          AND COALESCE(f.size_bytes, 0) >= ?
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

    # param order: hard_linked host, dupes host, dupes min_size, scoped host+drive+path+min_size, join host
    params = [host, host, min_size, host, drive, prefix + "/%", prefix, min_size, host]
    rows = db.query(sql, params)
    _log_perf(
        "/files/ls",
        req_start,
        host=host,
        path=prefix or "/",
        depth=depth,
        min_size=min_size,
        rows=len(rows),
        cache="miss",
    )
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
    _cache_set(_ls_cache, cache_key, result)
    return result


def _tree_children_rows(
    path: str,
    host: str,
    depth: int = 1,
    limit: int | None = None,
    offset: int = 0,
    drive: str = "",
) -> tuple[list[LsEntry], bool]:
    """Fast tree listing without subtree aggregate rollups."""
    prefix = path.lower().rstrip("/")
    lower_bound = prefix + "/"
    upper_bound = prefix + "0"
    split_idx = prefix.count("/") + depth + 1
    sql = f"""
    WITH scoped AS (
        SELECT
            f.path, f.path_display, f.filename, f.size_bytes,
            f.hash, f.mtime, f.last_seen_at, f.file_category,
            SPLIT_PART(f.path, '/', {split_idx}) AS segment,
            SPLIT_PART(f.path_display, '/', {split_idx}) AS segment_display,
            CASE WHEN SPLIT_PART(f.path, '/', {split_idx + 1}) = ''
                 THEN 'file' ELSE 'dir' END AS entry_type
        FROM files f
        WHERE f.host = ?
          AND f.drive = ?
          AND ((f.path >= ? AND f.path < ?) OR f.path = ?)
          AND SPLIT_PART(f.path, '/', {split_idx}) != ''
    ),
    dirs AS (
        SELECT
            s.segment,
            ANY_VALUE(s.segment_display) AS segment_display,
            COUNT(*) AS file_count,
            SUM(COALESCE(s.size_bytes, 0)) AS total_bytes
        FROM scoped s
        WHERE s.entry_type = 'dir'
        GROUP BY s.segment
    ),
    leaf_files AS (
        SELECT
            s.segment,
            s.segment_display,
            s.filename,
            s.size_bytes,
            s.hash,
            s.mtime,
            s.last_seen_at,
            s.file_category,
            s.path_display
        FROM scoped s
        WHERE s.entry_type = 'file'
    )
    SELECT * FROM (
        SELECT
            d.segment,
            'dir' AS entry_type,
            d.file_count,
            d.total_bytes,
            0 AS dup_count,
            0 AS dup_hash_count,
            NULL::TEXT AS filename,
            NULL::BIGINT AS leaf_size,
            NULL::TEXT AS leaf_hash,
            NULL::BIGINT AS leaf_mtime,
            NULL::TIMESTAMPTZ AS leaf_last_seen_at,
            NULL::TEXT AS leaf_file_category,
            NULL::TEXT AS leaf_path_display,
            d.segment_display,
            NULL::TEXT AS other_hosts,
            FALSE AS is_hard_linked
        FROM dirs d
        UNION ALL
        SELECT
            f.segment,
            'file' AS entry_type,
            1 AS file_count,
            f.size_bytes AS total_bytes,
            0 AS dup_count,
            0 AS dup_hash_count,
            f.filename,
            f.size_bytes AS leaf_size,
            f.hash AS leaf_hash,
            f.mtime AS leaf_mtime,
            f.last_seen_at AS leaf_last_seen_at,
            f.file_category AS leaf_file_category,
            f.path_display AS leaf_path_display,
            f.segment_display,
            NULL::TEXT AS other_hosts,
            FALSE AS is_hard_linked
        FROM leaf_files f
    ) t
    ORDER BY t.entry_type ASC, t.segment ASC
    """
    params: list = [host, drive, lower_bound, upper_bound, prefix]
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit + 1, max(0, offset)])

    rows = db.query(sql, params)
    has_more = False
    if limit is not None and len(rows) > limit:
        rows = rows[:limit]
        has_more = True

    return [
        LsEntry(
            segment=r[0],
            entry_type=r[1],
            file_count=r[2],
            total_bytes=r[3],
            dup_count=0,
            dup_hash_count=0,
            filename=r[6],
            size_bytes=r[7],
            hash=r[8],
            mtime=r[9],
            last_seen_at=r[10],
            file_category=r[11],
            path_display=r[12],
            segment_display=r[13],
            other_hosts=None,
            is_hard_linked=False,
        )
        for r in rows
    ], has_more


@app.get("/tree/children", response_model=TreeChildrenResponse)
def tree_children(
    path: str = "/",
    host: str = "",
    drive: str = Query(""),
    depth: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=2000),
    cursor: Optional[str] = None,
):
    req_start = time.monotonic()
    prefix = path.lower().rstrip("/")
    try:
        offset = int(cursor) if cursor else 0
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc
    if offset < 0:
        raise HTTPException(status_code=400, detail="Invalid cursor")

    cache_key = (host, drive, prefix, depth, limit, offset)
    cached = _cache_get(_tree_children_cache, cache_key)
    if cached is not None:
        _log_perf(
            "/tree/children",
            req_start,
            host=host,
            path=prefix or "/",
            depth=depth,
            limit=limit,
            offset=offset,
            rows=len(cached.items),
            cache="hit",
        )
        return cached

    items, has_more = _tree_children_rows(
        path=path,
        host=host,
        depth=depth,
        limit=limit,
        offset=offset,
        drive=drive,
    )
    response = TreeChildrenResponse(
        items=items,
        next_cursor=str(offset + limit) if has_more else None,
        has_more=has_more,
        aggregated_at=None,
        data_freshness="fresh",
    )
    _cache_set(_tree_children_cache, cache_key, response)
    _log_perf(
        "/tree/children",
        req_start,
        host=host,
        path=prefix or "/",
        depth=depth,
        limit=limit,
        offset=offset,
        rows=len(items),
        cache="miss",
    )
    return response


@app.get("/tree/dup-metrics", response_model=TreeDupMetricsResponse)
def tree_dup_metrics(
    path: str = "/",
    host: str = "",
    hosts: str = "",
    drive: str = Query(""),
    depth: int = Query(1, ge=1),
    min_size: int = Query(0, ge=0),
    segments: list[str] = Query([], description="Child segments to enrich"),
):
    req_start = time.monotonic()
    prefix = path.lower().rstrip("/")
    lower_bound = prefix + "/"
    upper_bound = prefix + "0"
    seg_list = [s.strip() for s in segments if s.strip()]
    host_list = [h.strip() for h in hosts.split(",") if h.strip()]
    host_list = list(dict.fromkeys(host_list))

    if host_list:
        hosts_key = ",".join(host_list)
        seg_cache = "\0".join(sorted(seg_list)) if seg_list else ""
        cache_key = ("hosts", hosts_key, drive, prefix, depth, min_size, seg_cache)
        cached = _cache_get(_tree_dup_metrics_cache, cache_key)
        if cached is not None:
            return cached

        key_params = [f"host_hash_stats:{h}" for h in host_list]
        ph = ", ".join(["?" for _ in key_params])
        meta_rows = db.query(
            f"SELECT key, status FROM aggregate_meta WHERE key IN ({ph})",
            key_params,
        )
        meta_by_key = {str(r[0]): str(r[1]) for r in meta_rows}
        all_fresh = all(meta_by_key.get(k) == "fresh" for k in key_params)
        if not all_fresh:
            response = TreeDupMetricsResponse(
                metrics={}, aggregated_at=None, data_freshness="stale"
            )
            _cache_set(_tree_dup_metrics_cache, cache_key, response)
            return response

        split_idx = prefix.count("/") + depth + 1
        host_ph = ", ".join(["?" for _ in host_list])
        seg_clause = ""
        seg_params: list = []
        if seg_list:
            placeholders = ", ".join(["?" for _ in seg_list])
            seg_clause = (
                f" AND SPLIT_PART(f.path, '/', {split_idx}) IN ({placeholders})"
            )
            seg_params = seg_list

        sql = f"""
        WITH scoped AS (
            SELECT
                SPLIT_PART(f.path, '/', {split_idx}) AS segment,
                f.host,
                f.hash,
                f.size_bytes
            FROM files f
            WHERE f.host IN ({host_ph})
              AND f.drive = ?
              AND ((f.path >= ? AND f.path < ?) OR f.path = ?)
              AND SPLIT_PART(f.path, '/', {split_idx}) != ''
              AND f.hash IS NOT NULL
              AND COALESCE(f.size_bytes, 0) >= ?
              {seg_clause}
        ),
        selected_dupe_hashes AS (
            SELECT hash
            FROM host_hash_stats
            WHERE host IN ({host_ph}) AND hash IS NOT NULL
            GROUP BY hash
            HAVING SUM(copy_count_effective) > 1
               AND COALESCE(MAX(size_bytes), 0) >= ?
        ),
        seg_totals AS (
            SELECT segment,
                   COUNT(*) AS file_count,
                   SUM(COALESCE(size_bytes, 0)) AS total_bytes
            FROM scoped
            GROUP BY segment
        ),
        seg_dups AS (
            SELECT s.segment,
                   COUNT(*) AS dup_count,
                   COUNT(DISTINCT s.hash) AS dup_hash_count,
                   STRING_AGG(DISTINCT s.host, ',' ORDER BY s.host) AS other_hosts
            FROM scoped s
            INNER JOIN selected_dupe_hashes d ON d.hash = s.hash
            GROUP BY s.segment
        )
        SELECT
            st.segment,
            COALESCE(sd.dup_count, 0) AS dup_count,
            COALESCE(sd.dup_hash_count, 0) AS dup_hash_count,
            sd.other_hosts,
            FALSE AS is_hard_linked,
            st.file_count,
            st.total_bytes
        FROM seg_totals st
        LEFT JOIN seg_dups sd ON sd.segment = st.segment
        """
        params: list = [
            *host_list,
            drive,
            lower_bound,
            upper_bound,
            prefix,
            min_size,
            *seg_params,
            *host_list,
            min_size,
        ]
        rows = db.query(sql, params)
        metrics = {
            r[0]: TreeDupMetric(
                dup_count=r[1] or 0,
                dup_hash_count=r[2] or 0,
                other_hosts=r[3],
                is_hard_linked=bool(r[4]),
                file_count=r[5],
                total_bytes=r[6],
            )
            for r in rows
        }
        response = TreeDupMetricsResponse(
            metrics=metrics, aggregated_at=None, data_freshness="fresh"
        )
        _cache_set(_tree_dup_metrics_cache, cache_key, response)
        _log_perf(
            "/tree/dup-metrics",
            req_start,
            host="*",
            hosts=len(host_list),
            path=prefix or "/",
            depth=depth,
            min_size=min_size,
            segments="yes" if segments else "no",
            rows=len(metrics),
            cache="miss",
            source="agg_hosts",
        )
        return response

    seg_cache = "\0".join(sorted(seg_list)) if seg_list else ""
    cache_key = (host, drive, prefix, depth, min_size, seg_cache)
    cached = _cache_get(_tree_dup_metrics_cache, cache_key)
    if cached is not None:
        _log_perf(
            "/tree/dup-metrics",
            req_start,
            host=host,
            path=prefix or "/",
            depth=depth,
            min_size=min_size,
            rows=len(cached.metrics),
            cache="hit",
        )
        return cached

    split_idx = prefix.count("/") + depth + 1
    agg_row = db.query_one(
        "SELECT MAX(updated_at) FROM host_hash_stats WHERE host = ?",
        [host],
    )
    agg_ts = agg_row[0] if agg_row else None
    has_agg = agg_ts is not None
    aggregated_at = agg_ts if has_agg else None
    host_meta = db.query_one(
        "SELECT status FROM aggregate_meta WHERE key = ?",
        [f"host_hash_stats:{host}"],
    )
    host_freshness = host_meta[0] if host_meta else None

    if not has_agg:
        hs_row = db.query_one(
            "SELECT total_files FROM host_stats WHERE host = ?",
            [host],
        )
        host_files = int(hs_row[0]) if hs_row and hs_row[0] is not None else 0
        if host_files >= _DUP_METRICS_LIVE_MAX_FILES:
            if _MAINTENANCE_ENABLED:
                # Avoid multi-minute live fallback scans on large hosts; rely on
                # eventual aggregate refresh instead.
                db.set_aggregate_meta(
                    f"host_hash_stats:{host}",
                    "stale",
                    "Live dup-metrics fallback skipped on large host; waiting for aggregate refresh",
                )
                db.enqueue_maintenance_job(
                    "refresh_host_hash_stats",
                    host=host,
                    priority=20,
                )
                response = TreeDupMetricsResponse(
                    metrics={},
                    aggregated_at=None,
                    data_freshness="stale",
                )
                # Do not cache this empty skip response; we want quick retries
                # once maintenance has refreshed host aggregates.
                _log_perf(
                    "/tree/dup-metrics",
                    req_start,
                    host=host,
                    path=prefix or "/",
                    depth=depth,
                    min_size=min_size,
                    segments="yes" if segments else "no",
                    rows=0,
                    cache="miss",
                    source="skip_live_large_host",
                )
                return response

            # Maintenance is disabled; run a bounded lightweight fallback that
            # scopes host-wide duplicate counting to hashes visible under this
            # path/segment set so "Only dups" can still function.
            seg_clause = ""
            scoped_seg_clause = ""
            seg_params: list = []
            if seg_list:
                placeholders = ", ".join(["?" for _ in seg_list])
                seg_clause = f" AND sh.segment IN ({placeholders})"
                scoped_seg_clause = (
                    f" AND SPLIT_PART(f.path, '/', {split_idx}) IN ({placeholders})"
                )
                seg_params = seg_list

            # Aggregate-first lite fallback: GROUP BY (segment, hash) to reduce
            # join size.  Cross-host pre-aggregated per segment to avoid fan-out.
            sql = f"""
            WITH hard_linked_inodes AS (
                SELECT device, inode FROM files
                WHERE host = ? AND inode IS NOT NULL AND device IS NOT NULL
                GROUP BY device, inode HAVING COUNT(*) > 1
            ),
            seg_hashes AS (
                SELECT
                    SPLIT_PART(f.path, '/', {split_idx}) AS segment,
                    f.hash,
                    COUNT(*) AS file_count,
                    SUM(COALESCE(f.size_bytes, 0)) AS total_bytes,
                    BOOL_OR(
                        SPLIT_PART(f.path, '/', {split_idx + 1}) = ''
                        AND f.inode IS NOT NULL AND f.device IS NOT NULL
                        AND (f.device, f.inode) IN (SELECT device, inode FROM hard_linked_inodes)
                    ) AS has_hard_link
                FROM files f
                WHERE f.host = ?
                  AND f.drive = ?
                  AND ((f.path >= ? AND f.path < ?) OR f.path = ?)
                  AND f.hash IS NOT NULL
                  AND COALESCE(f.size_bytes, 0) >= ?
                  {scoped_seg_clause}
                GROUP BY SPLIT_PART(f.path, '/', {split_idx}), f.hash
            ),
            dupes AS (
                SELECT hash FROM files
                WHERE host = ? AND hash IN (SELECT hash FROM seg_hashes)
                  AND NOT (inode IS NOT NULL AND device IS NOT NULL
                           AND (device, inode) IN (SELECT device, inode FROM hard_linked_inodes))
                GROUP BY hash HAVING COUNT(*) > 1
            ),
            cross_hosts AS (
                SELECT sh.segment, STRING_AGG(DISTINCT f2.host ORDER BY f2.host) AS other_hosts
                FROM seg_hashes sh
                INNER JOIN files f2 ON f2.hash = sh.hash AND f2.host != ?
                GROUP BY sh.segment
            )
            SELECT
                sh.segment,
                SUM(CASE WHEN sh.hash IN (SELECT hash FROM dupes)
                         THEN sh.file_count ELSE 0 END) AS dup_count,
                COUNT(DISTINCT CASE WHEN sh.hash IN (SELECT hash FROM dupes)
                                    THEN sh.hash END) AS dup_hash_count,
                ch.other_hosts,
                BOOL_OR(sh.has_hard_link) AS is_hard_linked,
                SUM(sh.file_count) AS file_count,
                SUM(sh.total_bytes) AS total_bytes
            FROM seg_hashes sh
            LEFT JOIN cross_hosts ch ON ch.segment = sh.segment
            WHERE sh.segment IS NOT NULL AND sh.segment != ''
              {seg_clause}
            GROUP BY sh.segment, ch.other_hosts
            """
            params = [
                host,
                host,
                drive,
                lower_bound,
                upper_bound,
                prefix,
                min_size,
                *seg_params,
                host,
                host,
                *seg_params,
            ]
            rows = db.query(sql, params)
            metrics = {
                r[0]: TreeDupMetric(
                    dup_count=r[1] or 0,
                    dup_hash_count=r[2] or 0,
                    other_hosts=r[3],
                    is_hard_linked=bool(r[4]),
                    file_count=r[5],
                    total_bytes=r[6],
                )
                for r in rows
            }
            response = TreeDupMetricsResponse(
                metrics=metrics,
                aggregated_at=None,
                data_freshness="stale",
            )
            _cache_set(_tree_dup_metrics_cache, cache_key, response)
            _log_perf(
                "/tree/dup-metrics",
                req_start,
                host=host,
                path=prefix or "/",
                depth=depth,
                min_size=min_size,
                segments="yes" if segments else "no",
                rows=len(metrics),
                cache="miss",
                source="lite_live_large_host",
            )
            return response

    if has_agg:
        seg_clause = ""
        scoped_seg_clause = ""
        seg_params: list = []
        if seg_list:
            placeholders = ", ".join(["?" for _ in seg_list])
            seg_clause = f" AND sh.segment IN ({placeholders})"
            scoped_seg_clause = (
                f" AND SPLIT_PART(f.path, '/', {split_idx}) IN ({placeholders})"
            )
            seg_params = seg_list
        # Aggregate-first approach: GROUP BY (segment, hash) first to reduce
        # row count from 852k+ down to ~unique hashes per segment, THEN join
        # to host_hash_stats.  Cross-host info is pre-aggregated per segment.
        sql = f"""
        WITH seg_hashes AS (
            SELECT
                SPLIT_PART(f.path, '/', {split_idx}) AS segment,
                f.hash,
                COUNT(*) AS file_count,
                SUM(COALESCE(f.size_bytes, 0)) AS total_bytes,
                BOOL_OR(
                    SPLIT_PART(f.path, '/', {split_idx + 1}) = ''
                    AND f.inode IS NOT NULL AND f.device IS NOT NULL
                    AND (f.device, f.inode) IN (
                        SELECT device, inode FROM host_hard_linked_inodes WHERE host = ?
                    )
                ) AS has_hard_link
            FROM files f
            WHERE f.host = ?
              AND f.drive = ?
              AND ((f.path >= ? AND f.path < ?) OR f.path = ?)
              AND f.hash IS NOT NULL
              AND COALESCE(f.size_bytes, 0) >= ?
              {scoped_seg_clause}
            GROUP BY SPLIT_PART(f.path, '/', {split_idx}), f.hash
        ),
        cross_matches AS (
            SELECT sh.segment, sh.hash, oh.host
            FROM seg_hashes sh
            INNER JOIN host_hash_stats oh ON oh.hash = sh.hash AND oh.host != ?
        ),
        cross_hosts AS (
            SELECT segment, STRING_AGG(DISTINCT host ORDER BY host) AS other_hosts
            FROM cross_matches
            GROUP BY segment
        ),
        cross_dups AS (
            SELECT DISTINCT segment, hash FROM cross_matches
        )
        SELECT
            sh.segment,
            SUM(CASE WHEN (hhs.copy_count_effective > 1 OR cd.hash IS NOT NULL)
                      AND COALESCE(hhs.size_bytes, 0) >= ?
                     THEN sh.file_count ELSE 0 END) AS dup_count,
            COUNT(DISTINCT CASE WHEN (hhs.copy_count_effective > 1 OR cd.hash IS NOT NULL)
                                 AND COALESCE(hhs.size_bytes, 0) >= ?
                                THEN sh.hash END) AS dup_hash_count,
            ch.other_hosts,
            BOOL_OR(sh.has_hard_link) AS is_hard_linked,
            SUM(sh.file_count) AS file_count,
            SUM(sh.total_bytes) AS total_bytes
        FROM seg_hashes sh
        LEFT JOIN host_hash_stats hhs ON hhs.host = ? AND hhs.hash = sh.hash
        LEFT JOIN cross_hosts ch ON ch.segment = sh.segment
        LEFT JOIN cross_dups cd ON cd.segment = sh.segment AND cd.hash = sh.hash
        WHERE sh.segment IS NOT NULL AND sh.segment != ''
          {seg_clause}
        GROUP BY sh.segment, ch.other_hosts
        """
        params = [
            host,
            host,
            drive,
            lower_bound,
            upper_bound,
            prefix,
            min_size,
            *seg_params,
            host,
            min_size,
            min_size,
            host,
            *seg_params,
        ]
        source = "agg"
    else:
        seg_clause = ""
        scoped_seg_clause = ""
        seg_params = []
        if seg_list:
            placeholders = ", ".join(["?" for _ in seg_list])
            seg_clause = f" AND sh.segment IN ({placeholders})"
            scoped_seg_clause = (
                f" AND SPLIT_PART(f.path, '/', {split_idx}) IN ({placeholders})"
            )
            seg_params = seg_list
        # Aggregate-first: GROUP BY (segment, hash) to reduce join size.
        # Cross-host info pre-aggregated per segment.
        sql = f"""
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
        ),
        seg_hashes AS (
            SELECT
                SPLIT_PART(f.path, '/', {split_idx}) AS segment,
                f.hash,
                COUNT(*) AS file_count,
                SUM(COALESCE(f.size_bytes, 0)) AS total_bytes,
                MAX(COALESCE(f.size_bytes, 0)) AS file_size,
                BOOL_OR(
                    SPLIT_PART(f.path, '/', {split_idx + 1}) = ''
                    AND f.inode IS NOT NULL AND f.device IS NOT NULL
                    AND (f.device, f.inode) IN (SELECT device, inode FROM hard_linked_inodes)
                ) AS has_hard_link
            FROM files f
            WHERE f.host = ?
              AND f.drive = ?
              AND ((f.path >= ? AND f.path < ?) OR f.path = ?)
              AND f.hash IS NOT NULL
              AND COALESCE(f.size_bytes, 0) >= ?
              {scoped_seg_clause}
            GROUP BY SPLIT_PART(f.path, '/', {split_idx}), f.hash
        ),
        cross_matches AS (
            SELECT sh.segment, sh.hash, f2.host
            FROM seg_hashes sh
            INNER JOIN files f2 ON f2.hash = sh.hash AND f2.host != ?
        ),
        cross_hosts AS (
            SELECT segment, STRING_AGG(DISTINCT host ORDER BY host) AS other_hosts
            FROM cross_matches
            GROUP BY segment
        ),
        cross_dups AS (
            SELECT DISTINCT segment, hash FROM cross_matches
        )
        SELECT
            sh.segment,
            SUM(CASE WHEN (sh.hash IN (SELECT hash FROM dupes) OR cd.hash IS NOT NULL)
                      AND sh.file_size >= ?
                     THEN sh.file_count ELSE 0 END) AS dup_count,
            COUNT(DISTINCT CASE WHEN (sh.hash IN (SELECT hash FROM dupes) OR cd.hash IS NOT NULL)
                                 AND sh.file_size >= ?
                                THEN sh.hash END) AS dup_hash_count,
            ch.other_hosts,
            BOOL_OR(sh.has_hard_link) AS is_hard_linked,
            SUM(sh.file_count) AS file_count,
            SUM(sh.total_bytes) AS total_bytes
        FROM seg_hashes sh
        LEFT JOIN cross_hosts ch ON ch.segment = sh.segment
        LEFT JOIN cross_dups cd ON cd.segment = sh.segment AND cd.hash = sh.hash
        WHERE sh.segment IS NOT NULL AND sh.segment != ''
          {seg_clause}
        GROUP BY sh.segment, ch.other_hosts
        """
        params = [
            host,
            host,
            min_size,
            host,
            drive,
            lower_bound,
            upper_bound,
            prefix,
            min_size,
            *seg_params,
            host,
            min_size,
            min_size,
            *seg_params,
        ]
        source = "live"

    rows = db.query(sql, params)
    metrics = {
        r[0]: TreeDupMetric(
            dup_count=r[1] or 0,
            dup_hash_count=r[2] or 0,
            other_hosts=r[3],
            is_hard_linked=bool(r[4]),
            file_count=r[5],
            total_bytes=r[6],
        )
        for r in rows
    }
    response = TreeDupMetricsResponse(
        metrics=metrics,
        aggregated_at=aggregated_at,
        data_freshness=host_freshness or ("fresh" if has_agg else "stale"),
    )
    _cache_set(_tree_dup_metrics_cache, cache_key, response)
    _log_perf(
        "/tree/dup-metrics",
        req_start,
        host=host,
        path=prefix or "/",
        depth=depth,
        min_size=min_size,
        segments="yes" if segments else "no",
        rows=len(metrics),
        cache="miss",
        source=source,
    )
    return response


@app.get("/files/page", response_model=FilePageResponse)
def list_files_page(
    hosts: str = Query(..., description="Comma-separated selected hosts"),
    categories: Optional[str] = None,
    path_contains: Optional[str] = None,
    drive: str = Query("", description="Optional drive letter filter (e.g. 'C')"),
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    has_duplicates: Optional[bool] = None,
    hash: Optional[str] = None,
    iname: Optional[str] = None,
    sort_by: str = Query("name"),
    sort_dir: str = Query("asc"),
    limit: int = Query(200, ge=1, le=2000),
    cursor: Optional[str] = None,
):
    req_start = time.monotonic()

    try:
        offset = int(cursor) if cursor else 0
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc
    if offset < 0:
        raise HTTPException(status_code=400, detail="Invalid cursor")

    host_list = [h.strip() for h in hosts.split(",") if h.strip()]
    if not host_list:
        raise HTTPException(status_code=400, detail="hosts is required")
    host_list = list(dict.fromkeys(host_list))
    category_list = (
        [c.strip() for c in categories.split(",") if c.strip()] if categories else []
    )

    sort_map = {
        "name": "LOWER(LTRIM(f.filename))",
        "size": "COALESCE(f.size_bytes, 0)",
        "date": "COALESCE(f.mtime, 0)",
        "seen": "COALESCE(f.last_seen_at, TIMESTAMPTZ '1970-01-01 00:00:00+00')",
        "type": "LOWER(f.file_category)",
        "hash": "LOWER(COALESCE(f.hash, ''))",
        "path": "LOWER(f.path)",
    }
    if sort_by not in sort_map:
        raise HTTPException(status_code=400, detail="Invalid sort_by")
    if sort_dir not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="Invalid sort_dir")

    # For duplicate-sensitive views, require fresh per-host aggregates.
    if has_duplicates is True:
        key_params = [f"host_hash_stats:{h}" for h in host_list]
        ph = ", ".join(["?" for _ in key_params])
        meta_rows = db.query(
            f"SELECT key, status FROM aggregate_meta WHERE key IN ({ph})",
            key_params,
        )
        meta_by_key = {str(r[0]): str(r[1]) for r in meta_rows}
        all_fresh = all(meta_by_key.get(k) == "fresh" for k in key_params)
        if not all_fresh:
            _log_perf(
                "/files/page",
                req_start,
                hosts=len(host_list),
                has_duplicates=str(has_duplicates).lower(),
                result="pending",
            )
            return JSONResponse(
                status_code=202,
                content={
                    "status": "pending",
                    "detail": "Duplicate index is still building",
                },
            )

    host_ph = ", ".join(["?" for _ in host_list])
    conditions = [f"f.host IN ({host_ph})"]
    where_params: list = [*host_list]

    if category_list:
        cat_ph = ", ".join(["?" for _ in category_list])
        conditions.append(f"f.file_category IN ({cat_ph})")
        where_params.extend(category_list)

    if path_contains:
        conditions.append("LOWER(f.path) LIKE '%' || ? || '%'")
        where_params.append(path_contains.lower())

    drive_upper = drive.strip().upper() if drive else ""
    if drive_upper:
        conditions.append("f.drive = ?")
        where_params.append(drive_upper)

    if min_size is not None:
        conditions.append("f.size_bytes >= ?")
        where_params.append(min_size)

    if max_size is not None:
        conditions.append("f.size_bytes <= ?")
        where_params.append(max_size)

    if hash:
        h = hash.lower()
        if len(h) == 64:
            conditions.append("f.hash = ?")
        else:
            conditions.append("f.hash LIKE '%' || ? || '%'")
        where_params.append(h)

    if iname:
        sql_pat = (
            iname.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            .replace("*", "%")
            .replace("?", "_")
        )
        conditions.append("LOWER(f.filename) LIKE LOWER(?) ESCAPE '\\'")
        where_params.append(sql_pat)

    if has_duplicates is True:
        conditions.append("COALESCE(shs.copies, 0) > 1")
    elif has_duplicates is False:
        conditions.append("(f.hash IS NULL OR COALESCE(shs.copies, 0) <= 1)")

    order_expr = sort_map[sort_by]
    where_sql = " AND ".join(conditions)
    sql = f"""
    WITH selected_hash_stats AS (
        SELECT hash, SUM(copy_count_effective) AS copies
        FROM host_hash_stats
        WHERE host IN ({host_ph}) AND hash IS NOT NULL
        GROUP BY hash
    )
    SELECT
        f.host,
        f.drive,
        f.path_display,
        f.filename,
        f.ext,
        f.file_category,
        f.size_bytes,
        f.hash,
        f.mtime,
        f.last_seen_at,
        (
            SELECT STRING_AGG(DISTINCT hhs.host, ',' ORDER BY hhs.host)
            FROM host_hash_stats hhs
            WHERE hhs.hash = f.hash
              AND hhs.host != f.host
              AND hhs.host IN ({host_ph})
              AND f.hash IS NOT NULL
        ) AS other_hosts,
        CASE WHEN COALESCE(shs.copies, 0) > 1 THEN shs.copies ELSE 0 END AS dup_count
    FROM files f
    LEFT JOIN selected_hash_stats shs ON shs.hash = f.hash
    WHERE {where_sql}
    ORDER BY {order_expr} {sort_dir.upper()}, LOWER(f.path) ASC
    LIMIT ? OFFSET ?
    """

    params = [*host_list, *host_list, *where_params, limit + 1, offset]
    rows = db.query(sql, params)
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    result = FilePageResponse(
        items=[
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
                dup_count=r[11] or 0,
            )
            for r in rows
        ],
        next_cursor=str(offset + limit) if has_more else None,
        has_more=has_more,
    )

    _log_perf(
        "/files/page",
        req_start,
        hosts=len(host_list),
        categories=len(category_list),
        has_duplicates="*" if has_duplicates is None else str(has_duplicates).lower(),
        sort=f"{sort_by}:{sort_dir}",
        limit=limit,
        offset=offset,
        rows=len(result.items),
        has_more=str(has_more).lower(),
    )
    return result


def _filter_own_host(hosts_csv: str | None, own_host: str) -> str | None:
    """Remove the file's own host from a comma-separated other_hosts string."""
    if not hosts_csv:
        return None
    others = [h for h in hosts_csv.split(",") if h != own_host]
    return ",".join(others) if others else None


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
    lite: bool = Query(
        False, description="Skip cross-host enrichment for faster search"
    ),
    limit: int = Query(100, le=1_000_000),
):
    req_start = time.monotonic()
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

    dup_clause = ""
    dup_params: list = []
    if has_duplicates is not None:
        # Prefer aggregate-backed duplicate filtering when available to avoid
        # expensive full-table GROUP BY scans in interactive find/search paths.
        if host:
            host_agg = db.query_one(
                "SELECT 1 FROM host_hash_stats WHERE host = ? LIMIT 1",
                [host],
            )
            if host_agg is not None:
                if has_duplicates is True:
                    dup_clause = (
                        " AND f.hash IN ("
                        "SELECT hash FROM host_hash_stats "
                        "WHERE host = ? AND copy_count_effective > 1"
                        ")"
                    )
                    dup_params = [host]
                else:
                    dup_clause = (
                        " AND (f.hash IS NULL OR f.hash NOT IN ("
                        "SELECT hash FROM host_hash_stats "
                        "WHERE host = ? AND copy_count_effective > 1"
                        "))"
                    )
                    dup_params = [host]
        if not dup_clause:
            global_agg = db.query_one("SELECT 1 FROM hash_stats LIMIT 1")
            if global_agg is not None:
                if has_duplicates is True:
                    dup_clause = (
                        " AND f.hash IN ("
                        "SELECT hash FROM hash_stats WHERE copy_count > 1"
                        ")"
                    )
                else:
                    dup_clause = (
                        " AND (f.hash IS NULL OR f.hash NOT IN ("
                        "SELECT hash FROM hash_stats WHERE copy_count > 1"
                        "))"
                    )
        if not dup_clause:
            # No aggregate tables available (startup window). Return 202
            # instead of running an expensive inline GROUP BY that would
            # hold the DB lock for seconds.
            _log_perf(
                "/files",
                req_start,
                host=host or "*",
                has_duplicates=str(has_duplicates).lower(),
                result="pending",
            )
            return JSONResponse(
                status_code=202,
                content={
                    "status": "pending",
                    "detail": "Duplicate index is still building",
                },
            )

    where = " AND ".join(conditions)

    use_host_dup_join = False
    if has_duplicates is True and host:
        host_dup_agg = db.query_one(
            "SELECT 1 FROM host_hash_stats WHERE host = ? LIMIT 1",
            [host],
        )
        use_host_dup_join = host_dup_agg is not None
        if use_host_dup_join:
            # duplicate filtering is provided by INNER JOIN host_hash_stats
            dup_clause = ""
            dup_params = []

    if lite:
        if use_host_dup_join:
            sql = f"""
            SELECT
                f.host, f.drive, f.path_display, f.filename, f.ext,
                f.file_category, f.size_bytes, f.hash, f.mtime, f.last_seen_at,
                NULL AS other_hosts
            FROM files f
            INNER JOIN host_hash_stats hdup
                ON hdup.host = ?
               AND hdup.hash = f.hash
               AND hdup.copy_count_effective > 1
            WHERE {where}
            ORDER BY f.path
            LIMIT ?
            """
        else:
            sql = f"""
            SELECT
                f.host, f.drive, f.path_display, f.filename, f.ext,
                f.file_category, f.size_bytes, f.hash, f.mtime, f.last_seen_at,
                NULL AS other_hosts
            FROM files f
            WHERE {where} {dup_clause}
            ORDER BY f.path
            LIMIT ?
            """
    else:
        # Two-phase enrichment: fetch base rows without GROUP BY (Phase A),
        # then batch-enrich other_hosts for distinct hashes (Phase B).
        # This avoids the expensive 11-column GROUP BY over all matching rows.
        has_host_hash_stats = db.query_one("SELECT 1 FROM host_hash_stats LIMIT 1")
        if has_host_hash_stats is not None:
            if use_host_dup_join:
                sql = f"""
                SELECT
                    f.host, f.drive, f.path_display, f.filename, f.ext,
                    f.file_category, f.size_bytes, f.hash, f.mtime, f.last_seen_at
                FROM files f
                INNER JOIN host_hash_stats hdup
                    ON hdup.host = ?
                   AND hdup.hash = f.hash
                   AND hdup.copy_count_effective > 1
                WHERE {where}
                ORDER BY f.path
                LIMIT ?
                """
            else:
                sql = f"""
                SELECT
                    f.host, f.drive, f.path_display, f.filename, f.ext,
                    f.file_category, f.size_bytes, f.hash, f.mtime, f.last_seen_at
                FROM files f
                WHERE {where} {dup_clause}
                ORDER BY f.path
                LIMIT ?
                """
        else:
            # Startup fallback: host_hash_stats empty, use files self-join.
            # Still two-phase: fetch base rows first, enrich after.
            sql = f"""
            SELECT
                f.host, f.drive, f.path_display, f.filename, f.ext,
                f.file_category, f.size_bytes, f.hash, f.mtime, f.last_seen_at
            FROM files f
            WHERE {where} {dup_clause}
            ORDER BY f.path
            LIMIT ?
            """
    if use_host_dup_join:
        params.append(host)
    params.extend(dup_params)
    params.append(limit)

    rows = db.query(sql, params)

    if lite:
        # Lite mode: no enrichment needed, other_hosts is already NULL.
        _log_perf(
            "/files",
            req_start,
            host=host or "*",
            path_prefix=path_prefix or "*",
            hash="yes" if hash else "no",
            iname="yes" if iname else "no",
            lite="yes",
            limit=limit,
            rows=len(rows),
        )
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

    # Phase B: batch-enrich other_hosts for the result set's distinct hashes.
    # Collect non-NULL hashes from Phase A rows and look them up in bulk.
    result_hashes = list({r[7] for r in rows if r[7] is not None})
    other_hosts_map: dict[str, str] = {}

    if result_hashes:
        has_host_hash_stats = db.query_one("SELECT 1 FROM host_hash_stats LIMIT 1")
        if has_host_hash_stats is not None:
            # Fast path: use pre-aggregated host_hash_stats table.
            hash_ph = ", ".join(["?" for _ in result_hashes])
            enrich_rows = db.query(
                f"""
                SELECT hash, STRING_AGG(DISTINCT host, ',' ORDER BY host) AS hosts
                FROM host_hash_stats
                WHERE hash IN ({hash_ph})
                GROUP BY hash
                """,
                result_hashes,
            )
            for er in enrich_rows:
                other_hosts_map[er[0]] = er[1]
        else:
            # Startup fallback: use files table directly.
            hash_ph = ", ".join(["?" for _ in result_hashes])
            enrich_rows = db.query(
                f"""
                SELECT hash, STRING_AGG(DISTINCT host, ',' ORDER BY host) AS hosts
                FROM files
                WHERE hash IN ({hash_ph}) AND hash IS NOT NULL
                GROUP BY hash
                """,
                result_hashes,
            )
            for er in enrich_rows:
                other_hosts_map[er[0]] = er[1]

    _log_perf(
        "/files",
        req_start,
        host=host or "*",
        path_prefix=path_prefix or "*",
        hash="yes" if hash else "no",
        iname="yes" if iname else "no",
        lite="no",
        limit=limit,
        rows=len(rows),
        enriched_hashes=len(result_hashes),
    )
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
            # Filter out the file's own host from the other_hosts string.
            other_hosts=_filter_own_host(other_hosts_map.get(r[7]), r[0]),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------


@app.get("/init")
def init_data(request: Request, path: str = "/", min_size: int = Query(0, ge=0)):
    """Combined startup endpoint: returns hosts + root ls in one round trip."""
    req_start = time.monotonic()
    hosts = list_hosts()
    root_ls = {
        h.host: _tree_children_rows(
            path=path, host=h.host, depth=1, limit=None, offset=0
        )[0]
        for h in hosts
    }
    client_host = _detect_client_host(request)
    root_entries = sum(len(v) for v in root_ls.values())
    _log_perf(
        "/init",
        req_start,
        hosts=len(hosts),
        root_path=path,
        min_size=min_size,
        root_entries=root_entries,
    )
    return {"hosts": hosts, "root_ls": root_ls, "client_host": client_host}


@app.get("/client-host")
def client_host(request: Request):
    return {"client_host": _detect_client_host(request)}


@app.get("/hosts", response_model=list[HostEntry])
def list_hosts():
    cache_key = ("hosts",)
    cached = _cache_get(_hosts_cache, cache_key)
    if cached is not None:
        return cached

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
    # Collect distinct non-empty drives per host from files table
    drive_rows = db.query(
        "SELECT host, drive FROM files WHERE drive != '' GROUP BY host, drive ORDER BY host, drive"
    )
    drives_by_host: dict[str, list[str]] = {}
    for dr in drive_rows:
        drives_by_host.setdefault(dr[0], []).append(dr[1])
    # Check which hosts have active scans
    scanning_rows = db.query(
        "SELECT DISTINCT host FROM scan_runs WHERE status = 'running'"
    )
    scanning_hosts = {r[0] for r in scanning_rows}
    result = [
        HostEntry(
            host=r[0],
            last_scan_at=r[1],
            last_scan_root=r[2],
            total_files=r[3],
            total_bytes=r[4],
            total_hashed=r[5],
            drives=drives_by_host.get(r[0], []),
            is_scanning=r[0] in scanning_hosts,
        )
        for r in rows
    ]
    _cache_set(_hosts_cache, cache_key, result)
    return result


def _root_covers(ancestor: str, candidate: str) -> bool:
    if ancestor == candidate:
        return True
    if ancestor == "/":
        return candidate.startswith("/")
    return candidate.startswith(ancestor + "/")


@app.get("/hosts/roots", response_model=list[HostRootEntry])
def list_host_roots(host: Optional[str] = Query(None)):
    params: list = []
    where_parts = ["status = 'complete'"]
    if host:
        where_parts.append("host = ?")
        params.append(host)
    where = "WHERE " + " AND ".join(where_parts)

    rows = db.query(
        f"""
        WITH complete_runs AS (
            SELECT id, host, drive, root_path, root_path_display, started_at
            FROM scan_runs
            {where}
        ),
        latest_per_root AS (
            SELECT
                host,
                drive,
                root_path,
                COALESCE(root_path_display, root_path) AS root_display,
                started_at,
                ROW_NUMBER() OVER (
                    PARTITION BY host, drive, root_path
                    ORDER BY started_at DESC, id DESC
                ) AS rn
            FROM complete_runs
        )
        SELECT host, drive, root_path, root_display, started_at
        FROM latest_per_root
        WHERE rn = 1
        ORDER BY host, drive, LENGTH(root_path), root_path
        """,
        params,
    )

    grouped: dict[tuple[str, str], list[tuple[str, str, datetime]]] = {}
    for r in rows:
        grouped.setdefault((str(r[0]), str(r[1] or "")), []).append(
            (str(r[2]), str(r[3]), r[4])
        )

    out: list[HostRootEntry] = []
    for (h, drive), roots in sorted(grouped.items()):
        selected: list[tuple[str, str, datetime]] = []
        for root_path, root_display, started_at in roots:
            if any(_root_covers(s[0], root_path) for s in selected):
                continue
            selected.append((root_path, root_display, started_at))
        for root_path, root_display, started_at in selected:
            out.append(
                HostRootEntry(
                    host=h,
                    drive=drive,
                    root_path=root_display,
                    latest_complete_at=started_at,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

# Stats cache now uses the unified _cache_get/_cache_set helpers via
# _stats_overview_cache (defined alongside other query caches above).
# TTL is controlled by SIFT_QUERY_CACHE_TTL.


def _report_all_hosts_in_datastore() -> list[str]:
    rows = db.query(
        """
        WITH all_hosts AS (
            SELECT host FROM host_stats
            UNION
            SELECT DISTINCT host FROM scan_runs
        )
        SELECT host FROM all_hosts ORDER BY host
        """
    )
    return [str(r[0]) for r in rows]


def _report_require_fresh_host_hash_stats(hosts: list[str]) -> JSONResponse | None:
    if not hosts:
        return None
    key_params = [f"host_hash_stats:{h}" for h in hosts]
    ph = ", ".join(["?" for _ in key_params])
    meta_rows = db.query(
        f"SELECT key, status FROM aggregate_meta WHERE key IN ({ph})",
        key_params,
    )
    meta_by_key = {str(r[0]): str(r[1]) for r in meta_rows}
    all_fresh = all(meta_by_key.get(k) == "fresh" for k in key_params)
    if all_fresh:
        return None
    return JSONResponse(
        status_code=202,
        content={"status": "pending", "detail": "Duplicate index is still building"},
    )


_SIZE_100_KB = 100 * 1024
_SIZE_1_MB = 1024 * 1024
_SIZE_10_MB = 10 * 1024 * 1024
_SIZE_100_MB = 100 * 1024 * 1024
_SIZE_1_GB = 1024 * 1024 * 1024
_SIZE_10_GB = 10 * 1024 * 1024 * 1024
_SIZE_100_GB = 100 * 1024 * 1024 * 1024
_SIZE_1_TB = 1024 * 1024 * 1024 * 1024


@app.get("/aggregate-status")
def aggregate_status():
    """Return freshness status of all aggregates."""
    rows = db.query(
        "SELECT key, status, updated_at, note FROM aggregate_meta ORDER BY key"
    )
    return [
        {
            "key": r[0],
            "status": r[1],
            "updated_at": r[2],
            "note": r[3],
        }
        for r in rows
    ]


@app.get("/debug/query")
def debug_query(sql: str = Query(...)):
    """Debug endpoint — run a read-only SQL query."""
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
        raise HTTPException(status_code=400, detail="Only SELECT/WITH queries allowed")
    try:
        rows = db.query(sql)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"rows": rows}


@app.get("/stats/overview", response_model=StatsOverview)
def stats_overview(
    min_size: int = Query(0, ge=0),
    categories: str = Query(
        "", description="Comma-separated file categories to filter dup stats"
    ),
    hosts: str = Query("", description="Comma-separated host names to filter stats"),
):
    req_start = time.monotonic()
    cache_key = ("stats_overview", min_size, categories, hosts)
    cached = _cache_get(_stats_overview_cache, cache_key)
    if cached is not None:
        _log_perf(
            "/stats/overview",
            req_start,
            cache="hit",
            min_size=min_size,
            categories=categories or "*",
            hosts=hosts or "*",
        )
        return cached

    host_list = [h.strip() for h in hosts.split(",") if h.strip()] if hosts else []
    category_list = (
        [c.strip() for c in categories.split(",") if c.strip()] if categories else []
    )

    # Base totals from host_stats (cheap and already maintained).
    if host_list:
        placeholders = ", ".join(["?" for _ in host_list])
        totals_row = db.query_one(
            f"""
            SELECT
                COALESCE(SUM(total_files), 0),
                COUNT(CASE WHEN total_files > 0 THEN 1 END),
                COALESCE(SUM(total_bytes), 0)
            FROM host_stats
            WHERE host IN ({placeholders})
            """,
            host_list,
        )
    else:
        totals_row = db.query_one(
            """
            SELECT
                COALESCE(SUM(total_files), 0),
                COUNT(CASE WHEN total_files > 0 THEN 1 END),
                COALESCE(SUM(total_bytes), 0)
            FROM host_stats
            """
        )

    total_files = int(totals_row[0]) if totals_row and totals_row[0] is not None else 0
    total_hosts = int(totals_row[1]) if totals_row and totals_row[1] is not None else 0
    total_bytes = int(totals_row[2]) if totals_row and totals_row[2] is not None else 0

    def _combine_freshness(statuses: list[str]) -> str:
        if any(s == "building" for s in statuses):
            return "building"
        if any(s == "stale" for s in statuses):
            return "stale"
        return "fresh"

    use_agg = len(category_list) == 0
    freshness = "fresh"
    aggregated_at = None
    source = "live"

    if use_agg:
        if host_list:
            key_params = [f"host_hash_stats:{h}" for h in host_list]
            ph = ", ".join(["?" for _ in key_params])
            meta_rows = db.query(
                f"SELECT key, status, updated_at FROM aggregate_meta WHERE key IN ({ph})",
                key_params,
            )
            if len(meta_rows) == len(key_params):
                freshness = _combine_freshness([str(r[1]) for r in meta_rows])
                aggregated_at = max(r[2] for r in meta_rows if r[2] is not None)
            else:
                # Backward-compatible fallback: use host_hash_stats when metadata
                # has not been initialized yet.
                placeholders = ", ".join(["?" for _ in host_list])
                host_ts = db.query_one(
                    f"""
                    SELECT COUNT(DISTINCT host), MAX(updated_at)
                    FROM host_hash_stats
                    WHERE host IN ({placeholders})
                    """,
                    host_list,
                )
                covered = int(host_ts[0]) if host_ts and host_ts[0] is not None else 0
                if covered == len(host_list):
                    freshness = "stale"
                    aggregated_at = host_ts[1] if host_ts else None
                else:
                    use_agg = False
        else:
            meta_row = db.query_one(
                "SELECT status, updated_at FROM aggregate_meta WHERE key = 'hash_stats'"
            )
            if meta_row is not None:
                freshness = str(meta_row[0])
                aggregated_at = meta_row[1]
            else:
                # Backward-compatible fallback: use hash_stats when metadata has
                # not been initialized yet.
                hs_row = db.query_one(
                    "SELECT COUNT(*), MAX(updated_at) FROM hash_stats"
                )
                hs_count = int(hs_row[0]) if hs_row and hs_row[0] is not None else 0
                if hs_count > 0:
                    freshness = "stale"
                    aggregated_at = hs_row[1] if hs_row else None
                else:
                    use_agg = False

    if use_agg and host_list:
        placeholders = ", ".join(["?" for _ in host_list])
        agg_row = db.query_one(
            f"""
            WITH selected AS (
                SELECT
                    hash,
                    SUM(copy_count_effective) AS copies,
                    MAX(size_bytes) AS size_bytes
                FROM host_hash_stats
                WHERE host IN ({placeholders})
                GROUP BY hash
            )
            SELECT
                COUNT(*) AS unique_hashes,
                COUNT(CASE WHEN copies > 1 AND COALESCE(size_bytes, 0) >= ? THEN 1 END) AS dup_sets,
                COALESCE(SUM(CASE
                    WHEN copies > 1 AND COALESCE(size_bytes, 0) >= ?
                    THEN (copies - 1) * COALESCE(size_bytes, 0)
                    ELSE 0
                END), 0) AS wasted
            FROM selected
            """,
            [*host_list, min_size, min_size],
        )
        unique_hashes = int(agg_row[0]) if agg_row and agg_row[0] is not None else 0
        duplicate_sets = int(agg_row[1]) if agg_row and agg_row[1] is not None else 0
        wasted_bytes = int(agg_row[2]) if agg_row and agg_row[2] is not None else 0
        source = "agg_host"
    elif use_agg and not host_list:
        unique_row = db.query_one("SELECT COUNT(*) FROM hash_stats")
        dup_row = db.query_one(
            """
            SELECT
                COUNT(CASE WHEN copy_count > 1 AND COALESCE(size_bytes, 0) >= ? THEN 1 END) AS dup_sets,
                COALESCE(SUM(CASE
                    WHEN copy_count > 1 AND COALESCE(size_bytes, 0) >= ? THEN COALESCE(wasted_bytes, 0)
                    ELSE 0
                END), 0) AS wasted
            FROM hash_stats
            """,
            [min_size, min_size],
        )
        unique_hashes = (
            int(unique_row[0]) if unique_row and unique_row[0] is not None else 0
        )
        duplicate_sets = int(dup_row[0]) if dup_row and dup_row[0] is not None else 0
        wasted_bytes = int(dup_row[1]) if dup_row and dup_row[1] is not None else 0
        source = "agg_global"
    else:
        host_where = ""
        if host_list:
            placeholders = ", ".join(["?" for _ in host_list])
            host_where = f"AND host IN ({placeholders})"

        row = db.query_one(
            f"""
            SELECT COUNT(DISTINCT hash) FILTER (WHERE hash IS NOT NULL)
            FROM files
            WHERE 1=1 {host_where}
            """,
            host_list,
        )
        unique_hashes = int(row[0]) if row and row[0] is not None else 0

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

        duplicate_sets = int(dup_row[0]) if dup_row and dup_row[0] is not None else 0
        wasted_bytes = int(dup_row[1]) if dup_row and dup_row[1] is not None else 0
        aggregated_at = None
        freshness = "fresh"
        source = "live"

    result = StatsOverview(
        total_files=total_files,
        total_hosts=total_hosts,
        unique_hashes=unique_hashes,
        duplicate_sets=duplicate_sets,
        wasted_bytes=wasted_bytes,
        total_bytes=total_bytes,
        aggregated_at=aggregated_at,
        data_freshness=freshness,
    )
    _cache_set(_stats_overview_cache, cache_key, result)
    _log_perf(
        "/stats/overview",
        req_start,
        cache="miss",
        min_size=min_size,
        categories=categories or "*",
        hosts=hosts or "*",
        total_files=total_files,
        dup_sets=duplicate_sets,
        source=source,
        freshness=freshness,
    )
    return result


@app.get("/stats/report/inventory", response_model=ReportInventoryResponse)
def stats_report_inventory():
    hosts = _report_all_hosts_in_datastore()
    with db.operation_context("report inventory: host totals"):
        totals_row = db.query_one(
            """
            SELECT
                COALESCE(SUM(total_files), 0),
                COALESCE(SUM(total_bytes), 0)
            FROM host_stats
            """
        )
    total_files = int(totals_row[0]) if totals_row and totals_row[0] is not None else 0
    total_bytes = int(totals_row[1]) if totals_row and totals_row[1] is not None else 0

    with db.operation_context("report inventory: zero-byte count"):
        zero_row = db.query_one(
            "SELECT COUNT(*) FROM files WHERE COALESCE(size_bytes, 0) = 0"
        )
    zero_files = int(zero_row[0]) if zero_row and zero_row[0] is not None else 0

    return ReportInventoryResponse(
        hosts_in_datastore=len(hosts),
        total_file_rows=total_files,
        total_bytes=total_bytes,
        zero_byte_files=zero_files,
    )


@app.get("/stats/report/duplicates", response_model=ReportDuplicatesResponse)
def stats_report_duplicates(
    min_size: int = Query(0, ge=0),
    top_limit: int = Query(10, ge=1, le=50),
):
    dup_hosts_rows = db.query(
        "SELECT host FROM host_stats WHERE total_files > 0 ORDER BY host"
    )
    dup_hosts = [str(r[0]) for r in dup_hosts_rows]
    pending = _report_require_fresh_host_hash_stats(dup_hosts)
    if pending is not None:
        return pending
    if not dup_hosts:
        empty_global = ReportGlobalDuplicateSummary(
            uniq_dup_hashes=0,
            extra_copies=0,
            extra_bytes=0,
            gross_duplicate_bytes=0,
        )
        empty_cross = ReportCrossHostSummary(
            qualifying_uniq_dup_hashes=0,
            qualifying_file_copies=0,
            extra_copies=0,
            extra_bytes=0,
            gross_duplicate_bytes=0,
        )
        return ReportDuplicatesResponse(
            global_summary=empty_global,
            host_only_rows=[],
            cross_host_summary=empty_cross,
            top_opportunities=[],
        )

    host_ph = ", ".join(["?" for _ in dup_hosts])
    scope_sql = f"""
    WITH per_hash AS (
        SELECT
            hash,
            SUM(copy_count_effective) AS total_copies,
            SUM(CASE WHEN copy_count_effective > 0 THEN 1 ELSE 0 END) AS host_count_present,
            MAX(size_bytes) AS size_bytes,
            MAX(CASE WHEN copy_count_effective > 1 THEN 1 ELSE 0 END) AS has_intra
        FROM host_hash_stats
        WHERE host IN ({host_ph})
          AND hash IS NOT NULL
        GROUP BY hash
    ),
    scoped AS (
        SELECT
            hash,
            total_copies,
            host_count_present,
            COALESCE(size_bytes, 0) AS size_bytes,
            CASE
                WHEN has_intra = 1 OR (total_copies >= 3 AND host_count_present >= 2)
                THEN 1 ELSE 0
            END AS in_scope,
            CASE
                WHEN total_copies >= 3 AND host_count_present >= 2
                THEN 1 ELSE 0
            END AS in_cross_scope
        FROM per_hash
        WHERE COALESCE(size_bytes, 0) >= ?
    )
    """

    with db.operation_context("report duplicates: global and cross summaries"):
        global_row = db.query_one(
            scope_sql
            + """
            SELECT
                COALESCE(COUNT(CASE WHEN in_scope = 1 THEN 1 END), 0),
                COALESCE(SUM(CASE WHEN in_scope = 1 THEN total_copies - 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN in_scope = 1 THEN (total_copies - 1) * size_bytes ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN in_scope = 1 THEN total_copies * size_bytes ELSE 0 END), 0)
            FROM scoped
            """,
            [*dup_hosts, min_size],
        )
        cross_row = db.query_one(
            scope_sql
            + """
            SELECT
                COALESCE(COUNT(CASE WHEN in_cross_scope = 1 THEN 1 END), 0),
                COALESCE(SUM(CASE WHEN in_cross_scope = 1 THEN total_copies ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN in_cross_scope = 1 THEN total_copies - 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN in_cross_scope = 1 THEN (total_copies - 1) * size_bytes ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN in_cross_scope = 1 THEN total_copies * size_bytes ELSE 0 END), 0)
            FROM scoped
            """,
            [*dup_hosts, min_size],
        )

    with db.operation_context("report duplicates: host-only table"):
        host_rows = db.query(
            f"""
        SELECT
            hs.host,
            COALESCE(COUNT(CASE
                WHEN h.copy_count_effective > 1 AND COALESCE(h.size_bytes, 0) >= ?
                THEN 1
            END), 0) AS uniq_dup_hashes,
            COALESCE(SUM(CASE
                WHEN h.copy_count_effective > 1 AND COALESCE(h.size_bytes, 0) >= ?
                THEN h.copy_count_effective - 1
                ELSE 0
            END), 0) AS extra_copies,
            COALESCE(SUM(CASE
                WHEN h.copy_count_effective > 1 AND COALESCE(h.size_bytes, 0) >= ?
                THEN (h.copy_count_effective - 1) * COALESCE(h.size_bytes, 0)
                ELSE 0
            END), 0) AS extra_bytes,
            COALESCE(hs.total_bytes, 0) AS host_total_bytes
        FROM host_stats hs
        LEFT JOIN host_hash_stats h
               ON h.host = hs.host
        WHERE hs.host IN ({host_ph})
        GROUP BY hs.host, hs.total_bytes
        ORDER BY hs.host
            """,
            [min_size, min_size, min_size, *dup_hosts],
        )

    with db.operation_context("report duplicates: top opportunities"):
        top_rows = db.query(
            scope_sql
            + f"""
        , top_hashes AS (
            SELECT
                hash,
                total_copies,
                host_count_present,
                size_bytes,
                (total_copies - 1) * size_bytes AS extra_bytes
            FROM scoped
            WHERE in_scope = 1
            ORDER BY extra_bytes DESC, total_copies DESC, hash ASC
            LIMIT ?
        ),
        sample AS (
            SELECT
                f.hash,
                MIN(COALESCE(f.file_category, 'other')) AS file_category,
                MIN(COALESCE(f.filename, '')) AS sample_filename
            FROM files f
            INNER JOIN top_hashes t ON t.hash = f.hash
            WHERE f.host IN ({host_ph})
            GROUP BY f.hash
        )
        SELECT
            t.extra_bytes,
            t.total_copies,
            t.host_count_present,
            COALESCE(s.file_category, 'other') AS file_category,
            COALESCE(s.sample_filename, '') AS sample_filename
        FROM top_hashes t
        LEFT JOIN sample s ON s.hash = t.hash
        ORDER BY t.extra_bytes DESC, t.total_copies DESC
            """,
            [*dup_hosts, min_size, top_limit, *dup_hosts],
        )

    global_summary = ReportGlobalDuplicateSummary(
        uniq_dup_hashes=int(global_row[0]) if global_row else 0,
        extra_copies=int(global_row[1]) if global_row else 0,
        extra_bytes=int(global_row[2]) if global_row else 0,
        gross_duplicate_bytes=int(global_row[3]) if global_row else 0,
    )
    cross_summary = ReportCrossHostSummary(
        qualifying_uniq_dup_hashes=int(cross_row[0]) if cross_row else 0,
        qualifying_file_copies=int(cross_row[1]) if cross_row else 0,
        extra_copies=int(cross_row[2]) if cross_row else 0,
        extra_bytes=int(cross_row[3]) if cross_row else 0,
        gross_duplicate_bytes=int(cross_row[4]) if cross_row else 0,
    )
    host_only_rows = [
        ReportHostOnlyRow(
            host=str(r[0]),
            uniq_dup_hashes=int(r[1] or 0),
            extra_copies=int(r[2] or 0),
            extra_bytes=int(r[3] or 0),
            host_total_bytes=int(r[4] or 0),
        )
        for r in host_rows
    ]
    top_opportunities = [
        ReportTopOpportunity(
            rank=i,
            extra_bytes=int(r[0] or 0),
            copies=int(r[1] or 0),
            hosts=int(r[2] or 0),
            file_category=str(r[3] or "other"),
            sample_filename=str(r[4] or ""),
        )
        for i, r in enumerate(top_rows, start=1)
    ]
    return ReportDuplicatesResponse(
        global_summary=global_summary,
        host_only_rows=host_only_rows,
        cross_host_summary=cross_summary,
        top_opportunities=top_opportunities,
    )


@app.get("/stats/report/tombstones", response_model=ReportTombstonesResponse)
def stats_report_tombstones():
    hosts_in_datastore = len(_report_all_hosts_in_datastore())
    with db.operation_context("report tombstones: eligibility summary"):
        rows = db.query(
            """
        WITH covered AS (
            SELECT
                f.host,
                f.drive,
                f.path,
                MAX(sr.started_at) AS latest_complete_started_at
            FROM files f
            JOIN scan_runs sr
              ON sr.host = f.host
             AND sr.drive = f.drive
             AND sr.status = 'complete'
             AND (f.path = sr.root_path OR f.path LIKE sr.root_path || '/%')
            GROUP BY f.host, f.drive, f.path
        ),
        eligible AS (
            SELECT
                f.host,
                COALESCE(f.size_bytes, 0) AS size_bytes
            FROM files f
            JOIN covered c
              ON c.host = f.host
             AND c.drive = f.drive
             AND c.path = f.path
            WHERE f.last_seen_at < c.latest_complete_started_at
        )
        SELECT
            host,
            COUNT(*) AS file_rows,
            COALESCE(SUM(size_bytes), 0) AS total_bytes
        FROM eligible
        GROUP BY host
        ORDER BY host
            """
        )
    host_stats = [(str(r[0]), int(r[1] or 0), int(r[2] or 0)) for r in rows]
    eligible_rows = sum(r[1] for r in host_stats)
    eligible_bytes = sum(r[2] for r in host_stats)
    hosts_with_pressure = [r[0] for r in host_stats if r[1] > 0]
    hosts_with_pressure_count = len(hosts_with_pressure)

    top_host = None
    top_host_rows = 0
    if host_stats:
        top = sorted(host_stats, key=lambda x: (-x[1], x[0]))[0]
        top_host = top[0]
        top_host_rows = top[1]

    return ReportTombstonesResponse(
        eligible_tombstone_rows=eligible_rows,
        eligible_tombstone_bytes=eligible_bytes,
        hosts_with_pressure=hosts_with_pressure,
        hosts_with_pressure_count=hosts_with_pressure_count,
        hosts_in_datastore=hosts_in_datastore,
        top_host=top_host,
        top_host_rows=top_host_rows,
    )


@app.get(
    "/stats/report/size-distribution", response_model=ReportSizeDistributionResponse
)
def stats_report_size_distribution(fast: bool = Query(False)):
    if fast:
        cache_key = ("report_size_distribution",)
        cached = _cache_get(
            _report_size_distribution_cache,
            cache_key,
            ttl_sec=_REPORT_SIZE_DISTRIBUTION_CACHE_TTL,
        )
        if cached is not None:
            return cached

    with db.operation_context("report size distribution: magnitude buckets"):
        row = db.query_one(
            """
            SELECT
                COUNT(*) AS total_files,
                SUM(CASE WHEN COALESCE(size_bytes, 0) < ? THEN 1 ELSE 0 END) AS b10kb,
                SUM(CASE WHEN COALESCE(size_bytes, 0) >= ? AND COALESCE(size_bytes, 0) < ? THEN 1 ELSE 0 END) AS b100kb,
                SUM(CASE WHEN COALESCE(size_bytes, 0) >= ? AND COALESCE(size_bytes, 0) < ? THEN 1 ELSE 0 END) AS b1mb,
                SUM(CASE WHEN COALESCE(size_bytes, 0) >= ? AND COALESCE(size_bytes, 0) < ? THEN 1 ELSE 0 END) AS b10mb,
                SUM(CASE WHEN COALESCE(size_bytes, 0) >= ? AND COALESCE(size_bytes, 0) < ? THEN 1 ELSE 0 END) AS b100mb,
                SUM(CASE WHEN COALESCE(size_bytes, 0) >= ? AND COALESCE(size_bytes, 0) < ? THEN 1 ELSE 0 END) AS b1gb,
                SUM(CASE WHEN COALESCE(size_bytes, 0) >= ? AND COALESCE(size_bytes, 0) < ? THEN 1 ELSE 0 END) AS b10gb,
                SUM(CASE WHEN COALESCE(size_bytes, 0) >= ? AND COALESCE(size_bytes, 0) < ? THEN 1 ELSE 0 END) AS b100gb,
                SUM(CASE WHEN COALESCE(size_bytes, 0) >= ? THEN 1 ELSE 0 END) AS b1tb
            FROM files
            """,
            [
                _SIZE_100_KB,
                _SIZE_100_KB,
                _SIZE_1_MB,
                _SIZE_1_MB,
                _SIZE_10_MB,
                _SIZE_10_MB,
                _SIZE_100_MB,
                _SIZE_100_MB,
                _SIZE_1_GB,
                _SIZE_1_GB,
                _SIZE_10_GB,
                _SIZE_10_GB,
                _SIZE_100_GB,
                _SIZE_100_GB,
                _SIZE_1_TB,
                _SIZE_1_TB,
            ],
        )

    total_files = int(row[0] or 0) if row else 0
    counts = [int(v or 0) for v in (row[1:] if row else [])]
    labels = [
        "10 KB",
        "100 KB",
        "1 MB",
        "10 MB",
        "100 MB",
        "1 GB",
        "10 GB",
        "100 GB",
        "1+ TB",
    ]
    bucket_rows = []
    for label, count in zip(labels, counts):
        pct = (float(count) / float(total_files) * 100.0) if total_files > 0 else 0.0
        bucket_rows.append(
            ReportSizeBucketRow(bucket=label, files=count, pct_of_files=pct)
        )

    response = ReportSizeDistributionResponse(
        total_files=total_files,
        buckets=bucket_rows,
    )
    if fast:
        _cache_set(
            _report_size_distribution_cache,
            ("report_size_distribution",),
            response,
        )
    return response


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

    if not sets_rows:
        return []

    # Batch-fetch all locations in one query instead of N+1.
    all_hashes = [sr[0] for sr in sets_rows]
    hash_ph = ", ".join(["?" for _ in all_hashes])
    loc_rows = db.query(
        f"""
        SELECT hash, host, drive, path_display
        FROM files
        WHERE hash IN ({hash_ph})
        ORDER BY hash, host, path_display
        """,
        all_hashes,
    )
    locs_by_hash: dict[str, list[DuplicateLocation]] = {}
    for lr in loc_rows:
        locs_by_hash.setdefault(lr[0], []).append(
            DuplicateLocation(host=lr[1], drive=lr[2], path_display=lr[3])
        )

    return [
        DuplicateSet(
            hash=sr[0],
            filename=sr[1],
            size_bytes=sr[2],
            copy_count=sr[3],
            wasted_bytes=sr[4],
            locations=locs_by_hash.get(sr[0], []),
        )
        for sr in sets_rows
    ]


# ---------------------------------------------------------------------------
# Directory autocomplete
# ---------------------------------------------------------------------------


@app.get("/directories")
def list_directories(
    hosts: str = Query(..., description="Comma-separated selected hosts"),
    q: str = "",
    drive: str = Query("", description="Optional drive letter filter (e.g. 'C')"),
    limit: int = Query(20, le=100),
):
    req_start = time.monotonic()
    q = q.strip()
    host_list = [h.strip() for h in hosts.split(",") if h.strip()]
    drive_upper = drive.strip().upper()
    if len(q) < 2 or not host_list:
        _log_perf("/directories", req_start, query_len=len(q), limit=limit, rows=0)
        return []
    hosts_key = ",".join(sorted(host_list))
    cache_key = (q.lower(), hosts_key, drive_upper, limit)
    cached = _cache_get(_directories_cache, cache_key)
    if cached is not None:
        _log_perf(
            "/directories",
            req_start,
            query_len=len(q),
            limit=limit,
            rows=len(cached),
            cache="hit",
        )
        return cached

    # Build dynamic host/drive filter
    host_ph = ", ".join(["?"] * len(host_list))
    host_filter = f"AND host IN ({host_ph})"
    host_params = list(host_list)
    drive_filter = ""
    drive_params: list = []
    if drive_upper:
        drive_filter = "AND drive = ?"
        drive_params = [drive_upper]

    rows = db.query(
        f"""
        SELECT host, drive, dir_path, dir_display
        FROM directory_index
        WHERE dir_path != ''
          AND lower(dir_path) LIKE '%' || lower(?) || '%'
          {host_filter}
          {drive_filter}
        ORDER BY
          CASE
            WHEN lower(regexp_extract(dir_path, '[^/]+$')) = lower(?) THEN 0
            WHEN lower(regexp_extract(dir_path, '[^/]+$')) LIKE lower(?) || '%' THEN 1
            WHEN lower(dir_path) LIKE '%/' || lower(?) || '/%' OR lower(dir_path) LIKE '%/' || lower(?) THEN 2
            ELSE 3
          END,
          LENGTH(dir_path),
          dir_path
        LIMIT ?
        """,
        [q] + host_params + drive_params + [q, q, q, q, limit],
    )
    if not rows:
        rows = db.query(
            f"""
            SELECT host, drive, dir_path, dir_display FROM (
                SELECT
                    host,
                    drive,
                    regexp_replace(path, '/[^/]+$', '') AS dir_path,
                    ANY_VALUE(regexp_replace(path_display, '/[^/]+$', '')) AS dir_display
                FROM files
                WHERE host IN ({host_ph})
                  {drive_filter}
                GROUP BY host, drive, regexp_replace(path, '/[^/]+$', '')
                HAVING regexp_replace(path, '/[^/]+$', '') != ''
            ) sub
            WHERE lower(dir_path) LIKE '%' || lower(?) || '%'
            ORDER BY
              CASE
                WHEN lower(regexp_extract(dir_path, '[^/]+$')) = lower(?) THEN 0
                WHEN lower(regexp_extract(dir_path, '[^/]+$')) LIKE lower(?) || '%' THEN 1
                WHEN lower(dir_path) LIKE '%/' || lower(?) || '/%' OR lower(dir_path) LIKE '%/' || lower(?) THEN 2
                ELSE 3
              END,
              LENGTH(dir_path),
              dir_path
            LIMIT ?
            """,
            host_params + drive_params + [q, q, q, q, q, limit],
        )

    # Key by (host, drive, dir_path) to preserve per-host/drive identity
    results: dict[tuple, str] = {}
    for r in rows:
        key = (r[0], r[1], r[2])  # host, drive, dir_path
        results[key] = r[3] or r[2]

    # Also include any ancestor paths that contain the query but have no files
    # directly in them (e.g. BetterZip.app only has files in Contents/).
    # Without this the UI expands the ancestor as a non-highlighted node.
    q_lower = q.lower()
    extra: dict[tuple, str] = {}
    for (host, drv, dir_path) in list(results):
        parts = dir_path.split("/")
        for i in range(2, len(parts)):
            ancestor = "/".join(parts[:i])
            anc_key = (host, drv, ancestor)
            if (
                q_lower in ancestor.lower()
                and anc_key not in results
                and anc_key not in extra
            ):
                extra[anc_key] = ancestor

    results.update(extra)
    output = [
        {"host": k[0], "drive": k[1], "dir_path": k[2], "dir_display": v}
        for k, v in sorted(results.items(), key=lambda kv: (kv[0][2], kv[0][0], kv[0][1]))
    ][:limit]
    _log_perf(
        "/directories",
        req_start,
        query_len=len(q),
        limit=limit,
        rows=len(output),
        cache="miss",
    )
    _cache_set(_directories_cache, cache_key, output)
    return output


# ---------------------------------------------------------------------------
# Static frontend — mounted LAST so API routes take precedence
# ---------------------------------------------------------------------------

_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if not os.path.isdir(_frontend_dist):
    # Fallback for non-editable installs: check current working directory
    _frontend_dist = os.path.join(os.getcwd(), "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
