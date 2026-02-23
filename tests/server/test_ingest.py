"""Tests for POST /files (upsert) and POST /files/seen."""
import pytest
from tests.server.conftest import (
    NOW, HASH_A, HASH_B, client, make_file, insert_files,
)


class TestUpsertFiles:
    def test_insert_single_file(self, client):
        resp = client.post("/files", json=[make_file()])
        assert resp.status_code == 200
        assert resp.json()["upserted"] == 1

    def test_insert_multiple_files(self, client):
        records = [
            make_file(path="/users/brian/a.txt", filename="a.txt"),
            make_file(path="/users/brian/b.txt", filename="b.txt"),
            make_file(path="/users/brian/c.txt", filename="c.txt"),
        ]
        resp = client.post("/files", json=records)
        assert resp.status_code == 200
        assert resp.json()["upserted"] == 3

    def test_empty_list_returns_zero(self, client):
        resp = client.post("/files", json=[])
        assert resp.status_code == 200
        assert resp.json()["upserted"] == 0

    def test_upsert_updates_existing_record(self, client):
        original = make_file(path="/users/brian/file.txt", hash=HASH_A, size=1000)
        client.post("/files", json=[original])

        updated = make_file(
            path="/users/brian/file.txt",
            hash=HASH_B,
            size=2000,
            mtime=1700001000,
        )
        client.post("/files", json=[updated])

        # Verify update took effect via cache endpoint
        resp = client.get("/files/cache", params={"host": "mac", "root": "/users/brian"})
        files = resp.json()["files"]
        assert len(files) == 1
        assert files[0]["size_bytes"] == 2000

    def test_upsert_conflict_on_host_drive_path(self, client):
        """Inserting the same (host, drive, path) twice should not double-count."""
        record = make_file(path="/users/brian/dup.txt")
        client.post("/files", json=[record])
        client.post("/files", json=[record])

        resp = client.get("/files/ls", params={"path": "/users/brian", "host": "mac"})
        entries = resp.json()
        assert len(entries) == 1

    def test_different_hosts_same_path_stored_separately(self, client):
        mac_file = make_file(host="mac", path="/users/brian/file.txt")
        nas_file = make_file(host="nas", path="/users/brian/file.txt")
        client.post("/files", json=[mac_file, nas_file])

        mac_resp = client.get("/files/cache", params={"host": "mac", "root": "/users/brian"})
        nas_resp = client.get("/files/cache", params={"host": "nas", "root": "/users/brian"})
        assert len(mac_resp.json()["files"]) == 1
        assert len(nas_resp.json()["files"]) == 1

    def test_file_with_null_hash_accepted(self, client):
        record = make_file(hash=None, skipped_reason="volatile_active")
        resp = client.post("/files", json=[record])
        assert resp.status_code == 200
        assert resp.json()["upserted"] == 1


class TestMarkFilesSeen:
    def test_seen_updates_last_seen_at(self, client):
        insert_files([make_file(path="/users/brian/file.txt")])

        new_ts = "2025-06-01T12:00:00+00:00"
        resp = client.post("/files/seen", json={
            "host": "mac",
            "last_seen_at": new_ts,
            "paths": [{"drive": "", "path": "/users/brian/file.txt"}],
        })
        assert resp.status_code == 200
        assert resp.json()["updated"] == 1

    def test_seen_empty_paths_returns_zero(self, client):
        resp = client.post("/files/seen", json={
            "host": "mac",
            "last_seen_at": NOW,
            "paths": [],
        })
        assert resp.status_code == 200
        assert resp.json()["updated"] == 0

    def test_seen_unknown_path_updates_zero_rows(self, client):
        resp = client.post("/files/seen", json={
            "host": "mac",
            "last_seen_at": NOW,
            "paths": [{"drive": "", "path": "/nonexistent/file.txt"}],
        })
        # Should succeed without error; 0 rows updated is fine
        assert resp.status_code == 200

    def test_seen_bulk_updates_multiple_files(self, client):
        insert_files([
            make_file(path="/users/brian/a.txt", filename="a.txt"),
            make_file(path="/users/brian/b.txt", filename="b.txt"),
            make_file(path="/users/brian/c.txt", filename="c.txt"),
        ])

        resp = client.post("/files/seen", json={
            "host": "mac",
            "last_seen_at": NOW,
            "paths": [
                {"drive": "", "path": "/users/brian/a.txt"},
                {"drive": "", "path": "/users/brian/b.txt"},
                {"drive": "", "path": "/users/brian/c.txt"},
            ],
        })
        assert resp.json()["updated"] == 3
