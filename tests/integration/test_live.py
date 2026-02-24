"""
Integration (sanity) tests against the live Unraid server.

These tests do NOT assert exact counts — the data changes between scans.
Instead they assert mathematical invariants that must ALWAYS hold regardless
of data content.  A failing invariant means there is a bug in the server.

Run with:
    SIFT_TEST_SERVER=http://your-sift-server:8765 pytest -m integration -v
"""
import pytest
from tests.integration.conftest import live_client, get


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# /hosts
# ---------------------------------------------------------------------------

class TestLiveHosts:
    def test_returns_at_least_one_host(self, live_client):
        hosts = get(live_client, "/hosts")
        assert len(hosts) >= 1, "Expected at least one scanned host"

    def test_each_host_has_positive_file_count(self, live_client):
        hosts = get(live_client, "/hosts")
        for h in hosts:
            assert h["total_files"] > 0, f"Host {h['host']} has 0 files"

    def test_total_hashed_leq_total_files(self, live_client):
        for h in get(live_client, "/hosts"):
            assert h["total_hashed"] <= h["total_files"], (
                f"Host {h['host']}: total_hashed ({h['total_hashed']}) "
                f"> total_files ({h['total_files']})"
            )

    def test_total_bytes_non_negative(self, live_client):
        for h in get(live_client, "/hosts"):
            if h["total_bytes"] is not None:
                assert h["total_bytes"] >= 0, f"Host {h['host']} has negative total_bytes"


# ---------------------------------------------------------------------------
# /stats/overview
# ---------------------------------------------------------------------------

class TestLiveStats:
    def test_overview_returns_expected_fields(self, live_client):
        stats = get(live_client, "/stats/overview")
        for field in ("total_files", "total_hosts", "unique_hashes",
                      "duplicate_sets", "wasted_bytes", "total_bytes"):
            assert field in stats, f"Missing field: {field}"

    def test_total_files_positive(self, live_client):
        stats = get(live_client, "/stats/overview")
        assert stats["total_files"] > 0

    def test_unique_hashes_leq_total_files(self, live_client):
        stats = get(live_client, "/stats/overview")
        assert stats["unique_hashes"] <= stats["total_files"]

    def test_duplicate_sets_leq_unique_hashes(self, live_client):
        stats = get(live_client, "/stats/overview")
        assert stats["duplicate_sets"] <= stats["unique_hashes"]

    def test_wasted_bytes_non_negative(self, live_client):
        stats = get(live_client, "/stats/overview")
        if stats["wasted_bytes"] is not None:
            assert stats["wasted_bytes"] >= 0

    def test_total_hosts_matches_hosts_endpoint(self, live_client):
        stats = get(live_client, "/stats/overview")
        hosts = get(live_client, "/hosts")
        assert stats["total_hosts"] == len(hosts)


# ---------------------------------------------------------------------------
# /files/ls — per-host, starting from root
# ---------------------------------------------------------------------------

