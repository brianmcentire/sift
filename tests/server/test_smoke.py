"""Fast smoke checks for local/canary verification."""

import pytest

from tests.server.conftest import HASH_A, client, insert_files, make_file


pytestmark = pytest.mark.smoke


class TestSmokeEndpoints:
    def test_hosts_endpoint_returns_list(self, client):
        resp = client.get("/hosts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_client_host_endpoint_shape(self, client):
        resp = client.get("/client-host")
        assert resp.status_code == 200
        data = resp.json()
        assert "client_host" in data

    def test_stats_overview_shape_includes_freshness_fields(self, client):
        insert_files(
            [
                make_file(path="/users/brian/a.txt", filename="a.txt", hash=HASH_A),
                make_file(path="/users/brian/b.txt", filename="b.txt", hash=HASH_A),
            ]
        )
        resp = client.get("/stats/overview")
        assert resp.status_code == 200
        data = resp.json()
        for field in (
            "total_files",
            "total_hosts",
            "unique_hashes",
            "duplicate_sets",
            "wasted_bytes",
            "total_bytes",
            "aggregated_at",
            "data_freshness",
        ):
            assert field in data

    def test_tree_children_and_dup_metrics_basic_path(self, client):
        insert_files(
            [
                make_file(path="/users/brian/a.txt", filename="a.txt", hash=HASH_A),
                make_file(path="/users/brian/b.txt", filename="b.txt", hash=HASH_A),
            ]
        )
        children = client.get(
            "/tree/children", params={"path": "/users/brian", "host": "mac"}
        )
        assert children.status_code == 200
        children_data = children.json()
        assert isinstance(children_data.get("items"), list)
        assert len(children_data["items"]) == 2

        metrics = client.get(
            "/tree/dup-metrics", params={"path": "/users/brian", "host": "mac"}
        )
        assert metrics.status_code == 200
        metrics_data = metrics.json()
        assert isinstance(metrics_data.get("metrics"), dict)
