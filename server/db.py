"""DuckDB connection, schema DDL, thread-safe query helpers."""

import logging
import os
import threading
import time
import contextvars
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger("sift.db")


_DB_LOCK_WAIT_TIMEOUT_SEC = float(os.environ.get("SIFT_DB_LOCK_WAIT_TIMEOUT_SEC", "0"))
_DB_QUERY_TIMEOUT_SEC = float(os.environ.get("SIFT_DB_QUERY_TIMEOUT_SEC", "0"))

_lock = threading.RLock()
_conn: duckdb.DuckDBPyConnection | None = None


class DBTimeoutError(RuntimeError):
    def __init__(
        self,
        timeout_type: str,
        timeout_sec: float,
        endpoint: str,
        operation: str,
        detail: str,
        sql: str,
    ) -> None:
        super().__init__(detail)
        self.timeout_type = timeout_type
        self.timeout_sec = timeout_sec
        self.endpoint = endpoint
        self.operation = operation
        self.detail = detail
        self.sql = sql

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "timeout_enforced",
            "type": self.timeout_type,
            "endpoint": self.endpoint,
            "operation": self.operation,
            "timeout_sec": self.timeout_sec,
            "sql": self.sql,
            "detail": self.detail,
        }


_request_context: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar(
    "sift_db_request_context",
    default={"endpoint": "unknown", "operation": "unspecified"},
)


def push_request_context(endpoint: str) -> contextvars.Token:
    return _request_context.set({"endpoint": endpoint, "operation": endpoint})


def pop_request_context(token: contextvars.Token) -> None:
    _request_context.reset(token)


@contextmanager
def operation_context(operation: str):
    current = _request_context.get()
    token = _request_context.set(
        {"endpoint": current.get("endpoint", "unknown"), "operation": operation}
    )
    try:
        yield
    finally:
        _request_context.reset(token)


def _context_snapshot() -> tuple[str, str]:
    ctx = _request_context.get()
    return (ctx.get("endpoint", "unknown"), ctx.get("operation", "unspecified"))


def _sql_snippet(sql: str) -> str:
    text = " ".join(sql.split())
    return text[:180]