class TestLiveLs:
    def test_root_ls_returns_entries_for_each_host(self, live_client):
        hosts = get(live_client, "/hosts")
        for h in hosts:
            entries = get(live_client, "/files/ls", path="/", host=h["host"])
            assert len(entries) > 0, f"Root ls for host {h['host']} returned nothing"

    def test_entry_types_are_valid(self, live_client):
        hosts = get(live_client, "/hosts")
        for h in hosts[:2]:  # limit to first 2 hosts to keep runtime short
            entries = get(live_client, "/files/ls", path="/", host=h["host"])
            for e in entries:
                assert e["entry_type"] in ("file", "dir"), (
                    f"Unknown entry_type '{e['entry_type']}' for host {h['host']}"
                )

    def test_dup_count_leq_file_count(self, live_client):
        """
        Invariant: dup_count cannot exceed file_count for any entry.
        This would mean more 'duplicate' files than files, which is impossible.
        """
        hosts = get(live_client, "/hosts")
        for h in hosts[:2]:
            entries = get(live_client, "/files/ls", path="/", host=h["host"])
            for e in entries:
                assert e["dup_count"] <= e["file_count"], (
                    f"Host {h['host']} segment '{e['segment']}': "
                    f"dup_count={e['dup_count']} > file_count={e['file_count']}"
                )

    def test_dup_hash_count_leq_dup_count(self, live_client):
        """
        Invariant: dup_hash_count <= dup_count.
        You can't have more distinct dup-hashes than dup-files.
        """
        hosts = get(live_client, "/hosts")
        for h in hosts[:2]:
            entries = get(live_client, "/files/ls", path="/", host=h["host"])
            for e in entries:
                assert e["dup_hash_count"] <= e["dup_count"], (
                    f"Host {h['host']} segment '{e['segment']}': "
                    f"dup_hash_count={e['dup_hash_count']} > dup_count={e['dup_count']}"
                )

    def test_extra_copies_non_negative(self, live_client):
        """
        Invariant: dup_count - dup_hash_count >= 0 for every entry.
        This is what the UI shows as 'X extra copies'.
        A negative value would indicate a bug.
        """
        hosts = get(live_client, "/hosts")
        for h in hosts:
            entries = get(live_client, "/files/ls", path="/", host=h["host"])
            for e in entries:
                extra = e["dup_count"] - e["dup_hash_count"]
                assert extra >= 0, (
                    f"Host {h['host']} segment '{e['segment']}': "
                    f"extra_copies={extra} (negative!)"
                )

    def test_file_entries_dup_count_is_zero_or_one(self, live_client):
        """
        For a leaf file entry, dup_count is 0 (not a dup) or 1 (is a dup).
        It can never be > 1 because there's exactly one file in the group.
        """
        hosts = get(live_client, "/hosts")
        host = hosts[0]["host"]
        entries = get(live_client, "/files/ls", path="/", host=host)
        for e in entries:
            if e["entry_type"] == "file":
                assert e["dup_count"] in (0, 1), (
                    f"File entry '{e['segment']}': dup_count={e['dup_count']} (expected 0 or 1)"
                )

    def test_total_bytes_non_negative(self, live_client):
        hosts = get(live_client, "/hosts")
        for h in hosts[:2]:
            entries = get(live_client, "/files/ls", path="/", host=h["host"])
            for e in entries:
                if e["total_bytes"] is not None:
                    assert e["total_bytes"] >= 0

    def test_cross_host_dup_not_in_dup_count_spot_check(self, live_client):
        """
        For each host, spot-check: for any FILE entry with dup_count=0,
        if other_hosts is non-null, that's correct cross-host info in the right field.
        For any FILE entry with dup_count=1, it should have a same-host counterpart
        — we can't easily verify this at the root level without drilling in,
        but we check the dup_count=1 entries also appear via /files?hash=<hash>.
        """
        hosts = get(live_client, "/hosts")
        host = hosts[0]["host"]
        entries = get(live_client, "/files/ls", path="/", host=host)
        file_entries = [e for e in entries if e["entry_type"] == "file" and e.get("hash")]

        for e in file_entries[:5]:  # spot-check first 5 file entries
            if e["dup_count"] == 1:
                # Verify the hash truly appears more than once
                copies = get(live_client, "/files", hash=e["hash"], limit=10)
                assert len(copies) >= 2, (
                    f"Host {host} file '{e['segment']}' has dup_count=1 "
                    f"but /files?hash=... returned only {len(copies)} copy"
                )


# ---------------------------------------------------------------------------
# /files (search)
# ---------------------------------------------------------------------------

