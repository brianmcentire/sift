"""
Fixtures and helpers shared by all server tests.

Each test gets a fresh in-memory DuckDB — we reset the global _conn before
every test via the autouse `fresh_db` fixture, then pre-init with ":memory:"
so the FastAPI lifespan's init_db() call hits the guard and skips.
"""
import pytest
import server.db as db_module
from fastapi.testclient import TestClient
from server.main import app

# Stable timestamp used across fixture data
NOW = "2025-01-15T10:00:00+00:00"

# Fixed fake SHA-256 hashes (64 hex chars each)
HASH_A = "a" * 64  # same-host dup on mac (two files share it)
HASH_B = "b" * 64  # unique to mac
HASH_C = "c" * 64  # cross-host dup: one copy on mac, one on nas
HASH_D = "d" * 64  # unique to nas
HASH_E = "e" * 64  # unique to pi
HASH_F = "f" * 64  # appears 3× on mac (same-host)


@pytest.fixture(autouse=True)
def fresh_db():
    """Give every server test a clean in-memory DuckDB."""
    db_module._conn = None
    db_module.init_db(":memory:")
    # Clear any module-level caches that survive across tests
    from server.main import _stats_cache
    _stats_cache.clear()
    yield
    if db_module._conn:
        db_module._conn.close()
    db_module._conn = None


@pytest.fixture
def client():
    """FastAPI TestClient backed by the in-memory DB."""
    # lifespan fires init_db() but _conn is already set → guard skips it
    with TestClient(app) as c:
        yield c


def make_file(
    host="mac",
    path="/users/brian/file.txt",
    filename="file.txt",
    hash=HASH_B,
    size=1000,
    drive="",
    ext="txt",
    category="document",
    path_display=None,
    source_os="darwin",
    mtime=1700000000,
    skipped_reason=None,
    inode=None,
    device=None,
):
    """Return a dict suitable for insert_files()."""
    return {
        "host": host,
        "drive": drive,
        "path": path,
        "path_display": path_display or path,
        "filename": filename,
        "ext": ext,
        "file_category": category,
        "size_bytes": size,
        "hash": hash,
        "mtime": mtime,
        "last_checked": NOW,
        "source_os": source_os,
        "skipped_reason": skipped_reason,
        "last_seen_at": NOW,
        "inode": inode,
        "device": device,
    }


def insert_files(records: list[dict]) -> None:
    """Insert test file records directly into the in-memory DB."""
    sql = """
        INSERT INTO files (
            host, drive, path, path_display, filename, ext, file_category,
            size_bytes, hash, mtime, last_checked, source_os, skipped_reason, last_seen_at,
            inode, device
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (host, drive, path) DO NOTHING
    """
    data = [
        [
            r["host"], r["drive"], r["path"], r["path_display"], r["filename"],
            r["ext"], r["file_category"], r["size_bytes"], r["hash"], r["mtime"],
            r["last_checked"], r["source_os"], r["skipped_reason"], r["last_seen_at"],
            r.get("inode"), r.get("device"),
        ]
        for r in records
    ]
    db_module.executemany(sql, data)
    # Keep host_stats in sync — /hosts reads from this table, not files directly
    hosts_seen = {r["host"] for r in records}
    for host in hosts_seen:
        db_module.refresh_host_stats(host)


def insert_scan_run(host="mac", root_path="/", status="complete") -> int:
    """Insert a scan run and return its id."""
    db_module.execute(
        "INSERT INTO scan_runs (host, root_path, started_at, status) VALUES (?, ?, ?, ?)",
        [host, root_path, NOW, status],
    )
    row = db_module.query_one(
        "SELECT id FROM scan_runs WHERE host = ? AND root_path = ? ORDER BY id DESC LIMIT 1",
        [host, root_path],
    )
    return row[0]