def _slow_log_context(sql: str, params: list[Any] | None, max_chars: int = 250) -> str:
    sql_one_line = " ".join(sql.split())
    parts = [sql_one_line]
    if params:
        preview = repr(params[:6])
        parts.append(f"params_count={len(params)}")
        if "IN (VALUES" in sql_one_line.upper() and len(params) >= 2:
            # Common shape in trim/seen updates: first params are scalar values,
            # remainder are tupled path keys, often (drive, path) pairs.
            tuple_est = max((len(params) - 2) // 2, 0)
            if tuple_est:
                parts.append(f"value_tuples~{tuple_est}")
        parts.append(f"params_preview={preview}")
    out = " | ".join(parts)
    if len(out) > max_chars:
        return out[: max_chars - 3] + "..."
    return out


@contextmanager
def _acquire_lock(sql: str):
    start = time.monotonic()
    if _DB_LOCK_WAIT_TIMEOUT_SEC <= 0:
        _lock.acquire()
        acquired = True
    else:
        acquired = _lock.acquire(timeout=_DB_LOCK_WAIT_TIMEOUT_SEC)
    if not acquired:
        endpoint, operation = _context_snapshot()
        elapsed = time.monotonic() - start
        raise DBTimeoutError(
            timeout_type="lock_wait",
            timeout_sec=_DB_LOCK_WAIT_TIMEOUT_SEC,
            endpoint=endpoint,
            operation=operation,
            detail=f"Timed out waiting for DB lock after {elapsed:.1f}s",
            sql=_sql_snippet(sql),
        )
    try:
        yield
    finally:
        _lock.release()


def _run_with_query_timeout(conn: duckdb.DuckDBPyConnection, sql: str, runner):
    if _DB_QUERY_TIMEOUT_SEC <= 0:
        return runner()

    timed_out = threading.Event()

    def _interrupt() -> None:
        timed_out.set()
        try:
            conn.interrupt()
        except Exception:
            pass

    timer = threading.Timer(_DB_QUERY_TIMEOUT_SEC, _interrupt)
    timer.daemon = True
    timer.start()
    try:
        return runner()
    except Exception as exc:
        if timed_out.is_set():
            endpoint, operation = _context_snapshot()
            raise DBTimeoutError(
                timeout_type="query_runtime",
                timeout_sec=_DB_QUERY_TIMEOUT_SEC,
                endpoint=endpoint,
                operation=operation,
                detail="DuckDB query interrupted after timeout",
                sql=_sql_snippet(sql),
            ) from exc
        raise
    finally:
        timer.cancel()


SCHEMA_SQL = """
CREATE SEQUENCE IF NOT EXISTS scan_run_id_seq START 1;
CREATE SEQUENCE IF NOT EXISTS maintenance_job_id_seq START 1;

CREATE TABLE IF NOT EXISTS files (
    host            TEXT        NOT NULL,
    drive           TEXT        NOT NULL DEFAULT '',
    path            TEXT        NOT NULL,
    path_display    TEXT        NOT NULL,
    filename        TEXT        NOT NULL,
    ext             TEXT        NOT NULL DEFAULT '',
    file_category   TEXT        NOT NULL DEFAULT 'other',
    size_bytes      BIGINT,
    hash            TEXT,
    mtime           BIGINT,
    last_checked    TIMESTAMPTZ NOT NULL,
    source_os       TEXT        NOT NULL,
    skipped_reason  TEXT,
    last_seen_at    TIMESTAMPTZ NOT NULL,
    inode           BIGINT,
    device          BIGINT,
    PRIMARY KEY (host, drive, path)
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id                BIGINT      PRIMARY KEY DEFAULT nextval('scan_run_id_seq'),
    host              TEXT        NOT NULL,
    drive             TEXT        NOT NULL DEFAULT '',
    root_path         TEXT        NOT NULL,
    root_path_display TEXT,
    started_at        TIMESTAMPTZ NOT NULL,
    status            TEXT        DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS host_stats (
    host            TEXT    PRIMARY KEY,
    total_files     BIGINT  NOT NULL DEFAULT 0,
    total_bytes     BIGINT  NOT NULL DEFAULT 0,
    total_hashed    BIGINT  NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS hash_stats (
    hash            TEXT PRIMARY KEY,
    copy_count      BIGINT NOT NULL,
    host_count      BIGINT NOT NULL,
    size_bytes      BIGINT,
    wasted_bytes    BIGINT,
    updated_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS host_hash_stats (
    host            TEXT NOT NULL,
    hash            TEXT NOT NULL,
    copy_count      BIGINT NOT NULL,
    copy_count_effective BIGINT NOT NULL,
    size_bytes      BIGINT,
    updated_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (host, hash)
);

CREATE TABLE IF NOT EXISTS directory_index (
    host            TEXT NOT NULL,
    drive           TEXT NOT NULL DEFAULT '',
    dir_path        TEXT NOT NULL,
    dir_display     TEXT,
    updated_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (host, drive, dir_path)
);

CREATE TABLE IF NOT EXISTS aggregate_meta (
    key             TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL,
    note            TEXT
);

CREATE TABLE IF NOT EXISTS host_hard_linked_inodes (
    host            TEXT NOT NULL,
    device          BIGINT NOT NULL,
    inode           BIGINT NOT NULL,
    PRIMARY KEY (host, device, inode)
);

CREATE TABLE IF NOT EXISTS maintenance_jobs (
    id              BIGINT PRIMARY KEY DEFAULT nextval('maintenance_job_id_seq'),
    job_type        TEXT NOT NULL,
    host            TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    priority        INTEGER NOT NULL DEFAULT 50,
    attempts        INTEGER NOT NULL DEFAULT 0,
    payload         TEXT,
    created_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL,
    last_error      TEXT
);

CREATE TABLE IF NOT EXISTS host_meta (
    host        TEXT PRIMARY KEY,
    hidden      BOOLEAN DEFAULT FALSE,
    label       TEXT,
    description TEXT,
    hidden_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_files_hash      ON files(hash);
CREATE INDEX IF NOT EXISTS idx_files_size      ON files(size_bytes);
CREATE INDEX IF NOT EXISTS idx_files_host      ON files(host);
CREATE INDEX IF NOT EXISTS idx_files_filename  ON files(filename);
CREATE INDEX IF NOT EXISTS idx_files_ext       ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_category  ON files(file_category);
CREATE INDEX IF NOT EXISTS idx_files_seen      ON files(host, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_files_host_path ON files(host, path);
CREATE INDEX IF NOT EXISTS idx_files_host_hash ON files(host, hash);
CREATE INDEX IF NOT EXISTS idx_maintenance_jobs_status_priority ON maintenance_jobs(status, priority, created_at);
"""


def get_db_path() -> str:
    if path := os.environ.get("SIFT_DB_PATH"):
        return path
    return str(Path.home() / ".sift.duckdb")


def get_connection() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _conn


def _run_migrations(conn: duckdb.DuckDBPyConnection) -> None:
    """Add columns to existing databases that predate the current schema."""
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'files'"
        ).fetchall()
    }
    for col, ddl in [
        ("inode", "ALTER TABLE files ADD COLUMN inode  BIGINT"),
        ("device", "ALTER TABLE files ADD COLUMN device BIGINT"),
    ]:
        if col not in existing:
            conn.execute(ddl)

    # Add root_path_display to scan_runs if missing (pre-0.3.11 databases)
    sr_cols = {
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'scan_runs'"
        ).fetchall()
    }
    if "root_path_display" not in sr_cols:
        conn.execute("ALTER TABLE scan_runs ADD COLUMN root_path_display TEXT")
    if "drive" not in sr_cols:
        # DuckDB does not support ADD COLUMN with constraints in one statement.
        # Add nullable/default first, backfill, then enforce NOT NULL.
        conn.execute("ALTER TABLE scan_runs ADD COLUMN drive TEXT DEFAULT ''")
        conn.execute("UPDATE scan_runs SET drive = '' WHERE drive IS NULL")
        conn.execute("ALTER TABLE scan_runs ALTER COLUMN drive SET NOT NULL")

    # Backfill host_stats if empty (one-time on upgrade)
    hs_row = conn.execute("SELECT COUNT(*) FROM host_stats").fetchone()
    hs_count = hs_row[0] if hs_row else 0
    if hs_count == 0:
        conn.execute("""
            INSERT INTO host_stats (host, total_files, total_bytes, total_hashed, updated_at)
            SELECT host, COUNT(*), COALESCE(SUM(size_bytes), 0),
                   COUNT(CASE WHEN hash IS NOT NULL THEN 1 END), now()
            FROM files WHERE skipped_reason IS NULL GROUP BY host
        """)

    # Migrate directory_index to host/drive-aware schema (pre-0.9.7 databases).
    di_cols = {
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'directory_index'"
        ).fetchall()
    }
    if "host" not in di_cols:
        conn.execute("DROP INDEX IF EXISTS idx_dir_index_path")
        conn.execute("DROP TABLE IF EXISTS directory_index")
        conn.execute("""
            CREATE TABLE directory_index (
                host        TEXT NOT NULL,
                drive       TEXT NOT NULL DEFAULT '',
                dir_path    TEXT NOT NULL,
                dir_display TEXT,
                updated_at  TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (host, drive, dir_path)
            )
        """)
        conn.execute("CREATE INDEX idx_dir_index_host_path ON directory_index(host, dir_path)")

    dir_row = conn.execute("SELECT COUNT(*) FROM directory_index").fetchone()
    dir_count = dir_row[0] if dir_row else 0
    file_row = conn.execute("SELECT COUNT(*) FROM files").fetchone()
    file_count = file_row[0] if file_row else 0
    if dir_count == 0 and file_count > 0:
        conn.execute(
            """
            INSERT INTO directory_index (host, drive, dir_path, dir_display, updated_at)
            SELECT
                host,
                drive,
                regexp_replace(path, '/[^/]+$', '') AS dir_path,
                ANY_VALUE(regexp_replace(path_display, '/[^/]+$', '')) AS dir_display,
                now()
            FROM files
            GROUP BY host, drive, regexp_replace(path, '/[^/]+$', '')
            HAVING regexp_replace(path, '/[^/]+$', '') != ''
            """
        )

    # Ensure directory_index index exists — covers both fresh DBs (table created
    # by SCHEMA_SQL with correct schema) and migrated DBs (table just recreated).
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dir_index_host_path ON directory_index(host, dir_path)")

    # --- Host casing normalization (one-time) ---
    # DuckDB string comparison is case-sensitive. Mixed-case host names cause
    # silent data splits across aggregate tables. See architecture-principles.md.
    # Batched by rowid range (~500K per chunk) to avoid DuckDB heap corruption
    # on large tables (8M+ rows with 10 indexes).
    _BATCH = 500_000
    mixed_hosts = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT host FROM files WHERE host != LOWER(host)"
        ).fetchall()
    ]
    if mixed_hosts:
        total = conn.execute(
            "SELECT COUNT(*) FROM files WHERE host != LOWER(host)"
        ).fetchone()[0]
        logger.info(
            "migration: normalizing %d files across %d hosts with mixed-case names",
            total, len(mixed_hosts),
        )

        for host in mixed_hosts:
            target = host.lower()
            host_count = conn.execute(
                "SELECT COUNT(*) FROM files WHERE host = ?", [host]
            ).fetchone()[0]
            logger.info("migration: processing host %r → %r (%d files)", host, target, host_count)

            # 1. Dedup if target host already has rows that would create PK conflicts
            conflicts = conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT 1 FROM files
                    WHERE host IN (?, ?)
                    GROUP BY LOWER(host), drive, path
                    HAVING COUNT(DISTINCT host) > 1
                ) t
            """, [host, target]).fetchone()[0]
            if conflicts > 0:
                logger.info("migration:   resolving %d PK conflicts for %r", conflicts, host)
                conn.execute("""
                    DELETE FROM files WHERE rowid IN (
                        SELECT rowid FROM (
                            SELECT rowid, ROW_NUMBER() OVER (
                                PARTITION BY LOWER(host), drive, path
                                ORDER BY last_seen_at DESC NULLS LAST
                            ) AS rn FROM files
                            WHERE host IN (?, ?)
                        ) t WHERE rn > 1
                    )
                """, [host, target])

            # 2. Lowercase this host's files in batches by rowid range
            bounds = conn.execute(
                "SELECT MIN(rowid), MAX(rowid) FROM files WHERE host = ?", [host]
            ).fetchone()
            lo, hi = bounds[0], bounds[1]
            if lo is not None:
                batch_num = 0
                total_batches = ((hi - lo) // _BATCH) + 1
                cursor = lo
                while cursor <= hi:
                    batch_num += 1
                    chunk_hi = min(cursor + _BATCH - 1, hi)
                    conn.execute(
                        "UPDATE files SET host = ? WHERE host = ? AND rowid BETWEEN ? AND ?",
                        [target, host, cursor, chunk_hi],
                    )
                    logger.info(
                        "migration:   %r batch %d/%d (rowid %d–%d)",
                        host, batch_num, total_batches, cursor, chunk_hi,
                    )
                    cursor = chunk_hi + 1
                logger.info("migration:   finished %r", host)

        # 3. Delete derived aggregate tables — rebuilt on startup
        for table in ["host_stats", "host_hash_stats", "host_hard_linked_inodes", "directory_index"]:
            conn.execute(f"DELETE FROM {table}")
        logger.info("migration: cleared derived aggregate tables")

        # 4. Lowercase scan_runs (no unique constraint on host)
        conn.execute("UPDATE scan_runs SET host = LOWER(host) WHERE host != LOWER(host)")

        # 5. Dedup and lowercase host_meta (PK on host)
        conn.execute("""
            DELETE FROM host_meta WHERE rowid IN (
                SELECT rowid FROM (
                    SELECT rowid, ROW_NUMBER() OVER (
                        PARTITION BY LOWER(host) ORDER BY host
                    ) AS rn FROM host_meta
                ) t WHERE rn > 1
            )
        """)
        conn.execute("UPDATE host_meta SET host = LOWER(host) WHERE host != LOWER(host)")

        # 6. Dedup and lowercase aggregate_meta host_hash_stats keys
        conn.execute("""
            DELETE FROM aggregate_meta WHERE rowid IN (
                SELECT rowid FROM (
                    SELECT rowid, ROW_NUMBER() OVER (
                        PARTITION BY LOWER(key) ORDER BY updated_at DESC NULLS LAST
                    ) AS rn FROM aggregate_meta
                    WHERE key LIKE 'host_hash_stats:%'
                ) t WHERE rn > 1
            )
        """)
        conn.execute("""
            UPDATE aggregate_meta
            SET key = 'host_hash_stats:' || LOWER(SUBSTRING(key, 17))
            WHERE key LIKE 'host_hash_stats:%'
              AND key != 'host_hash_stats:' || LOWER(SUBSTRING(key, 17))
        """)

        # 7. Mark all aggregates stale so startup rebuilds with correct data
        conn.execute("UPDATE aggregate_meta SET status = 'stale'")
        logger.info("migration: host casing normalization complete")


def init_db(db_path: str | None = None) -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        path = db_path or get_db_path()
        try:
            _conn = duckdb.connect(path)
        except duckdb.IOException as exc:
            if "lock" in str(exc).lower():
                import re, sys
                m = re.search(r"PID (\d+)", str(exc))
                if m:
                    pid = m.group(1)
                    kill_hint = f"taskkill /PID {pid} /F" if sys.platform == "win32" else f"kill {pid}"
                    msg = f"error: another sift server is already running (PID {pid}).\nStop it with:  {kill_hint}"
                else:
                    msg = "error: another sift server is already running.\nStop the other instance first."
                raise SystemExit(msg) from None
            raise
        # Cap parallelism so bulk queries don't saturate all cores on a shared host.
        # DuckDB defaults to using every available core.
        max_threads = int(os.environ.get("SIFT_DB_THREADS", "4"))
        _conn.execute(f"SET threads TO {max_threads}")
        for stmt in _split_statements(SCHEMA_SQL):
            if stmt.strip():
                _conn.execute(stmt)
        _run_migrations(_conn)


def _split_statements(sql: str) -> list[str]:
    """Split SQL on semicolons, preserving statement integrity."""
    return [s.strip() for s in sql.split(";") if s.strip()]


def execute(sql: str, params: list[Any] | None = None) -> None:
    """Execute a write statement under the global lock."""
    with _acquire_lock(sql):
        conn = get_connection()
        start = time.monotonic()
        if params:
            _run_with_query_timeout(conn, sql, lambda: conn.execute(sql, params))
        else:
            _run_with_query_timeout(conn, sql, lambda: conn.execute(sql))
        elapsed = time.monotonic() - start
        if elapsed > 1.0:
            logger.warning(
                "slow execute (%.1fs): %s",
                elapsed,
                _slow_log_context(sql, params),
            )


def query(sql: str, params: list[Any] | None = None) -> list[tuple]:
    """Execute a SELECT and return all rows under the global lock."""
    with _acquire_lock(sql):
        conn = get_connection()
        start = time.monotonic()
        if params:
            result = _run_with_query_timeout(
                conn, sql, lambda: conn.execute(sql, params)
            )
        else:
            result = _run_with_query_timeout(conn, sql, lambda: conn.execute(sql))
        rows = result.fetchall()
        elapsed = time.monotonic() - start
        if elapsed > 1.0:
            logger.warning(
                "slow query (%.1fs, %d rows): %s",
                elapsed,
                len(rows),
                _slow_log_context(sql, params),
            )
        return rows


def query_one(sql: str, params: list[Any] | None = None) -> tuple | None:
    """Execute a SELECT and return the first row, or None."""
    rows = query(sql, params)
    return rows[0] if rows else None


def executemany(sql: str, data: list[list[Any]]) -> None:
    """Execute a write statement for many rows under the global lock."""
    with _acquire_lock(sql):
        conn = get_connection()
        start = time.monotonic()
        _run_with_query_timeout(conn, sql, lambda: conn.executemany(sql, data))
        elapsed = time.monotonic() - start
        if elapsed > 1.0:
            logger.warning(
                "slow executemany (%.1fs, %d rows): %s",
                elapsed,
                len(data),
                _slow_log_context(sql, None),
            )


def refresh_host_stats(host: str) -> int:
    """Recompute and store aggregate stats for a single host.

    Returns the total file count for the host (0 means fully trimmed).
    """
    with _lock:
        conn = get_connection()
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0), "
            "COUNT(CASE WHEN hash IS NOT NULL THEN 1 END) "
            "FROM files WHERE host = ? AND skipped_reason IS NULL",
            [host],
        ).fetchone()
        if row is None:
            total_files, total_bytes, total_hashed = 0, 0, 0
        else:
            total_files, total_bytes, total_hashed = row
        conn.execute(
            "DELETE FROM host_stats WHERE host = ?",
            [host],
        )
        if total_files == 0:
            # Host fully trimmed — clean up all derived/meta entries
            conn.execute("DELETE FROM host_meta WHERE host = ?", [host])
            conn.execute("DELETE FROM host_hash_stats WHERE host = ?", [host])
            conn.execute("DELETE FROM host_hard_linked_inodes WHERE host = ?", [host])
            conn.execute(
                "DELETE FROM aggregate_meta WHERE key = ?",
                [f"host_hash_stats:{host}"],
            )
        else:
            conn.execute(
                "INSERT INTO host_stats (host, total_files, total_bytes, total_hashed, updated_at) "
                "VALUES (?, ?, ?, ?, now())",
                [host, total_files, total_bytes, total_hashed],
            )
        return total_files


def refresh_host_hard_linked_inodes(host: str) -> None:
    """Recompute pre-computed hard-linked inode pairs for a host."""
    with _lock:
        conn = get_connection()
        conn.execute("BEGIN TRANSACTION")
        conn.execute("DELETE FROM host_hard_linked_inodes WHERE host = ?", [host])
        conn.execute(
            """
            INSERT INTO host_hard_linked_inodes (host, device, inode)
            SELECT ?, device, inode FROM files
            WHERE host = ? AND inode IS NOT NULL AND device IS NOT NULL
            GROUP BY device, inode HAVING COUNT(*) > 1
            """,
            [host, host],
        )
        conn.execute("COMMIT")


def refresh_host_hash_stats(host: str) -> None:
    """Recompute per-host hash aggregates for eventual-consistent reads."""
    refresh_host_hard_linked_inodes(host)
    with _lock:
        conn = get_connection()
        conn.execute("BEGIN TRANSACTION")
        conn.execute("DELETE FROM host_hash_stats WHERE host = ?", [host])
        conn.execute(
            """
            WITH hard_linked_inodes AS (
                SELECT device, inode FROM host_hard_linked_inodes
                WHERE host = ?
            )
            INSERT INTO host_hash_stats (host, hash, copy_count, copy_count_effective, size_bytes, updated_at)
            SELECT
                ?,
                f.hash,
                COUNT(*) AS copy_count,
                COUNT(CASE WHEN NOT (
                    f.inode IS NOT NULL AND f.device IS NOT NULL
                    AND (f.device, f.inode) IN (SELECT device, inode FROM hard_linked_inodes)
                ) THEN 1 END) AS copy_count_effective,
                MAX(f.size_bytes) AS size_bytes,
                now()
            FROM files f
            WHERE f.host = ? AND f.hash IS NOT NULL
            GROUP BY f.hash
            """,
            [host, host, host],
        )
        conn.execute("COMMIT")


def refresh_hash_stats() -> None:
    """Recompute global hash aggregates from current files table."""
    with _lock:
        conn = get_connection()
        conn.execute("BEGIN TRANSACTION")
        conn.execute("DELETE FROM hash_stats")
        conn.execute(
            """
            INSERT INTO hash_stats (hash, copy_count, host_count, size_bytes, wasted_bytes, updated_at)
            SELECT
                hash,
                COUNT(*) AS copy_count,
                COUNT(DISTINCT host) AS host_count,
                MAX(size_bytes) AS size_bytes,
                CASE WHEN COUNT(*) > 1 THEN (COUNT(*) - 1) * MAX(size_bytes) ELSE 0 END AS wasted_bytes,
                now()
            FROM files
            WHERE hash IS NOT NULL
            GROUP BY hash
            """
        )
        conn.execute("COMMIT")


def refresh_directory_index() -> None:
    """Recompute directory search index from files table."""
    with _lock:
        conn = get_connection()
        conn.execute("BEGIN TRANSACTION")
        conn.execute("DELETE FROM directory_index")
        conn.execute(
            """
            INSERT INTO directory_index (host, drive, dir_path, dir_display, updated_at)
            SELECT
                host,
                drive,
                regexp_replace(path, '/[^/]+$', '') AS dir_path,
                ANY_VALUE(regexp_replace(path_display, '/[^/]+$', '')) AS dir_display,
                now()
            FROM files
            GROUP BY host, drive, regexp_replace(path, '/[^/]+$', '')
            """
        )
        conn.execute("COMMIT")


def refresh_aggregates_for_host(host: str) -> None:
    """Refresh aggregate tables after a host scan completes."""
    refresh_host_hash_stats(host)
    refresh_hash_stats()
    refresh_directory_index()


def set_aggregate_meta(key: str, status: str, note: str | None = None) -> None:
    """Upsert aggregate freshness/status metadata."""
    with _lock:
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO aggregate_meta (key, status, updated_at, note)
            VALUES (?, ?, now(), ?)
            ON CONFLICT (key)
            DO UPDATE SET status = excluded.status,
                          updated_at = now(),
                          note = excluded.note
            """,
            [key, status, note],
        )


