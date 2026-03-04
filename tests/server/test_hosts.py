"""Tests for GET /hosts."""
import pytest
import server.db as db_module
from server.main import _cleanup_stale_scan_runs
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
        assert mac["total_files"] == 1   # skipped files excluded from stats
        assert mac["total_hashed"] == 1

    def test_no_files_no_scan_runs_returns_empty(self, client):
        resp = client.get("/hosts")
        assert resp.json() == []

    def test_scanning_host_with_no_files_appears(self, client):
        """A host that has a running scan but no files yet should still appear."""
        insert_scan_run(host="newhost", root_path="/data", status="running")
        resp = client.get("/hosts")
        hosts = {h["host"] for h in resp.json()}
        assert "newhost" in hosts
        newhost = next(h for h in resp.json() if h["host"] == "newhost")
        assert newhost["total_files"] == 0
        assert newhost["total_bytes"] is None
        assert newhost["is_scanning"] is True

    def test_is_scanning_false_when_no_running_scans(self, client):
        insert_files([make_file(host="mac", path="/a.txt", filename="a.txt")])
        insert_scan_run(host="mac", root_path="/", status="complete")
        resp = client.get("/hosts")
        mac = next(h for h in resp.json() if h["host"] == "mac")
        assert mac["is_scanning"] is False

    def test_is_scanning_mixed_states(self, client):
        """One host scanning, another not."""
        insert_files([
            make_file(host="mac", path="/a.txt", filename="a.txt"),
            make_file(host="nas", path="/b.txt", filename="b.txt"),
        ])
        insert_scan_run(host="mac", root_path="/", status="running")
        insert_scan_run(host="nas", root_path="/", status="complete")
        resp = client.get("/hosts")
        by_host = {h["host"]: h for h in resp.json()}
        assert by_host["mac"]["is_scanning"] is True
        assert by_host["nas"]["is_scanning"] is False

    def test_last_scan_at_populated_from_scan_runs(self, client):
        insert_files([make_file(host="mac", path="/a.txt", filename="a.txt")])
        insert_scan_run(host="mac", root_path="/", status="complete")
        resp = client.get("/hosts")
        mac = next(h for h in resp.json() if h["host"] == "mac")
        assert mac["last_scan_at"] is not None


class TestCleanupStaleScanRuns:
    def test_marks_running_as_interrupted(self):
        insert_scan_run(host="mac", root_path="/", status="running")
        insert_scan_run(host="nas", root_path="/data", status="running")
        _cleanup_stale_scan_runs()
        rows = db_module.query(
            "SELECT host, status FROM scan_runs ORDER BY host"
        )
        assert rows == [("mac", "interrupted"), ("nas", "interrupted")]

    def test_leaves_complete_and_failed_untouched(self):
        insert_scan_run(host="mac", root_path="/", status="complete")
        insert_scan_run(host="nas", root_path="/data", status="failed")
        _cleanup_stale_scan_runs()
        rows = db_module.query(
            "SELECT host, status FROM scan_runs ORDER BY host"
        )
        assert rows == [("mac", "complete"), ("nas", "failed")]

    def test_noop_when_no_running_scans(self):
        """No error when scan_runs table is empty."""
        _cleanup_stale_scan_runs()
        rows = db_module.query("SELECT count(*) FROM scan_runs")
        assert rows == [(0,)]
