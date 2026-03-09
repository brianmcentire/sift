"""Tests for report-focused stats endpoints."""

import server.db as db_module
import server.main as main_module
from tests.server.conftest import (
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    HASH_E,
    client,
    insert_files,
    make_file,
)


def _refresh_dup_aggregates(hosts: list[str]) -> None:
    for host in hosts:
        db_module.refresh_host_hash_stats(host)
        db_module.set_aggregate_meta(f"host_hash_stats:{host}", "fresh")


def test_report_duplicates_returns_pending_when_aggregates_not_fresh(client):
    insert_files(
        [
            make_file(host="mac", path="/a.txt", filename="a.txt", hash=HASH_A),
            make_file(host="mac", path="/b.txt", filename="b.txt", hash=HASH_A),
        ]
    )

    resp = client.get("/stats/report/duplicates")
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"


def test_report_duplicate_union_scope_and_host_only_semantics(client):
    insert_files(
        [
            make_file(
                host="mac", path="/m/a1.txt", filename="a1.txt", hash=HASH_A, size=100
            ),
            make_file(
                host="mac", path="/m/a2.txt", filename="a2.txt", hash=HASH_A, size=100
            ),
            make_file(
                host="mac", path="/m/b1.txt", filename="b1.txt", hash=HASH_B, size=200
            ),
            make_file(
                host="nas", path="/n/b2.txt", filename="b2.txt", hash=HASH_B, size=200
            ),
            make_file(
                host="nas", path="/n/b3.txt", filename="b3.txt", hash=HASH_B, size=200
            ),
            make_file(
                host="mac", path="/m/c1.txt", filename="c1.txt", hash=HASH_C, size=300
            ),
            make_file(
                host="mac", path="/m/c2.txt", filename="c2.txt", hash=HASH_C, size=300
            ),
            make_file(
                host="nas", path="/n/c3.txt", filename="c3.txt", hash=HASH_C, size=300
            ),
            make_file(
                host="mac", path="/m/d1.txt", filename="d1.txt", hash=HASH_D, size=400
            ),
            make_file(
                host="nas", path="/n/d2.txt", filename="d2.txt", hash=HASH_D, size=400
            ),
            make_file(
                host="pi", path="/p/e1.txt", filename="e1.txt", hash=HASH_E, size=50
            ),
        ]
    )
    _refresh_dup_aggregates(["mac", "nas", "pi"])

    resp = client.get("/stats/report/duplicates")
    assert resp.status_code == 200
    body = resp.json()

    g = body["global_summary"]
    assert g["uniq_dup_hashes"] == 3
    assert g["extra_copies"] == 5
    assert g["extra_bytes"] == 1100
    assert g["gross_duplicate_bytes"] == 1700

    cross = body["cross_host_summary"]
    assert cross["qualifying_uniq_dup_hashes"] == 2
    assert cross["qualifying_file_copies"] == 6
    assert cross["extra_copies"] == 4
    assert cross["extra_bytes"] == 1000
    assert cross["gross_duplicate_bytes"] == 1500

    host_rows = {r["host"]: r for r in body["host_only_rows"]}
    assert host_rows["mac"]["uniq_dup_hashes"] == 2
    assert host_rows["mac"]["extra_copies"] == 2
    assert host_rows["mac"]["extra_bytes"] == 400
    assert host_rows["nas"]["uniq_dup_hashes"] == 1
    assert host_rows["nas"]["extra_copies"] == 1
    assert host_rows["nas"]["extra_bytes"] == 200
    assert host_rows["pi"]["uniq_dup_hashes"] == 0
    assert host_rows["pi"]["extra_copies"] == 0
    assert host_rows["pi"]["extra_bytes"] == 0

    tops = body["top_opportunities"]
    assert [r["extra_bytes"] for r in tops[:3]] == [600, 400, 100]


