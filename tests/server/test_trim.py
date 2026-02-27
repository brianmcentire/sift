"""Tests for POST /trim."""

import server.db as db_module
from tests.server.conftest import NOW, client, insert_files, make_file


def _insert_scan_run(host: str, root_path: str, started_at: str, status: str) -> None:
    db_module.execute(
        "INSERT INTO scan_runs (host, root_path, started_at, status) VALUES (?, ?, ?, ?)",
        [host, root_path, started_at, status],
    )


class TestTrimTargeted:
    def test_recursive_root_removes_all_for_host(self, client):
        insert_files(
            [
                make_file(host="mac", path="/users/brian/a.txt", filename="a.txt"),
                make_file(host="mac", path="/users/brian/b.txt", filename="b.txt"),
                make_file(host="nas", path="/users/brian/a.txt", filename="a.txt"),
            ]
        )

        resp = client.post(
            "/trim",
            json={
                "host": "mac",
                "path_prefix": "/",
                "recursive": True,
                "deleted_only": False,
                "patterns": [],
                "limit": 5000,
                "count_only": False,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2

        mac_left = client.get("/files", params={"host": "mac", "limit": 1000}).json()
        nas_left = client.get("/files", params={"host": "nas", "limit": 1000}).json()
        assert len(mac_left) == 0
        assert len(nas_left) == 1

    def test_non_recursive_only_direct_children(self, client):
        insert_files(
            [
                make_file(path="/users/brian/top.txt", filename="top.txt"),
                make_file(path="/users/brian/sub/deep.txt", filename="deep.txt"),
            ]
        )

        resp = client.post(
            "/trim",
            json={
                "host": "mac",
                "path_prefix": "/users/brian",
                "recursive": False,
                "deleted_only": False,
                "patterns": [],
                "limit": 5000,
                "count_only": False,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

        rows = client.get("/files", params={"host": "mac", "limit": 1000}).json()
        paths = {r["path_display"].lower() for r in rows}
        assert "/users/brian/top.txt" not in paths
        assert "/users/brian/sub/deep.txt" in paths

    def test_patterns_match_basename_only(self, client):
        insert_files(
            [
                make_file(path="/users/brian/a.jpg", filename="a.jpg"),
                make_file(path="/users/brian/sub/a.jpg", filename="a.jpg"),
                make_file(path="/users/brian/b.png", filename="b.png"),
            ]
        )

        resp = client.post(
            "/trim",
            json={
                "host": "mac",
                "path_prefix": "/users/brian",
                "recursive": True,
                "deleted_only": False,
                "patterns": ["*.jpg"],
                "limit": 5000,
                "count_only": False,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 2

        rows = client.get("/files", params={"host": "mac", "limit": 1000}).json()
        names = {r["filename"] for r in rows}
        assert names == {"b.png"}

    def test_count_only_preview_returns_paths(self, client):
        insert_files(
            [
                make_file(path="/users/brian/a.txt", filename="a.txt"),
                make_file(path="/users/brian/b.txt", filename="b.txt"),
            ]
        )

        resp = client.post(
            "/trim",
            json={
                "host": "mac",
                "path_prefix": "/users/brian",
                "recursive": True,
                "deleted_only": False,
                "patterns": ["*.txt"],
                "limit": 1,
                "count_only": True,
                "preview": True,
                "offset": 1,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["matched"] == 2
        assert body["deleted"] == 0
        assert len(body["preview_paths"]) == 1


class TestTrimDeletedOnly:
    def test_deleted_only_uses_latest_covering_complete_scan(self, client):
        old = "2025-01-01T00:00:00+00:00"
        complete = "2025-01-15T00:00:00+00:00"

        insert_files(
            [
                make_file(
                    path="/users/brian/stale.txt",
                    filename="stale.txt",
                    skipped_reason="volatile_active",
                ),
                make_file(path="/users/brian/fresh.txt", filename="fresh.txt"),
            ]
        )
        # Force stale/fresh seen timestamps
        db_module.execute(
            "UPDATE files SET last_seen_at = ? WHERE host = ? AND path = ?",
            [old, "mac", "/users/brian/stale.txt"],
        )
        db_module.execute(
            "UPDATE files SET last_seen_at = ? WHERE host = ? AND path = ?",
            [NOW, "mac", "/users/brian/fresh.txt"],
        )

        _insert_scan_run("mac", "/users/brian", complete, "complete")

        resp = client.post(
            "/trim",
            json={
                "host": "mac",
                "path_prefix": "/users/brian",
                "recursive": True,
                "deleted_only": True,
                "patterns": [],
                "limit": 5000,
                "count_only": False,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

        rows = client.get("/files", params={"host": "mac", "limit": 1000}).json()
        names = {r["filename"] for r in rows}
        assert names == {"fresh.txt"}

    def test_deleted_only_ignores_interrupted_runs(self, client):
        old = "2025-01-01T00:00:00+00:00"
        interrupted = "2025-01-20T00:00:00+00:00"

        insert_files(
            [
                make_file(path="/users/brian/a.txt", filename="a.txt"),
            ]
        )
        db_module.execute(
            "UPDATE files SET last_seen_at = ? WHERE host = ? AND path = ?",
            [old, "mac", "/users/brian/a.txt"],
        )
        _insert_scan_run("mac", "/users/brian", interrupted, "interrupted")

        resp = client.post(
            "/trim",
            json={
                "host": "mac",
                "path_prefix": "/users/brian",
                "recursive": True,
                "deleted_only": True,
                "patterns": [],
                "limit": 5000,
                "count_only": False,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0

    def test_deleted_only_skips_rows_without_covering_complete_scan(self, client):
        old = "2025-01-01T00:00:00+00:00"
        complete_other_root = "2025-01-15T00:00:00+00:00"

        insert_files(
            [
                make_file(path="/users/brian/a.txt", filename="a.txt"),
            ]
        )
        db_module.execute(
            "UPDATE files SET last_seen_at = ? WHERE host = ? AND path = ?",
            [old, "mac", "/users/brian/a.txt"],
        )
        _insert_scan_run("mac", "/tmp", complete_other_root, "complete")

        resp = client.post(
            "/trim",
            json={
                "host": "mac",
                "path_prefix": "/users/brian",
                "recursive": True,
                "deleted_only": True,
                "patterns": [],
                "limit": 5000,
                "count_only": False,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 0