class TestLiveFiles:
    def test_hash_search_returns_results(self, live_client):
        """Find a known-duplicate hash and confirm /files?hash= works."""
        dups = get(live_client, "/stats/duplicates", limit=1)
        if not dups:
            pytest.skip("No duplicates in database — cannot test hash search")
        known_hash = dups[0]["hash"]
        results = get(live_client, "/files", hash=known_hash, limit=50)
        assert len(results) >= 2, "Expected at least 2 copies of a duplicate file"

    def test_all_results_have_required_fields(self, live_client):
        results = get(live_client, "/files", limit=20)
        for r in results:
            for field in ("host", "drive", "path_display", "filename",
                          "ext", "file_category", "size_bytes"):
                assert field in r, f"Missing field '{field}' in /files result"

    def test_size_bytes_non_negative(self, live_client):
        results = get(live_client, "/files", limit=100)
        for r in results:
            if r["size_bytes"] is not None:
                assert r["size_bytes"] >= 0

    def test_iname_search_returns_results(self, live_client):
        results = get(live_client, "/files", iname="*.jpg", limit=10)
        # If there are any jpg files, all results should be jpg
        for r in results:
            assert r["ext"].lower() == "jpg", (
                f"iname=*.jpg returned non-jpg file: {r['filename']}"
            )


# ---------------------------------------------------------------------------
# /stats/duplicates
# ---------------------------------------------------------------------------

class TestLiveDuplicates:
    def test_duplicate_sets_have_copy_count_gte_2(self, live_client):
        sets = get(live_client, "/stats/duplicates", limit=50)
        for s in sets:
            assert s["copy_count"] >= 2, (
                f"Duplicate set {s['hash'][:8]}... has copy_count={s['copy_count']}"
            )

    def test_wasted_bytes_consistent_with_copy_count(self, live_client):
        """
        For each dup set: wasted_bytes = (copy_count - 1) * size_bytes
        (assuming all copies have equal size, which is true for same-content files).
        """
        sets = get(live_client, "/stats/duplicates", limit=20)
        for s in sets:
            if s["wasted_bytes"] is not None and s["size_bytes"] is not None:
                expected = (s["copy_count"] - 1) * s["size_bytes"]
                assert s["wasted_bytes"] == expected, (
                    f"wasted_bytes mismatch for {s['hash'][:8]}: "
                    f"got {s['wasted_bytes']}, expected {expected}"
                )

    def test_locations_count_matches_copy_count(self, live_client):
        sets = get(live_client, "/stats/duplicates", limit=10)
        for s in sets:
            assert len(s["locations"]) == s["copy_count"], (
                f"Hash {s['hash'][:8]}: copy_count={s['copy_count']} "
                f"but len(locations)={len(s['locations'])}"
            )


# ---------------------------------------------------------------------------
# /files/ls/dup-hash — "1 extra copy" click feature
# ---------------------------------------------------------------------------

def _find_one_extra_copy_dir(live_client, path, host, max_depth=4, _visited=None):
    """Walk the tree to find the first directory where dup_count - dup_hash_count == 1."""
    if _visited is None:
        _visited = set()
    if path in _visited:
        return None
    _visited.add(path)
    try:
        entries = get(live_client, "/files/ls", path=path, host=host)
    except Exception:
        return None
    for e in entries:
        if e["entry_type"] != "dir":
            continue
        full = ("/" + e["segment"]) if path == "/" else (path + "/" + e["segment"])
        if (e["dup_count"] - e["dup_hash_count"]) == 1:
            return full
        if max_depth > 0 and e["dup_count"] > 0:
            result = _find_one_extra_copy_dir(live_client, full, host, max_depth - 1, _visited)
            if result:
                return result
    return None


