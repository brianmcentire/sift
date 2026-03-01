"""Tests for maintenance queue endpoints and execution."""

import server.db as db_module


class TestMaintenanceEndpoints:
    def test_list_jobs_returns_enqueued_job(self, client):
        added = db_module.enqueue_maintenance_job(
            "refresh_directory_index", priority=70
        )
        assert added is True

        resp = client.get("/maintenance/jobs")
        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        assert len(jobs) >= 1
        assert jobs[0]["job_type"] == "refresh_directory_index"

    def test_run_now_requires_enabled_or_force(self, client):
        db_module.enqueue_maintenance_job("refresh_directory_index", priority=70)
        resp = client.post("/maintenance/run-now")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["reason"] == "maintenance_disabled"

    def test_force_run_now_executes_pending_job(self, client):
        db_module.enqueue_maintenance_job("refresh_directory_index", priority=70)
        resp = client.post("/maintenance/run-now", params={"force": "true"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["ran"] is True

        row = db_module.query_one(
            "SELECT COUNT(*) FROM maintenance_jobs WHERE status = 'complete'"
        )
        assert row is not None
        assert row[0] == 1
