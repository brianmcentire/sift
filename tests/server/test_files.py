"""Tests for GET /files (search / filter)."""
import pytest
from tests.server.conftest import (
    NOW, HASH_A, HASH_B, HASH_C, HASH_D, client, make_file, insert_files,
)


class TestListFiles:
    def test_returns_all_files_without_filters(self, client):
        insert_files([
            make_file(host="mac", path="/users/brian/a.txt", filename="a.txt", hash=HASH_A),
            make_file(host="nas", path="/mnt/b.txt", filename="b.txt", hash=HASH_B),
        ])
        resp = client.get("/files")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_host_filter(self, client):
        insert_files([
            make_file(host="mac", path="/users/brian/a.txt", filename="a.txt"),
            make_file(host="nas", path="/mnt/b.txt", filename="b.txt"),
        ])
        resp = client.get("/files", params={"host": "mac"})
        results = resp.json()
        assert all(r["host"] == "mac" for r in results)
        assert len(results) == 1

    def test_hash_filter_returns_all_copies(self, client):
        """Searching by hash should find copies on all hosts."""
        insert_files([
            make_file(host="mac", path="/users/brian/photo.jpg", filename="photo.jpg", hash=HASH_C),
            make_file(host="nas", path="/mnt/backup/photo.jpg", filename="photo.jpg", hash=HASH_C),
            make_file(host="mac", path="/users/brian/other.pdf", filename="other.pdf", hash=HASH_B),
        ])
        resp = client.get("/files", params={"hash": HASH_C})
        results = resp.json()
        assert len(results) == 2
        assert all(r["hash"] == HASH_C for r in results)

    def test_hash_prefix_not_matched(self, client):
        """Hash filter is exact match, not prefix."""
        insert_files([make_file(hash=HASH_A)])
        resp = client.get("/files", params={"hash": HASH_A[:8]})
        # Partial hash should not match
        assert len(resp.json()) == 0

    def test_path_prefix_filter(self, client):
        insert_files([
            make_file(path="/users/brian/docs/a.pdf", filename="a.pdf"),
            make_file(path="/users/brian/music/song.mp3", filename="song.mp3"),
            make_file(path="/tmp/cache.tmp", filename="cache.tmp"),
        ])
        resp = client.get("/files", params={"path_prefix": "/users/brian/docs"})
        results = resp.json()
        assert len(results) == 1
        assert results[0]["filename"] == "a.pdf"

    def test_path_prefix_no_false_match_on_similar_prefix(self, client):
        """
        /users/brian2 must NOT appear when filtering by path_prefix=/users/brian.
        """
        insert_files([
            make_file(host="mac", path="/users/brian/file.txt", filename="file.txt"),
            make_file(host="mac", path="/users/brian2/file.txt", filename="file.txt",
                      hash=HASH_B),
        ])
        resp = client.get("/files", params={"path_prefix": "/users/brian"})
        paths = [r["path_display"] for r in resp.json()]
        assert not any("brian2" in p for p in paths)

    def test_iname_filter_case_insensitive(self, client):
        insert_files([
            make_file(path="/users/brian/Photo.JPG", filename="Photo.JPG"),
            make_file(path="/users/brian/document.pdf", filename="document.pdf", hash=HASH_B),
        ])
        resp = client.get("/files", params={"iname": "*photo*"})
        results = resp.json()
        assert len(results) == 1
        assert results[0]["filename"] == "Photo.JPG"

    def test_iname_glob_wildcard(self, client):
        insert_files([
            make_file(path="/a/report_2024.pdf", filename="report_2024.pdf"),
            make_file(path="/a/report_2025.pdf", filename="report_2025.pdf", hash=HASH_B),
            make_file(path="/a/notes.txt", filename="notes.txt", hash=HASH_C),
        ])
        resp = client.get("/files", params={"iname": "report_*.pdf"})
        assert len(resp.json()) == 2

    def test_category_filter(self, client):
        insert_files([
            make_file(path="/a/photo.jpg", filename="photo.jpg", category="image"),
            make_file(path="/a/song.mp3", filename="song.mp3", category="audio", hash=HASH_B),
            make_file(path="/a/doc.pdf", filename="doc.pdf", category="document", hash=HASH_C),
        ])
        resp = client.get("/files", params={"category": "image"})
        results = resp.json()
        assert len(results) == 1
        assert results[0]["file_category"] == "image"

    def test_limit_respected(self, client):
        insert_files([
            make_file(path=f"/a/file{i}.txt", filename=f"file{i}.txt",
                      hash="a" * 63 + str(i))
            for i in range(10)
        ])
        resp = client.get("/files", params={"limit": 3})
        assert len(resp.json()) == 3

    def test_other_hosts_populated_for_cross_host_dup(self, client):
        """other_hosts lists hosts that have the same hash."""
        insert_files([
            make_file(host="mac", path="/users/brian/photo.jpg", filename="photo.jpg", hash=HASH_C),
            make_file(host="nas", path="/mnt/photo.jpg", filename="photo.jpg", hash=HASH_C),
        ])
        resp = client.get("/files", params={"host": "mac"})
        results = resp.json()
        assert len(results) == 1
        assert results[0]["other_hosts"] == "nas"

    def test_other_hosts_null_for_unique_file(self, client):
        insert_files([make_file(host="mac", path="/users/brian/unique.txt", hash=HASH_B)])
        resp = client.get("/files", params={"host": "mac"})
        assert resp.json()[0]["other_hosts"] is None

    def test_min_size_filter(self, client):
        insert_files([
            make_file(path="/a/small.txt", filename="small.txt", size=100),
            make_file(path="/a/large.txt", filename="large.txt", size=10000, hash=HASH_B),
        ])
        resp = client.get("/files", params={"min_size": 1000})
        assert len(resp.json()) == 1
        assert resp.json()[0]["size_bytes"] == 10000

    def test_max_size_filter(self, client):
        insert_files([
            make_file(path="/a/small.txt", filename="small.txt", size=100),
            make_file(path="/a/large.txt", filename="large.txt", size=10000, hash=HASH_B),
        ])
        resp = client.get("/files", params={"max_size": 1000})
        assert len(resp.json()) == 1
        assert resp.json()[0]["size_bytes"] == 100