def enqueue_maintenance_job(
    job_type: str,
    host: str | None = None,
    priority: int = 50,
    payload: str | None = None,
) -> bool:
    """Queue a maintenance job unless an equivalent pending/running one exists."""
    with _lock:
        conn = get_connection()
        row = conn.execute(
            """
            SELECT COUNT(*) FROM maintenance_jobs
            WHERE job_type = ?
              AND ((host IS NULL AND ? IS NULL) OR host = ?)
              AND status IN ('pending', 'running')
            """,
            [job_type, host, host],
        ).fetchone()
        count = row[0] if row else 0
        if count > 0:
            return False
        conn.execute(
            """
            INSERT INTO maintenance_jobs
            (job_type, host, status, priority, attempts, payload, created_at, updated_at)
            VALUES (?, ?, 'pending', ?, 0, ?, now(), now())
            """,
            [job_type, host, priority, payload],
        )
        return True


def dequeue_maintenance_job(max_priority: int | None = None) -> dict[str, Any] | None:
    """Pick the next pending maintenance job and mark it running."""
    with _lock:
        conn = get_connection()
        if max_priority is None:
            row = conn.execute(
                """
                SELECT id, job_type, host, priority, attempts, payload
                FROM maintenance_jobs
                WHERE status = 'pending'
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                """
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id, job_type, host, priority, attempts, payload
                FROM maintenance_jobs
                WHERE status = 'pending' AND priority <= ?
                ORDER BY priority ASC, created_at ASC
                LIMIT 1
                """,
                [max_priority],
            ).fetchone()
        if row is None:
            return None

        conn.execute(
            """
            UPDATE maintenance_jobs
            SET status = 'running', attempts = attempts + 1, updated_at = now(), last_error = NULL
            WHERE id = ?
            """,
            [row[0]],
        )
        return {
            "id": row[0],
            "job_type": row[1],
            "host": row[2],
            "priority": row[3],
            "attempts": row[4] + 1,
            "payload": row[5],
        }


def complete_maintenance_job(job_id: int) -> None:
    with _lock:
        conn = get_connection()
        conn.execute(
            "UPDATE maintenance_jobs SET status = 'complete', updated_at = now() WHERE id = ?",
            [job_id],
        )


def fail_maintenance_job(job_id: int, error: str, requeue: bool = False) -> None:
    with _lock:
        conn = get_connection()
        status = "pending" if requeue else "failed"
        conn.execute(
            """
            UPDATE maintenance_jobs
            SET status = ?, updated_at = now(), last_error = ?
            WHERE id = ?
            """,
            [status, error[:1000], job_id],
        )


def list_maintenance_jobs(limit: int = 50) -> list[tuple]:
    with _lock:
        conn = get_connection()
        return conn.execute(
            """
            SELECT id, job_type, host, status, priority, attempts, payload,
                   created_at, updated_at, last_error
            FROM maintenance_jobs
            ORDER BY id DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
