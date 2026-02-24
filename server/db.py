"""DuckDB connection, schema DDL, thread-safe query helpers."""
import os
import threading
from pathlib import Path
from typing import Any

import duckdb

_lock = threading.RLock()
_conn: duckdb.DuckDBPyConnection | None = None

SCHEMA_SQL = """
CREATE SEQUENCE IF NOT EXISTS scan_run_id_seq START 1;

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
    id          BIGINT      PRIMARY KEY DEFAULT nextval('scan_run_id_seq'),
    host        TEXT        NOT NULL,
    root_path   TEXT        NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    status      TEXT        DEFAULT 'running'
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
        ("inode",  "ALTER TABLE files ADD COLUMN inode  BIGINT"),
        ("device", "ALTER TABLE files ADD COLUMN device BIGINT"),
    ]:
        if col not in existing:
            conn.execute(ddl)


def init_db(db_path: str | None = None) -> None:
    global _conn
    with _lock:
        if _conn is not None:
            return
        path = db_path or get_db_path()
        _conn = duckdb.connect(path)
        for stmt in _split_statements(SCHEMA_SQL):
            if stmt.strip():
                _conn.execute(stmt)
        _run_migrations(_conn)


def _split_statements(sql: str) -> list[str]:
    """Split SQL on semicolons, preserving statement integrity."""
    return [s.strip() for s in sql.split(";") if s.strip()]


def execute(sql: str, params: list[Any] | None = None) -> None:
    """Execute a write statement under the global lock."""
    with _lock:
        conn = get_connection()
        if params:
            conn.execute(sql, params)
        else:
            conn.execute(sql)


def query(sql: str, params: list[Any] | None = None) -> list[tuple]:
    """Execute a SELECT and return all rows under the global lock."""
    with _lock:
        conn = get_connection()
        if params:
            result = conn.execute(sql, params)
        else:
            result = conn.execute(sql)
        return result.fetchall()


def query_one(sql: str, params: list[Any] | None = None) -> tuple | None:
    """Execute a SELECT and return the first row, or None."""
    rows = query(sql, params)
    return rows[0] if rows else None


def executemany(sql: str, data: list[list[Any]]) -> None:
    """Execute a write statement for many rows under the global lock."""
    with _lock:
        conn = get_connection()
        conn.executemany(sql, data)