class TestLiveDupHash:
    def test_dup_hash_returns_findable_hash(self, live_client):
        """
        Core invariant: when /files/ls/dup-hash returns a hash for a directory,
        that hash must appear >= 2 times in /files?hash=X.

        Regression test for the bug where clicking '1 extra copy' opened the
        hash overlay showing '0 results / No files found'.
        """
        hosts = get(live_client, "/hosts")
        host = hosts[0]["host"]

        dir_path = _find_one_extra_copy_dir(live_client, "/", host, max_depth=4)
        if dir_path is None:
            pytest.skip("No directory with exactly 1 extra copy found — cannot test")

        result = get(live_client, "/files/ls/dup-hash", path=dir_path, host=host)
        assert "hash" in result, f"Expected {{hash: ...}}, got {result}"
        hash_val = result["hash"]
        assert hash_val, "hash should be non-empty"

        copies = get(live_client, "/files", hash=hash_val, limit=10)
        assert len(copies) >= 2, (
            f"/files/ls/dup-hash for {dir_path} returned hash {hash_val[:8]}... "
            f"but /files?hash=... found only {len(copies)} "
            f"cop{'y' if len(copies) == 1 else 'ies'} (expected >= 2)"
        )

    def test_dup_hash_404_for_no_dup_dir(self, live_client):

        """
        A directory with no same-host duplicates should return 404,
        not a spurious hash.
        """
        hosts = get(live_client, "/hosts")
        host = hosts[0]["host"]

        entries = get(live_client, "/files/ls", path="/", host=host)
        no_dup = next(
            (e for e in entries if e["entry_type"] == "dir" and e["dup_count"] == 0),
            None,
        )
        if no_dup is None:
            pytest.skip("Every root-level directory has duplicates — cannot test 404 case")

        path = "/" + no_dup["segment"]
        r = live_client.get(
            f"{live_client.base_url}/files/ls/dup-hash",
            params={"path": path, "host": host},
            timeout=30,
        )
        assert r.status_code == 404, (
            f"Expected 404 for no-dup dir {path}, got {r.status_code}: {r.text}"
        )


# ---------------------------------------------------------------------------
# /directories — directory search
# ---------------------------------------------------------------------------

class TestLiveDirectories:
    def test_all_results_contain_query(self, live_client):
        """Every returned dir_path must contain the query string (case-insensitive)."""
        results = get(live_client, "/directories", q="users")
        for r in results:
            assert "users" in r["dir_path"].lower(), (
                f"Result '{r['dir_path']}' does not contain 'users'"
            )

    def test_short_query_returns_empty(self, live_client):
        """Single-char query should return []."""
        results = get(live_client, "/directories", q="x")
        assert results == []

    def test_respects_limit(self, live_client):
        results = get(live_client, "/directories", q="users", limit=3)
        assert len(results) <= 3

    def test_result_has_required_fields(self, live_client):
        results = get(live_client, "/directories", q="users", limit=1)
        if not results:
            pytest.skip("No matching directories")
        assert "dir_path" in results[0]
        assert "dir_display" in results[0]

    def test_matching_ancestors_included(self, live_client):
        """
        Regression: if a returned path has an ancestor that also contains the
        query string, that ancestor must also appear in the results.

        Without this, the tree expands the ancestor (as a non-highlighted
        node) and shows the matched child underneath — confusing the user.

        Example with q='better':
          Returned: /users/brian/downloads/betterzip.app/contents
          Missing:  /users/brian/downloads/betterzip.app   ← also contains 'better'

        The UI expands betterzip.app to reveal Contents, but betterzip.app
        itself is not highlighted as a match.
        """
        q = "better"
        results = get(live_client, "/directories", q=q, limit=100)
        if not results:
            pytest.skip(f"No '{q}' directories in database — cannot test")

        result_paths = {r["dir_path"] for r in results}

        missing = []
        for r in results:
            parts = r["dir_path"].split("/")  # ['', 'users', 'brian', ...]
            for i in range(2, len(parts)):
                ancestor = "/".join(parts[:i])
                if q.lower() in ancestor.lower() and ancestor not in result_paths:
                    missing.append((r["dir_path"], ancestor))

        assert not missing, (
            "These result paths have matching ancestors not in the results "
            "(the UI will expand the ancestor without highlighting it):\n"
            + "\n".join(f"  {child!r} is missing ancestor {anc!r}"
                        for child, anc in missing[:5])
        )
