"""Tests for GET /files/page (paged List View API)."""

import server.db as db_module

from tests.server.conftest import (
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    client,
    insert_files,
    make_file,
)


class TestListFilesPage:
    def test_pagination_cursor_and_has_more(self, client):
        insert_files(
            [
                make_file(
                    path=f"/a/file{i}.txt", filename=f"file{i}.txt", hash=f"{i:064x}"
                )
                for i in range(6)
            ]
        )

        first = client.get("/files/page", params={"hosts": "mac", "limit": 2})
        assert first.status_code == 200
        first_data = first.json()
        assert len(first_data["items"]) == 2
        assert first_data["has_more"] is True
        assert first_data["next_cursor"] == "2"

        second = client.get(
            "/files/page", params={"hosts": "mac", "limit": 2, "cursor": "2"}
        )
        assert second.status_code == 200
        second_data = second.json()
        assert len(second_data["items"]) == 2
        assert second_data["next_cursor"] == "4"

    def test_sort_size_desc(self, client):
        insert_files(
            [
                make_file(
                    path="/a/small.txt", filename="small.txt", size=100, hash=HASH_B
                ),
                make_file(
                    path="/a/med.txt", filename="med.txt", size=1000, hash=HASH_C
                ),
                make_file(
                    path="/a/big.txt", filename="big.txt", size=10000, hash=HASH_D
                ),
            ]
        )

        resp = client.get(
            "/files/page",
            params={"hosts": "mac", "sort_by": "size", "sort_dir": "desc", "limit": 10},
        )
        assert resp.status_code == 200
        sizes = [r["size_bytes"] for r in resp.json()["items"]]
        assert sizes == [10000, 1000, 100]

    def test_hosts_filter(self, client):
        insert_files(
            [
                make_file(
                    host="mac", path="/users/a.txt", filename="a.txt", hash=HASH_A
                ),
                make_file(host="nas", path="/mnt/b.txt", filename="b.txt", hash=HASH_B),
                make_file(host="pi", path="/home/c.txt", filename="c.txt", hash=HASH_C),
            ]
        )

        resp = client.get("/files/page", params={"hosts": "mac,nas", "limit": 20})
        assert resp.status_code == 200
        hosts = {r["host"] for r in resp.json()["items"]}
        assert hosts == {"mac", "nas"}

    def test_categories_filter_multi(self, client):
        insert_files(
            [
                make_file(
                    path="/a/photo.jpg",
                    filename="photo.jpg",
                    category="image",
                    hash=HASH_A,
                ),
                make_file(
                    path="/a/song.mp3",
                    filename="song.mp3",
                    category="audio",
                    hash=HASH_B,
                ),
                make_file(
                    path="/a/doc.pdf",
                    filename="doc.pdf",
                    category="document",
                    hash=HASH_C,
                ),
            ]
        )

        resp = client.get(
            "/files/page",
            params={"hosts": "mac", "categories": "image,document", "limit": 20},
        )
        assert resp.status_code == 200
        cats = {r["file_category"] for r in resp.json()["items"]}
        assert cats == {"image", "document"}

    def test_path_contains_matches_anywhere_case_insensitive(self, client):
        insert_files(
            [
                make_file(
                    path="/Users/Brian/Docs/report.pdf",
                    filename="report.pdf",
                    hash=HASH_A,
                ),
                make_file(
                    path="/users/brian/music/song.mp3", filename="song.mp3", hash=HASH_B
                ),
                make_file(path="/tmp/cache.tmp", filename="cache.tmp", hash=HASH_C),
            ]
        )

        resp = client.get(
            "/files/page",
            params={"hosts": "mac", "path_contains": "BRIAN/do", "limit": 20},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["filename"] == "report.pdf"

    def test_hash_semantics_partial_contains_and_full_exact(self, client):
        insert_files(
            [
                make_file(path="/a/a.txt", filename="a.txt", hash=HASH_A),
                make_file(path="/a/b.txt", filename="b.txt", hash=HASH_B),
            ]
        )

        partial = client.get(
            "/files/page", params={"hosts": "mac", "hash": HASH_A[8:16], "limit": 20}
        )
        assert partial.status_code == 200
        assert len(partial.json()["items"]) == 1
        assert partial.json()["items"][0]["hash"] == HASH_A

        full = client.get(
            "/files/page", params={"hosts": "mac", "hash": HASH_A, "limit": 20}
        )
        assert full.status_code == 200
        assert len(full.json()["items"]) == 1
        assert full.json()["items"][0]["hash"] == HASH_A

    def test_has_duplicates_within_selected_hosts_only(self, client):
        insert_files(
            [
                make_file(
                    host="mac", path="/a/one.txt", filename="one.txt", hash=HASH_A
                ),
                make_file(
                    host="mac", path="/a/two.txt", filename="two.txt", hash=HASH_A
                ),
                make_file(
                    host="nas", path="/b/three.txt", filename="three.txt", hash=HASH_A
                ),
                make_file(
                    host="pi",
                    path="/c/outside.txt",
                    filename="outside.txt",
                    hash=HASH_C,
                ),
                make_file(
                    host="nas", path="/b/solo.txt", filename="solo.txt", hash=HASH_D
                ),
                make_file(
                    host="pi", path="/c/solo2.txt", filename="solo2.txt", hash=HASH_D
                ),
            ]
        )
        db_module.refresh_host_hash_stats("mac")
        db_module.refresh_host_hash_stats("nas")
        db_module.refresh_host_hash_stats("pi")
        db_module.set_aggregate_meta("host_hash_stats:mac", "fresh")
        db_module.set_aggregate_meta("host_hash_stats:nas", "fresh")
        db_module.set_aggregate_meta("host_hash_stats:pi", "fresh")

        resp = client.get(
            "/files/page",
            params={"hosts": "mac,nas", "has_duplicates": True, "limit": 20},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert {r["hash"] for r in items} == {HASH_A}
        assert {r["host"] for r in items} == {"mac", "nas"}
        assert all((r.get("dup_count") or 0) > 0 for r in items)

    def test_has_duplicates_returns_202_when_aggregate_not_fresh(self, client):
        insert_files(
            [
                make_file(
                    host="mac", path="/a/one.txt", filename="one.txt", hash=HASH_A
                ),
                make_file(
                    host="mac", path="/a/two.txt", filename="two.txt", hash=HASH_A
                ),
                make_file(
                    host="nas", path="/b/three.txt", filename="three.txt", hash=HASH_A
                ),
            ]
        )
        db_module.refresh_host_hash_stats("mac")
        db_module.refresh_host_hash_stats("nas")
        db_module.set_aggregate_meta("host_hash_stats:mac", "fresh")
        db_module.set_aggregate_meta("host_hash_stats:nas", "building")

        resp = client.get(
            "/files/page",
            params={"hosts": "mac,nas", "has_duplicates": True, "limit": 20},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pending"
        assert "Duplicate index" in data["detail"]

    def test_invalid_cursor_returns_400(self, client):
        resp = client.get("/files/page", params={"hosts": "mac", "cursor": "bad"})
        assert resp.status_code == 400

    def test_invalid_sort_returns_400(self, client):
        resp = client.get(
            "/files/page",
            params={"hosts": "mac", "sort_by": "nope", "sort_dir": "sideways"},
        )
        assert resp.status_code == 400
