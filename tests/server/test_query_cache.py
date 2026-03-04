"""Tests for query cache behavior and invalidation hooks."""

from tests.server.conftest import client, insert_files, insert_scan_run, make_file


class TestTreeCacheInvalidation:
    def test_post_files_invalidates_tree_children_cache(self, client):
        resp = client.post(
            "/files",
            json=[make_file(path="/users/brian/a.txt", filename="a.txt")],
        )
        assert resp.status_code == 200

        first = client.get(
            "/tree/children", params={"path": "/users/brian", "host": "mac"}
        )
        assert first.status_code == 200
        assert {e["segment"] for e in first.json()["items"]} == {"a.txt"}

        # Prime cache explicitly with a second read.
        second = client.get(
            "/tree/children", params={"path": "/users/brian", "host": "mac"}
        )
        assert second.status_code == 200
        assert {e["segment"] for e in second.json()["items"]} == {"a.txt"}

        # Data mutation through POST /files should clear tree cache.
        resp = client.post(
            "/files",
            json=[make_file(path="/users/brian/b.txt", filename="b.txt")],
        )
        assert resp.status_code == 200

        third = client.get(
            "/tree/children", params={"path": "/users/brian", "host": "mac"}
        )
        assert third.status_code == 200
        assert {e["segment"] for e in third.json()["items"]} == {"a.txt", "b.txt"}

    def test_trim_invalidates_tree_children_cache(self, client):
        client.post(
            "/files",
            json=[
                make_file(path="/users/brian/a.txt", filename="a.txt"),
                make_file(path="/users/brian2/b.txt", filename="b.txt"),
            ],
        )

        before = client.get("/tree/children", params={"path": "/users", "host": "mac"})
        assert before.status_code == 200
        assert {e["segment"] for e in before.json()["items"]} == {"brian", "brian2"}

        # Prime cache.
        cached = client.get("/tree/children", params={"path": "/users", "host": "mac"})
        assert cached.status_code == 200

        trim_resp = client.post(
            "/trim",
            json={
                "host": "mac",
                "path_prefix": "/users/brian",
                "recursive": True,
                "deleted_only": False,
                "patterns": [],
                "limit": 5000,
            },
        )
        assert trim_resp.status_code == 200
        assert trim_resp.json()["deleted"] == 1

        after = client.get("/tree/children", params={"path": "/users", "host": "mac"})
        assert after.status_code == 200
        assert {e["segment"] for e in after.json()["items"]} == {"brian2"}

    def test_scan_completion_invalidates_tree_children_cache(self, client):
        run_id = insert_scan_run(host="mac", root_path="/users", status="running")
        insert_files([make_file(path="/users/brian/a.txt", filename="a.txt")])

        first = client.get(
            "/tree/children", params={"path": "/users/brian", "host": "mac"}
        )
        assert first.status_code == 200
        assert {e["segment"] for e in first.json()["items"]} == {"a.txt"}

        # Mutate DB directly (simulates out-of-band updates) so cache would be stale.
        insert_files([make_file(path="/users/brian/b.txt", filename="b.txt")])
        stale = client.get(
            "/tree/children", params={"path": "/users/brian", "host": "mac"}
        )
        assert {e["segment"] for e in stale.json()["items"]} == {"a.txt"}

        patch = client.patch(f"/scan-runs/{run_id}", json={"status": "complete"})
        assert patch.status_code == 200

        fresh = client.get(
            "/tree/children", params={"path": "/users/brian", "host": "mac"}
        )
        assert {e["segment"] for e in fresh.json()["items"]} == {"a.txt", "b.txt"}


class TestDirectoryCacheInvalidation:
    def test_post_files_invalidates_directory_cache(self, client):
        client.post(
            "/files",
            json=[make_file(path="/users/brian/first/a.txt", filename="a.txt")],
        )

        first = client.get("/directories", params={"q": "users/brian", "limit": 50})
        assert first.status_code == 200
        first_paths = {r["dir_path"] for r in first.json()}
        assert "/users/brian/first" in first_paths
        assert "/users/brian/second" not in first_paths

        # Prime cache.
        second = client.get("/directories", params={"q": "users/brian", "limit": 50})
        assert second.status_code == 200

        client.post(
            "/files",
            json=[make_file(path="/users/brian/second/b.txt", filename="b.txt")],
        )

        third = client.get("/directories", params={"q": "users/brian", "limit": 50})
        assert third.status_code == 200
        third_paths = {r["dir_path"] for r in third.json()}
        assert "/users/brian/second" in third_paths
