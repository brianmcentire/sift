"""Tests for POST/PATCH/GET /scan-runs."""
import pytest
from tests.server.conftest import NOW, client, insert_scan_run


class TestCreateScanRun:
    def test_create_returns_id(self, client):
        resp = client.post("/scan-runs", json={
            "host": "mac",
            "root_path": "/",
            "started_at": NOW,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert isinstance(data["id"], int)
        assert data["id"] > 0

    def test_create_multiple_different_ids(self, client):
        r1 = client.post("/scan-runs", json={"host": "mac", "root_path": "/", "started_at": NOW})
        r2 = client.post("/scan-runs", json={"host": "nas", "root_path": "/mnt", "started_at": NOW})
        assert r1.json()["id"] != r2.json()["id"]

    def test_create_abandons_prior_running_scan(self, client):
        """Starting a new scan for the same host+path marks any 'running' scan as 'failed'."""
        r1 = client.post("/scan-runs", json={"host": "mac", "root_path": "/", "started_at": NOW})
        id1 = r1.json()["id"]

        # Second scan for same host+path
        client.post("/scan-runs", json={"host": "mac", "root_path": "/", "started_at": NOW})

        # The first scan run should now be 'failed'
        resp = client.get("/scan-runs", params={"host": "mac"})
        runs = resp.json()
        run1 = next(r for r in runs if r["id"] == id1)
        assert run1["status"] == "failed"

    def test_create_different_root_path_not_abandoned(self, client):
        """Scans for different root paths are independent."""
        r1 = client.post("/scan-runs", json={"host": "mac", "root_path": "/", "started_at": NOW})
        id1 = r1.json()["id"]

        # Scan for a different path — should NOT abandon id1
        client.post("/scan-runs", json={"host": "mac", "root_path": "/Users", "started_at": NOW})

        resp = client.get("/scan-runs", params={"host": "mac"})
        runs = resp.json()
        run1 = next(r for r in runs if r["id"] == id1)
        assert run1["status"] == "running"


class TestPatchScanRun:
    def test_patch_complete(self, client):
        run_id = insert_scan_run(status="running")
        resp = client.patch(f"/scan-runs/{run_id}", json={"status": "complete"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_patch_failed(self, client):
        run_id = insert_scan_run(status="running")
        resp = client.patch(f"/scan-runs/{run_id}", json={"status": "failed"})
        assert resp.status_code == 200

    def test_patch_invalid_status_rejected(self, client):
        run_id = insert_scan_run(status="running")
        resp = client.patch(f"/scan-runs/{run_id}", json={"status": "bogus"})
        assert resp.status_code == 400


class TestListScanRuns:
    def test_list_returns_all(self, client):
        insert_scan_run(host="mac", root_path="/")
        insert_scan_run(host="nas", root_path="/mnt")
        resp = client.get("/scan-runs")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_filtered_by_host(self, client):
        insert_scan_run(host="mac", root_path="/")
        insert_scan_run(host="nas", root_path="/mnt")
        resp = client.get("/scan-runs", params={"host": "mac"})
        runs = resp.json()
        assert all(r["host"] == "mac" for r in runs)
        assert len(runs) == 1

    def test_list_ordered_newest_first(self, client):
        id1 = insert_scan_run(host="mac", root_path="/a")
        id2 = insert_scan_run(host="mac", root_path="/b")
        resp = client.get("/scan-runs")
        ids = [r["id"] for r in resp.json()]
        assert ids.index(id2) < ids.index(id1)
