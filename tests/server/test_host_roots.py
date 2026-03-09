"""Tests for GET /hosts/roots."""

from datetime import datetime

import server.db as db_module
from tests.server.conftest import client


def _scan_run(
    host: str,
    root_path: str,
    started_at: str,
    status: str,
    drive: str = "",
    root_path_display: str | None = None,
):
    db_module.execute(
        """
        INSERT INTO scan_runs (host, drive, root_path, root_path_display, started_at, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [host, drive, root_path, root_path_display, started_at, status],
    )


def test_hosts_roots_returns_effective_complete_roots(client):
    _scan_run("mac", "/users", "2026-03-01T00:00:00+00:00", "complete")
    _scan_run("mac", "/users/brian", "2026-03-02T00:00:00+00:00", "complete")
    _scan_run("mac", "/volumes/archive", "2026-03-03T00:00:00+00:00", "complete")
    _scan_run("mac", "/users/brian/tmp", "2026-03-04T00:00:00+00:00", "failed")
    _scan_run("nas", "/", "2026-03-01T00:00:00+00:00", "complete")
    _scan_run("nas", "/mnt/user", "2026-03-02T00:00:00+00:00", "complete")

    resp = client.get("/hosts/roots")
    assert resp.status_code == 200
    rows = resp.json()

    by_host = {}
    for r in rows:
        by_host.setdefault(r["host"], []).append(r)

    mac_roots = sorted(r["root_path"] for r in by_host["mac"])
    assert mac_roots == ["/users", "/volumes/archive"]

    nas_roots = sorted(r["root_path"] for r in by_host["nas"])
    assert nas_roots == ["/"]


def test_hosts_roots_reports_latest_complete_date_per_root(client):
    _scan_run("mac", "/users", "2026-03-01T00:00:00+00:00", "complete")
    _scan_run("mac", "/users", "2026-03-09T00:00:00+00:00", "complete")
    _scan_run("mac", "/users", "2026-03-10T00:00:00+00:00", "interrupted")

    resp = client.get("/hosts/roots", params={"host": "mac"})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["root_path"] == "/users"
    got_ts = datetime.fromisoformat(rows[0]["latest_complete_at"]).timestamp()
    want_ts = datetime.fromisoformat("2026-03-09T00:00:00+00:00").timestamp()
    assert abs(got_ts - want_ts) < 1.0


def test_hosts_roots_uses_root_path_display_when_present(client):
    _scan_run(
        "mac",
        "/users",
        "2026-03-09T00:00:00+00:00",
        "complete",
        root_path_display="/Users",
    )

    resp = client.get("/hosts/roots", params={"host": "mac"})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["root_path"] == "/Users"
