"""Tests for GET /files/cache."""
import pytest
from tests.server.conftest import NOW, HASH_A, HASH_B, client, make_file, insert_files


class TestGetCache:
    def test_returns_files_under_root(self, client):
        insert_files([
            make_file(path="/users/brian/docs/a.pdf", filename="a.pdf"),
            make_file(path="/users/brian/docs/b.pdf", filename="b.pdf"),
        ])
        resp = client.get("/files/cache", params={"host": "mac", "root": "/users/brian"})
        assert resp.status_code == 200
        files = resp.json()["files"]
        assert len(files) == 2

    def test_root_itself_included(self, client):
        insert_files([make_file(path="/users/brian/file.txt")])
        resp = client.get("/files/cache", params={"host": "mac", "root": "/users/brian"})
        files = resp.json()["files"]
        paths = [f["path"] for f in files]
        assert "/users/brian/file.txt" in paths

    def test_files_outside_root_excluded(self, client):
        insert_files([
            make_file(path="/users/brian/file.txt", filename="file.txt"),
            make_file(path="/tmp/other.txt", filename="other.txt"),
        ])
        resp = client.get("/files/cache", params={"host": "mac", "root": "/users/brian"})
        files = resp.json()["files"]
        paths = [f["path"] for f in files]
        assert all(p.startswith("/users/brian") for p in paths)

    def test_other_host_files_excluded(self, client):
        insert_files([
            make_file(host="mac", path="/users/brian/file.txt"),
            make_file(host="nas", path="/users/brian/file.txt"),
        ])
        resp = client.get("/files/cache", params={"host": "mac", "root": "/users/brian"})
        files = resp.json()["files"]
        assert len(files) == 1

    def test_response_includes_mtime_and_size(self, client):
        insert_files([make_file(path="/users/brian/file.txt", size=4096, mtime=1700000000)])
        resp = client.get("/files/cache", params={"host": "mac", "root": "/users/brian"})
        f = resp.json()["files"][0]
        assert f["mtime"] == 1700000000
        assert f["size_bytes"] == 4096

    def test_empty_root_returns_empty(self, client):
        resp = client.get("/files/cache", params={"host": "mac", "root": "/users/nobody"})
        assert resp.json()["files"] == []

    def test_prefix_not_matched_without_slash_separator(self, client):
        """
        /users/brian2 should NOT match when root=/users/brian.
        The LIKE uses path LIKE root || '/%' so the slash acts as a separator.
        """
        insert_files([
            make_file(path="/users/brian/file.txt", filename="file.txt"),
            make_file(path="/users/brian2/file.txt", filename="file.txt",
                      host="mac"),
        ])
        resp = client.get("/files/cache", params={"host": "mac", "root": "/users/brian"})
        files = resp.json()["files"]
        paths = [f["path"] for f in files]
        assert all(p.startswith("/users/brian/") or p == "/users/brian" for p in paths)
        assert not any(p.startswith("/users/brian2") for p in paths)
