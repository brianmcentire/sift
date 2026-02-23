"""Tests for GET /stats/overview and GET /stats/duplicates."""
import pytest
from tests.server.conftest import (
    NOW, HASH_A, HASH_B, HASH_C, HASH_D,
    client, make_file, insert_files,
)


class TestStatsOverview:
    def test_empty_db_returns_zeros(self, client):
        resp = client.get("/stats/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_files"] == 0
        assert data["total_hosts"] == 0
        assert data["unique_hashes"] == 0
        assert data["duplicate_sets"] == 0

    def test_total_files(self, client):
        insert_files([
            make_file(path="/a.txt", filename="a.txt", hash=HASH_A),
            make_file(path="/b.txt", filename="b.txt", hash=HASH_B),
            make_file(path="/c.txt", filename="c.txt", hash=HASH_C),
        ])
        resp = client.get("/stats/overview")
        assert resp.json()["total_files"] == 3

    def test_total_hosts(self, client):
        insert_files([
            make_file(host="mac", path="/a.txt", filename="a.txt"),
            make_file(host="nas", path="/a.txt", filename="a.txt"),
            make_file(host="pi", path="/a.txt", filename="a.txt"),
        ])
        resp = client.get("/stats/overview")
        assert resp.json()["total_hosts"] == 3

    def test_unique_hashes_counts_distinct_non_null(self, client):
        insert_files([
            make_file(path="/a.txt", filename="a.txt", hash=HASH_A),
            make_file(path="/b.txt", filename="b.txt", hash=HASH_A),  # same hash
            make_file(path="/c.txt", filename="c.txt", hash=HASH_B),
            make_file(path="/d.txt", filename="d.txt", hash=None, skipped_reason="volatile_active"),
        ])
        resp = client.get("/stats/overview")
        # 4 files, 2 distinct non-null hashes
        assert resp.json()["unique_hashes"] == 2

    def test_duplicate_sets(self, client):
        insert_files([
            # Set 1: HASH_A appears twice
            make_file(path="/a1.txt", filename="a1.txt", hash=HASH_A),
            make_file(path="/a2.txt", filename="a2.txt", hash=HASH_A),
            # Set 2: HASH_B appears three times
            make_file(path="/b1.txt", filename="b1.txt", hash=HASH_B),
            make_file(path="/b2.txt", filename="b2.txt", hash=HASH_B),
            make_file(path="/b3.txt", filename="b3.txt", hash=HASH_B),
            # Unique: HASH_C appears once
            make_file(path="/c.txt", filename="c.txt", hash=HASH_C),
        ])
        resp = client.get("/stats/overview")
        assert resp.json()["duplicate_sets"] == 2

    def test_wasted_bytes(self, client):
        """
        wasted_bytes = sum over dup sets of (copies - 1) * size.
        HASH_A: 2 copies × 1000 bytes → 1000 wasted
        HASH_B: 3 copies × 500 bytes  → 1000 wasted
        Total: 2000 wasted
        """
        insert_files([
            make_file(path="/a1.txt", filename="a1.txt", hash=HASH_A, size=1000),
            make_file(path="/a2.txt", filename="a2.txt", hash=HASH_A, size=1000),
            make_file(path="/b1.txt", filename="b1.txt", hash=HASH_B, size=500),
            make_file(path="/b2.txt", filename="b2.txt", hash=HASH_B, size=500),
            make_file(path="/b3.txt", filename="b3.txt", hash=HASH_B, size=500),
        ])
        resp = client.get("/stats/overview")
        assert resp.json()["wasted_bytes"] == 2000

    def test_total_bytes(self, client):
        insert_files([
            make_file(path="/a.txt", filename="a.txt", size=100),
            make_file(path="/b.txt", filename="b.txt", size=200, hash=HASH_B),
        ])
        resp = client.get("/stats/overview")
        assert resp.json()["total_bytes"] == 300

    def test_duplicate_sets_leq_unique_hashes(self, client):
        """Invariant: duplicate_sets <= unique_hashes."""
        insert_files([
            make_file(path="/a1.txt", filename="a1.txt", hash=HASH_A),
            make_file(path="/a2.txt", filename="a2.txt", hash=HASH_A),
            make_file(path="/b.txt", filename="b.txt", hash=HASH_B),
        ])
        data = client.get("/stats/overview").json()
        assert data["duplicate_sets"] <= data["unique_hashes"]


