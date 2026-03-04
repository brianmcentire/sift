"""Contract tests for GET /files/ls/dup-hash."""

from tests.server.conftest import HASH_A, HASH_B, client, insert_files, make_file


class TestDupHash:
    def test_returned_hash_has_two_or_more_copies(self, client):
        insert_files(
            [
                make_file(
                    path="/users/brian/docs/a1.txt", filename="a1.txt", hash=HASH_A
                ),
                make_file(
                    path="/users/brian/docs/a2.txt", filename="a2.txt", hash=HASH_A
                ),
                make_file(
                    path="/users/brian/docs/b1.txt", filename="b1.txt", hash=HASH_B
                ),
            ]
        )
        resp = client.get(
            "/files/ls/dup-hash",
            params={"path": "/users/brian/docs", "host": "mac"},
        )
        assert resp.status_code == 200
        hash_val = resp.json()["hash"]
        copies = client.get("/files", params={"hash": hash_val, "limit": 10})
        assert copies.status_code == 200
        assert len(copies.json()) >= 2

    def test_no_duplicate_returns_404(self, client):
        insert_files(
            [
                make_file(
                    path="/users/brian/docs/a1.txt", filename="a1.txt", hash=HASH_A
                ),
                make_file(
                    path="/users/brian/docs/b1.txt", filename="b1.txt", hash=HASH_B
                ),
            ]
        )
        resp = client.get(
            "/files/ls/dup-hash",
            params={"path": "/users/brian/docs", "host": "mac"},
        )
        assert resp.status_code == 404
