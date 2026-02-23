"""Tests for GET /hosts."""
import pytest
from tests.server.conftest import (
    NOW, HASH_A, HASH_B, client, make_file, insert_files, insert_scan_run,
)


class TestListHosts:
    def test_returns_known_hosts(self, client):
        insert_files([
            make_file(host="mac", path="/users/brian/a.txt", filename="a.txt"),
            make_file(host="nas", path="/mnt/b.txt", filename="b.txt"),
        ])
        resp = client.get("/hosts")
        assert resp.status_code == 200
        hosts = {h["host"] for h in resp.json()}
        assert "mac" in hosts
        assert "nas" in hosts

    def test_total_files_count(self, client):
        insert_files([
            make_file(host="mac", path="/a.txt", filename="a.txt"),
            make_file(host="mac", path="/b.txt", filename="b.txt", hash=HASH_B),
            make_file(host="mac", path="/c.txt", filename="c.txt", hash=HASH_A),
        ])
        resp = client.get("/hosts")
        mac = next(h for h in resp.json() if h["host"] == "mac")
        assert mac["total_files"] == 3

    def test_total_bytes_sum(self, client):
        insert_files([
            make_file(host="mac", path="/a.txt", filename="a.txt", size=1000),
            make_file(host="mac", path="/b.txt", filename="b.txt", size=2000, hash=HASH_B),
        ])
        resp = client.get("/hosts")
        mac = next(h for h in resp.json() if h["host"] == "mac")
        assert mac["total_bytes"] == 3000

    def test_total_hashed_counts_non_null_hashes(self, client):
        insert_files([
            make_file(host="mac", path="/a.txt", filename="a.txt", hash=HASH_A),
            make_file(host="mac", path="/b.txt", filename="b.txt", hash=None,
                      skipped_reason="volatile_active"),
        ])
        resp = client.get("/hosts")
        mac = next(h for h in resp.json() if h["host"] == "mac")
        assert mac["total_files"] == 2
        assert mac["total_hashed"] == 1

    def test_no_files_host_not_listed(self, client):
        resp = client.get("/hosts")
        assert resp.json() == []

    def test_last_scan_at_populated_from_scan_runs(self, client):
        insert_files([make_file(host="mac", path="/a.txt", filename="a.txt")])
        insert_scan_run(host="mac", root_path="/", status="complete")
        resp = client.get("/hosts")
        mac = next(h for h in resp.json() if h["host"] == "mac")
        assert mac["last_scan_at"] is not None
