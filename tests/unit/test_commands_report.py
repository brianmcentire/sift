from types import SimpleNamespace

import pytest


def _payload(path: str):
    if path == "/hosts":
        return [{"host": "zeta"}, {"host": "alpha"}]
    if path == "/stats/report/inventory":
        return {
            "hosts_in_datastore": 3,
            "total_file_rows": 1000,
            "total_bytes": 1024 * 1024 * 1024,
            "zero_byte_files": 20,
        }
    if path == "/stats/report/duplicates":
        return {
            "global_summary": {
                "uniq_dup_hashes": 12,
                "extra_copies": 42,
                "extra_bytes": 1024,
                "gross_duplicate_bytes": 2048,
            },
            "host_only_rows": [
                {
                    "host": "zeta",
                    "uniq_dup_hashes": 1,
                    "extra_copies": 3,
                    "extra_bytes": 2048,
                    "host_total_bytes": 1024 * 1024,
                },
                {
                    "host": "alpha",
                    "uniq_dup_hashes": 2,
                    "extra_copies": 4,
                    "extra_bytes": 1024,
                    "host_total_bytes": 1024 * 512,
                },
            ],
            "cross_host_summary": {
                "qualifying_uniq_dup_hashes": 3,
                "qualifying_file_copies": 8,
                "extra_copies": 5,
                "extra_bytes": 4096,
                "gross_duplicate_bytes": 8192,
            },
            "top_opportunities": [
                {
                    "rank": 1,
                    "extra_bytes": 3000,
                    "copies": 5,
                    "hosts": 2,
                    "file_category": "video",
                    "sample_filename": "a.mkv",
                }
            ],
        }
    if path == "/stats/report/tombstones":
        return {
            "eligible_tombstone_rows": 20,
            "eligible_tombstone_bytes": 50,
            "hosts_with_pressure": ["alpha", "zeta"],
            "hosts_with_pressure_count": 2,
            "hosts_in_datastore": 3,
            "top_host": "alpha",
            "top_host_rows": 10,
        }
    if path == "/stats/report/clusters":
        return {
            "k_target": 10,
            "k_used": 2,
            "total_files": 1000,
            "clusters": [
                {
                    "name": "C1",
                    "median_size_bytes": 0,
                    "files": 20,
                    "pct_of_files": 2.0,
                },
                {
                    "name": "C2",
                    "median_size_bytes": 1024,
                    "files": 980,
                    "pct_of_files": 98.0,
                },
            ],
        }
    raise AssertionError(path)


def test_report_output_progress_and_alignment(monkeypatch, capsys):
    from sift.commands import report as report_cmd

    def fake_get(path, params=None):
        return _payload(path)

    monkeypatch.setattr(report_cmd.client, "get", fake_get)
    monkeypatch.setattr(report_cmd, "get_server_url", lambda: "http://localhost:8765")
    monkeypatch.setattr(report_cmd, "get_version", lambda: "0.9.2")

    report_cmd.cmd_report(SimpleNamespace())
    out = capsys.readouterr().out

    assert "Building report: [1/7]" in out
    assert "Building report: [7/7]" in out
    assert "Inventory Summary" in out
    assert "Host-Only Extra Copies" in out
    assert "Top Duplicate Opportunities" in out

    alpha_pos = out.find("alpha")
    zeta_pos = out.find("zeta")
    assert alpha_pos != -1 and zeta_pos != -1
    assert alpha_pos < zeta_pos

    assert "2%" in out
    assert "2.0%" not in out


def test_report_pending_exits_with_error(monkeypatch, capsys):
    from sift.commands import report as report_cmd

    def fake_get(path, params=None):
        if path == "/stats/report/inventory":
            return _payload(path)
        if path == "/hosts":
            return _payload(path)
        return {"status": "pending", "detail": "Duplicate index is still building"}

    monkeypatch.setattr(report_cmd.client, "get", fake_get)
    monkeypatch.setattr(report_cmd, "get_server_url", lambda: "http://localhost:8765")
    monkeypatch.setattr(report_cmd, "get_version", lambda: "0.9.2")

    with pytest.raises(SystemExit):
        report_cmd.cmd_report(SimpleNamespace())

    err = capsys.readouterr().err
    assert "still building" in err
