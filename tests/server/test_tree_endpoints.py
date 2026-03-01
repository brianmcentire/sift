"""Tests for fast tree endpoints used by the frontend."""

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
        assert entries["notes.txt"]["entry_type"] == "file"

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
                "segments": "a.jpg,c.jpg",
            },
        )
        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        assert set(metrics.keys()) == {"a.jpg", "c.jpg"}
