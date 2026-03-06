"""Tests for fast tree endpoints used by the frontend."""

import server.db as db_module
import server.main as main_module

from tests.server.conftest import HASH_A, HASH_B, client, insert_files, make_file


class TestTreeChildren:
    def test_returns_immediate_children_with_file_and_dir_entries(self, client):
        insert_files(
            [
                make_file(
                    path="/users/brian/docs/a.txt", filename="a.txt", hash=HASH_A
                ),
                make_file(
                    path="/users/brian/notes.txt", filename="notes.txt", hash=HASH_B
                ),
            ]
        )

        resp = client.get(
            "/tree/children", params={"path": "/users/brian", "host": "mac"}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "items" in data
        entries = {e["segment"]: e for e in data["items"]}
        assert "docs" in entries
        assert "notes.txt" in entries
        assert entries["docs"]["entry_type"] == "dir"
        assert entries["docs"]["file_count"] == 1
        assert entries["docs"]["total_bytes"] == 1000
        assert entries["notes.txt"]["entry_type"] == "file"
        assert entries["notes.txt"]["file_count"] == 1
        assert entries["notes.txt"]["total_bytes"] == 1000

    def test_cursor_pagination(self, client):
        insert_files(
            [
                make_file(
                    path=f"/users/brian/file{i}.txt",
                    filename=f"file{i}.txt",
                    hash=HASH_A,
                )
                for i in range(6)
            ]
        )

        first = client.get(
            "/tree/children",
            params={"path": "/users/brian", "host": "mac", "limit": 2},
        )
        assert first.status_code == 200
        first_data = first.json()
        assert len(first_data["items"]) == 2
        assert first_data["has_more"] is True
        assert first_data["next_cursor"] is not None

        second = client.get(
            "/tree/children",
            params={
                "path": "/users/brian",
                "host": "mac",
                "limit": 2,
                "cursor": first_data["next_cursor"],
            },
        )
        assert second.status_code == 200
        second_data = second.json()
        assert len(second_data["items"]) == 2

    def test_invalid_cursor_returns_400(self, client):
        resp = client.get(
            "/tree/children",
            params={"path": "/users/brian", "host": "mac", "cursor": "not-a-number"},
        )
        assert resp.status_code == 400


class TestTreeDupMetrics:
    def test_returns_dup_metrics_for_same_host_duplicates(self, client):
        insert_files(
            [
                make_file(
                    path="/users/brian/photos/a.jpg", filename="a.jpg", hash=HASH_A
                ),
                make_file(
                    path="/users/brian/photos/b.jpg", filename="b.jpg", hash=HASH_A
                ),
                make_file(
                    path="/users/brian/photos/c.jpg", filename="c.jpg", hash=HASH_B
                ),
            ]
        )

        resp = client.get(
            "/tree/dup-metrics",
            params={"path": "/users/brian/photos", "host": "mac", "min_size": 0},
        )
        assert resp.status_code == 200
        data = resp.json()
        metrics = data["metrics"]

        assert metrics["a.jpg"]["dup_count"] == 1
        assert metrics["b.jpg"]["dup_count"] == 1
        assert metrics["c.jpg"]["dup_count"] == 0
        # file_count and total_bytes populated from dup-metrics
        assert metrics["a.jpg"]["file_count"] == 1
        assert metrics["a.jpg"]["total_bytes"] == 1000
        assert metrics["c.jpg"]["file_count"] == 1

    def test_cross_host_info_populates_other_hosts(self, client):
        insert_files(
            [
                make_file(
                    host="mac",
                    path="/users/brian/photo.jpg",
                    filename="photo.jpg",
                    hash=HASH_A,
                ),
                make_file(
                    host="nas",
                    path="/mnt/backup/photo.jpg",
                    filename="photo.jpg",
                    hash=HASH_A,
                ),
            ]
        )

        resp = client.get(
            "/tree/dup-metrics",
            params={"path": "/users/brian", "host": "mac", "min_size": 0},
        )
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        assert metrics["photo.jpg"]["other_hosts"] == "nas"

    def test_segments_filter_limits_result_scope(self, client):
        insert_files(
            [
                make_file(
                    path="/users/brian/photos/a.jpg", filename="a.jpg", hash=HASH_A
                ),
                make_file(
                    path="/users/brian/photos/b.jpg", filename="b.jpg", hash=HASH_A
                ),
                make_file(
                    path="/users/brian/photos/c.jpg", filename="c.jpg", hash=HASH_B
                ),
            ]
        )

        resp = client.get(
            "/tree/dup-metrics",
            params={
                "path": "/users/brian/photos",
                "host": "mac",
                "segments": ["a.jpg", "c.jpg"],
            },
        )
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        assert set(metrics.keys()) == {"a.jpg", "c.jpg"}

    def test_large_host_without_aggregates_skips_live_fallback(self, client):
        # Simulate a large host where live fallback would be expensive.
        db_module.execute(
            "INSERT INTO host_stats (host, total_files, total_bytes, total_hashed, updated_at) VALUES (?, ?, ?, ?, now())",
            ["mac", 500000, 0, 0],
        )
        # Ensure there are no host_hash_stats rows to force has_agg=False path.
        db_module.execute("DELETE FROM host_hash_stats WHERE host = ?", ["mac"])

        previous = main_module._MAINTENANCE_ENABLED
        main_module._MAINTENANCE_ENABLED = True

        try:
            resp = client.get(
                "/tree/dup-metrics",
                params={"path": "/users/brian", "host": "mac", "segments": ["a.jpg"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["metrics"] == {}
            assert data["data_freshness"] == "stale"

            job_row = db_module.query_one(
                "SELECT COUNT(*) FROM maintenance_jobs WHERE job_type = 'refresh_host_hash_stats' AND host = ?",
                ["mac"],
            )
            assert job_row is not None and job_row[0] >= 1
        finally:
            main_module._MAINTENANCE_ENABLED = previous

    def test_large_host_without_aggregates_uses_lite_fallback_when_maintenance_disabled(
        self, client
    ):
        db_module.execute(
            "INSERT INTO host_stats (host, total_files, total_bytes, total_hashed, updated_at) VALUES (?, ?, ?, ?, now())",
            ["mac", 500000, 0, 0],
        )
        db_module.execute("DELETE FROM host_hash_stats WHERE host = ?", ["mac"])
        db_module.execute(
            "INSERT INTO files (host, drive, path, path_display, filename, ext, file_category, size_bytes, hash, mtime, last_checked, source_os, skipped_reason, last_seen_at, inode, device) VALUES (?, '', ?, ?, ?, 'jpg', 'image', 10, ?, 0, now(), 'darwin', NULL, now(), NULL, NULL)",
            ["mac", "/users/brian/a.jpg", "/users/brian/a.jpg", "a.jpg", HASH_A],
        )
        db_module.execute(
            "INSERT INTO files (host, drive, path, path_display, filename, ext, file_category, size_bytes, hash, mtime, last_checked, source_os, skipped_reason, last_seen_at, inode, device) VALUES (?, '', ?, ?, ?, 'jpg', 'image', 10, ?, 0, now(), 'darwin', NULL, now(), NULL, NULL)",
            ["mac", "/users/brian/b.jpg", "/users/brian/b.jpg", "b.jpg", HASH_A],
        )

        previous = main_module._MAINTENANCE_ENABLED
        main_module._MAINTENANCE_ENABLED = False
        try:
            resp = client.get(
                "/tree/dup-metrics",
                params={
                    "path": "/users/brian",
                    "host": "mac",
                    "segments": ["a.jpg", "b.jpg"],
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["data_freshness"] == "stale"
            assert data["metrics"]["a.jpg"]["dup_count"] == 1
            assert data["metrics"]["b.jpg"]["dup_count"] == 1
            # file_count and total_bytes present in lite fallback
            assert data["metrics"]["a.jpg"]["file_count"] == 1
            assert data["metrics"]["a.jpg"]["total_bytes"] == 10
            assert data["metrics"]["b.jpg"]["file_count"] == 1
            assert data["metrics"]["b.jpg"]["total_bytes"] == 10
        finally:
            main_module._MAINTENANCE_ENABLED = previous

    def test_lite_fallback_counts_directory_segment_duplicates(self, client):
        db_module.execute(
            "INSERT INTO host_stats (host, total_files, total_bytes, total_hashed, updated_at) VALUES (?, ?, ?, ?, now())",
            ["mac", 500000, 0, 0],
        )
        db_module.execute("DELETE FROM host_hash_stats WHERE host = ?", ["mac"])
        db_module.execute(
            "INSERT INTO files (host, drive, path, path_display, filename, ext, file_category, size_bytes, hash, mtime, last_checked, source_os, skipped_reason, last_seen_at, inode, device) VALUES (?, '', ?, ?, ?, 'jpg', 'image', 10, ?, 0, now(), 'darwin', NULL, now(), NULL, NULL)",
            ["mac", "/users/brian/a.jpg", "/users/brian/a.jpg", "a.jpg", HASH_A],
        )
        db_module.execute(
            "INSERT INTO files (host, drive, path, path_display, filename, ext, file_category, size_bytes, hash, mtime, last_checked, source_os, skipped_reason, last_seen_at, inode, device) VALUES (?, '', ?, ?, ?, 'jpg', 'image', 10, ?, 0, now(), 'darwin', NULL, now(), NULL, NULL)",
            ["mac", "/users/brian/b.jpg", "/users/brian/b.jpg", "b.jpg", HASH_A],
        )

        previous = main_module._MAINTENANCE_ENABLED
        main_module._MAINTENANCE_ENABLED = False
        try:
            resp = client.get(
                "/tree/dup-metrics",
                params={"path": "/", "host": "mac", "segments": ["users"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["metrics"]["users"]["dup_count"] >= 1
            assert data["metrics"]["users"]["dup_hash_count"] >= 1
            # directory segment should aggregate file_count and total_bytes
            assert data["metrics"]["users"]["file_count"] == 2
            assert data["metrics"]["users"]["total_bytes"] == 20  # 2 files × 10 bytes
        finally:
            main_module._MAINTENANCE_ENABLED = previous
