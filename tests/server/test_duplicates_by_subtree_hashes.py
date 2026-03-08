"""Tests for GET /files/duplicates-by-subtree-hashes."""

import server.db as db_module

from tests.server.conftest import (
    HASH_A,
    HASH_B,
    HASH_C,
    client,
    insert_files,
    make_file,
)


class TestDuplicatesBySubtreeHashes:
    def test_subtree_scope_returns_only_subtree_members(self, client):
        insert_files(
            [
                make_file(
                    host="mac", path="/a/sub/one.txt", filename="one.txt", hash=HASH_A
                ),
                make_file(
                    host="nas", path="/x/two.txt", filename="two.txt", hash=HASH_A
                ),
                make_file(
                    host="mac",
                    path="/a/sub/three.txt",
                    filename="three.txt",
                    hash=HASH_B,
                ),
                make_file(
                    host="nas", path="/z/four.txt", filename="four.txt", hash=HASH_B
                ),
                make_file(
                    host="mac", path="/a/sub/solo.txt", filename="solo.txt", hash=HASH_C
                ),
            ]
        )
        db_module.refresh_host_hash_stats("mac")
        db_module.refresh_host_hash_stats("nas")
        db_module.set_aggregate_meta("host_hash_stats:mac", "fresh")
        db_module.set_aggregate_meta("host_hash_stats:nas", "fresh")

        resp = client.get(
            "/files/duplicates-by-subtree-hashes",
            params={
                "hosts": "mac,nas",
                "path_prefix": "/a/sub",
                "scope": "subtree",
                "min_size": 0,
            },
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 2
        assert {r["host"] for r in rows} == {"mac"}
        assert {r["hash"] for r in rows} == {HASH_A, HASH_B}
        assert all(r["in_subtree"] is True for r in rows)

    def test_context_scope_returns_all_members_of_seed_hashes(self, client):
        insert_files(
            [
                make_file(
                    host="mac", path="/a/sub/one.txt", filename="one.txt", hash=HASH_A
                ),
                make_file(
                    host="nas", path="/x/two.txt", filename="two.txt", hash=HASH_A
                ),
                make_file(
                    host="pi", path="/q/three.txt", filename="three.txt", hash=HASH_A
                ),
                make_file(
                    host="mac",
                    path="/a/sub/other.txt",
                    filename="other.txt",
                    hash=HASH_B,
                ),
                make_file(
                    host="nas", path="/z/four.txt", filename="four.txt", hash=HASH_B
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
            "/files/duplicates-by-subtree-hashes",
            params={
                "hosts": "mac,nas,pi",
                "path_prefix": "/a/sub",
                "scope": "context",
                "min_size": 0,
            },
        )
        assert resp.status_code == 200
        rows = resp.json()
        # Both hashes are seeded by /a/sub; context returns all copies for those hashes.
        assert {r["hash"] for r in rows} == {HASH_A, HASH_B}
        assert {r["host"] for r in rows} == {"mac", "nas", "pi"}
        assert any(r["in_subtree"] is True for r in rows)
        assert any(r["in_subtree"] is False for r in rows)

    def test_categories_filter_applies_to_seed_and_results(self, client):
        insert_files(
            [
                make_file(
                    host="mac",
                    path="/a/sub/pic.jpg",
                    filename="pic.jpg",
                    category="image",
                    hash=HASH_A,
                ),
                make_file(
                    host="nas",
                    path="/x/pic.jpg",
                    filename="pic.jpg",
                    category="image",
                    hash=HASH_A,
                ),
                make_file(
                    host="mac",
                    path="/a/sub/doc.pdf",
                    filename="doc.pdf",
                    category="document",
                    hash=HASH_B,
                ),
                make_file(
                    host="nas",
                    path="/x/doc.pdf",
                    filename="doc.pdf",
                    category="document",
                    hash=HASH_B,
                ),
            ]
        )
        db_module.refresh_host_hash_stats("mac")
        db_module.refresh_host_hash_stats("nas")
        db_module.set_aggregate_meta("host_hash_stats:mac", "fresh")
        db_module.set_aggregate_meta("host_hash_stats:nas", "fresh")

        resp = client.get(
            "/files/duplicates-by-subtree-hashes",
            params={
                "hosts": "mac,nas",
                "path_prefix": "/a/sub",
                "scope": "context",
                "categories": "image",
            },
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 2
        assert {r["file_category"] for r in rows} == {"image"}
        assert {r["hash"] for r in rows} == {HASH_A}

    def test_returns_202_when_any_selected_host_aggregate_not_fresh(self, client):
        insert_files(
            [
                make_file(
                    host="mac", path="/a/sub/one.txt", filename="one.txt", hash=HASH_A
                ),
                make_file(
                    host="nas", path="/x/two.txt", filename="two.txt", hash=HASH_A
                ),
            ]
        )
        db_module.refresh_host_hash_stats("mac")
        db_module.refresh_host_hash_stats("nas")
        db_module.set_aggregate_meta("host_hash_stats:mac", "fresh")
        db_module.set_aggregate_meta("host_hash_stats:nas", "building")

        resp = client.get(
            "/files/duplicates-by-subtree-hashes",
            params={
                "hosts": "mac,nas",
                "path_prefix": "/a/sub",
                "scope": "subtree",
            },
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "pending"
        assert "Duplicate index" in body["detail"]

    def test_context_scope_not_drive_limited_for_result_rows(self, client):
        insert_files(
            [
                make_file(
                    host="pc",
                    drive="D",
                    path="/video/a.mkv",
                    filename="a.mkv",
                    hash=HASH_A,
                ),
                make_file(
                    host="pc",
                    drive="D",
                    path="/video/b.mkv",
                    filename="b.mkv",
                    hash=HASH_A,
                ),
                make_file(
                    host="nas",
                    drive="",
                    path="/mnt/backups/a.mkv",
                    filename="a.mkv",
                    hash=HASH_A,
                ),
            ]
        )
        db_module.refresh_host_hash_stats("pc")
        db_module.refresh_host_hash_stats("nas")
        db_module.set_aggregate_meta("host_hash_stats:pc", "fresh")
        db_module.set_aggregate_meta("host_hash_stats:nas", "fresh")

        resp = client.get(
            "/files/duplicates-by-subtree-hashes",
            params={
                "hosts": "pc,nas",
                "drive": "D",
                "path_prefix": "/video",
                "scope": "context",
                "min_size": 0,
            },
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert {r["host"] for r in rows} == {"pc", "nas"}