def test_report_tombstones_summary(client):
    old = "2025-01-01T00:00:00+00:00"
    complete = "2025-01-15T00:00:00+00:00"

    insert_files(
        [
            make_file(host="mac", path="/r/a.txt", filename="a.txt", size=10),
            make_file(host="nas", path="/r/b.txt", filename="b.txt", size=20),
            make_file(host="nas", path="/r/c.txt", filename="c.txt", size=30),
        ]
    )
    db_module.execute(
        "UPDATE files SET last_seen_at = ? WHERE host = ? AND path = ?",
        [old, "mac", "/r/a.txt"],
    )
    db_module.execute(
        "UPDATE files SET last_seen_at = ? WHERE host = ? AND path = ?",
        [old, "nas", "/r/b.txt"],
    )
    db_module.execute(
        "INSERT INTO scan_runs (host, drive, root_path, started_at, status) VALUES (?, '', ?, ?, 'complete')",
        ["mac", "/r", complete],
    )
    db_module.execute(
        "INSERT INTO scan_runs (host, drive, root_path, started_at, status) VALUES (?, '', ?, ?, 'complete')",
        ["nas", "/r", complete],
    )

    resp = client.get("/stats/report/tombstones")
    assert resp.status_code == 200
    body = resp.json()
    assert body["eligible_tombstone_rows"] == 2
    assert body["eligible_tombstone_bytes"] == 30
    assert body["hosts_with_pressure"] == ["mac", "nas"]
    assert body["hosts_with_pressure_count"] == 2
    assert body["top_host"] == "mac"
    assert body["top_host_rows"] == 1


def test_report_clusters_shape_and_deterministic(client):
    insert_files(
        [
            make_file(path="/a", filename="a", size=0, hash=HASH_A),
            make_file(path="/b", filename="b", size=0, hash=HASH_B),
            make_file(path="/c", filename="c", size=100, hash=HASH_C),
            make_file(path="/d", filename="d", size=100, hash=HASH_D),
            make_file(path="/e", filename="e", size=10000, hash=HASH_E),
        ]
    )
    r1 = client.get("/stats/report/clusters", params={"k": 3})
    r2 = client.get("/stats/report/clusters", params={"k": 3})
    assert r1.status_code == 200
    assert r1.json() == r2.json()
    body = r1.json()
    assert body["k_target"] == 3
    assert 1 <= body["k_used"] <= 3
    assert body["total_files"] == 5
    assert sum(int(c["files"]) for c in body["clusters"]) == 5
    assert [c["name"] for c in body["clusters"]] == [
        f"C{i}" for i in range(1, len(body["clusters"]) + 1)
    ]


def test_timeout_error_payload_includes_endpoint_and_operation(client, monkeypatch):
    def boom(*args, **kwargs):
        raise db_module.DBTimeoutError(
            timeout_type="query_runtime",
            timeout_sec=300,
            endpoint="GET /stats/report/inventory",
            operation="report inventory: host totals",
            detail="DuckDB query interrupted after timeout",
            sql="SELECT ...",
        )

    monkeypatch.setattr(db_module, "query_one", boom)
    resp = client.get("/stats/report/inventory")
    assert resp.status_code == 504
    body = resp.json()
    assert body["status"] == "timeout_enforced"
    assert body["endpoint"] == "GET /stats/report/inventory"
    assert body["operation"] == "report inventory: host totals"


def test_report_clusters_fast_uses_cache(client, monkeypatch):
    insert_files(
        [
            make_file(path="/a", filename="a", size=1, hash=HASH_A),
            make_file(path="/b", filename="b", size=2, hash=HASH_B),
        ]
    )

    calls = {"n": 0}
    real = main_module._kmeans_log1p_weighted

    def wrapped(points, k_target=10):
        calls["n"] += 1
        return real(points, k_target=k_target)

    monkeypatch.setattr(main_module, "_kmeans_log1p_weighted", wrapped)

    r1 = client.get("/stats/report/clusters", params={"k": 3, "fast": True})
    r2 = client.get("/stats/report/clusters", params={"k": 3, "fast": True})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert calls["n"] == 1