class TestStatsDuplicates:
    def test_returns_duplicate_sets(self, client):
        insert_files([
            make_file(path="/a1.txt", filename="a1.txt", hash=HASH_A),
            make_file(path="/a2.txt", filename="a2.txt", hash=HASH_A),
        ])
        resp = client.get("/stats/duplicates")
        assert resp.status_code == 200
        sets = resp.json()
        assert len(sets) == 1
        assert sets[0]["hash"] == HASH_A
        assert sets[0]["copy_count"] == 2

    def test_unique_file_not_in_duplicates(self, client):
        insert_files([make_file(path="/unique.txt", filename="unique.txt", hash=HASH_B)])
        resp = client.get("/stats/duplicates")
        assert resp.json() == []

    def test_locations_populated(self, client):
        insert_files([
            make_file(host="mac", path="/users/brian/photo.jpg",
                      filename="photo.jpg", hash=HASH_A),
            make_file(host="nas", path="/mnt/photo.jpg",
                      filename="photo.jpg", hash=HASH_A),
        ])
        resp = client.get("/stats/duplicates")
        sets = resp.json()
        assert len(sets) == 1
        locations = sets[0]["locations"]
        assert len(locations) == 2
        hosts_in_locs = {l["host"] for l in locations}
        assert hosts_in_locs == {"mac", "nas"}

    def test_wasted_bytes_per_set(self, client):
        """3 copies of a 1000-byte file: wasted = 2 × 1000 = 2000."""
        insert_files([
            make_file(path="/a1.txt", filename="a1.txt", hash=HASH_C, size=1000),
            make_file(path="/a2.txt", filename="a2.txt", hash=HASH_C, size=1000),
            make_file(path="/a3.txt", filename="a3.txt", hash=HASH_C, size=1000),
        ])
        resp = client.get("/stats/duplicates")
        sets = resp.json()
        assert sets[0]["wasted_bytes"] == 2000

    def test_sorted_by_wasted_bytes_descending(self, client):
        """Most wasteful sets come first."""
        insert_files([
            # Set A: 2 copies × 100 bytes = 100 wasted
            make_file(path="/small1.txt", filename="small1.txt", hash=HASH_A, size=100),
            make_file(path="/small2.txt", filename="small2.txt", hash=HASH_A, size=100),
            # Set B: 2 copies × 9999 bytes = 9999 wasted
            make_file(path="/big1.txt", filename="big1.txt", hash=HASH_B, size=9999),
            make_file(path="/big2.txt", filename="big2.txt", hash=HASH_B, size=9999),
        ])
        resp = client.get("/stats/duplicates")
        sets = resp.json()
        assert sets[0]["hash"] == HASH_B  # most wasteful first
        assert sets[1]["hash"] == HASH_A

    def test_min_copies_filter(self, client):
        insert_files([
            make_file(path="/a1.txt", filename="a1.txt", hash=HASH_A),
            make_file(path="/a2.txt", filename="a2.txt", hash=HASH_A),
            make_file(path="/b1.txt", filename="b1.txt", hash=HASH_B),
            make_file(path="/b2.txt", filename="b2.txt", hash=HASH_B),
            make_file(path="/b3.txt", filename="b3.txt", hash=HASH_B),
        ])
        # Only sets with 3+ copies
        resp = client.get("/stats/duplicates", params={"min_copies": 3})
        sets = resp.json()
        assert all(s["copy_count"] >= 3 for s in sets)
        assert len(sets) == 1
        assert sets[0]["hash"] == HASH_B

    def test_limit_and_offset(self, client):
        insert_files([
            make_file(path="/a1.txt", filename="a1.txt", hash=HASH_A, size=3000),
            make_file(path="/a2.txt", filename="a2.txt", hash=HASH_A, size=3000),
            make_file(path="/b1.txt", filename="b1.txt", hash=HASH_B, size=2000),
            make_file(path="/b2.txt", filename="b2.txt", hash=HASH_B, size=2000),
            make_file(path="/c1.txt", filename="c1.txt", hash=HASH_C, size=1000),
            make_file(path="/c2.txt", filename="c2.txt", hash=HASH_C, size=1000),
        ])
        page1 = client.get("/stats/duplicates", params={"limit": 2, "offset": 0}).json()
        page2 = client.get("/stats/duplicates", params={"limit": 2, "offset": 2}).json()
        assert len(page1) == 2
        assert len(page2) == 1
        # No overlap
        hashes1 = {s["hash"] for s in page1}
        hashes2 = {s["hash"] for s in page2}
        assert hashes1.isdisjoint(hashes2)
