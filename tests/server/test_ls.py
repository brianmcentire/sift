"""
Tests for GET /files/ls.

This is the most critical endpoint — it drives the file tree UI.
Several tests here DOCUMENT KNOWN BUGS that will fail on current code and
pass after the fix. They are marked with comments.

The core bug: the `dupes` CTE in the ls SQL is global (not scoped to the
queried host). This causes files with cross-host copies to be counted in
dup_count even when only one copy exists on the queried host. The correct
behavior is that dup_count reflects same-host duplicates; cross-host info
belongs in other_hosts.
"""
import pytest
from tests.server.conftest import (
    NOW, HASH_A, HASH_B, HASH_C, HASH_D, HASH_E, HASH_F,
    client, make_file, insert_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ls(client, path="/", host="mac"):
    resp = client.get("/files/ls", params={"path": path, "host": host})
    assert resp.status_code == 200
    return resp.json()


def entry_by_segment(entries, segment):
    return next((e for e in entries if e["segment"] == segment), None)


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

class TestLsBasic:
    def test_single_file_appears_as_file_entry(self, client):
        insert_files([make_file(path="/users/brian/photo.jpg", filename="photo.jpg")])
        entries = ls(client, "/users/brian", "mac")
        e = entry_by_segment(entries, "photo.jpg")
        assert e is not None
        assert e["entry_type"] == "file"

    def test_subdir_appears_as_dir_entry(self, client):
        insert_files([make_file(path="/users/brian/docs/report.pdf", filename="report.pdf")])
        entries = ls(client, "/users/brian", "mac")
        e = entry_by_segment(entries, "docs")
        assert e is not None
        assert e["entry_type"] == "dir"

    def test_dirs_returned_before_files(self, client):
        insert_files([
            make_file(path="/users/brian/aaa_file.txt", filename="aaa_file.txt"),
            make_file(path="/users/brian/zzz_dir/file.txt", filename="file.txt", hash=HASH_B),
        ])
        entries = ls(client, "/users/brian", "mac")
        types = [e["entry_type"] for e in entries]
        # dirs come first in the ORDER BY (entry_type DESC → 'file' < 'dir')
        last_dir = max((i for i, t in enumerate(types) if t == "dir"), default=-1)
        first_file = min((i for i, t in enumerate(types) if t == "file"), default=999)
        assert last_dir < first_file

    def test_file_count_for_dir(self, client):
        insert_files([
            make_file(path="/users/brian/docs/a.pdf", filename="a.pdf"),
            make_file(path="/users/brian/docs/b.pdf", filename="b.pdf", hash=HASH_B),
            make_file(path="/users/brian/docs/c.pdf", filename="c.pdf", hash=HASH_C),
        ])
        entries = ls(client, "/users/brian", "mac")
        docs = entry_by_segment(entries, "docs")
        assert docs["file_count"] == 3

    def test_total_bytes_for_dir(self, client):
        insert_files([
            make_file(path="/users/brian/docs/a.pdf", filename="a.pdf", size=1000),
            make_file(path="/users/brian/docs/b.pdf", filename="b.pdf", size=2000, hash=HASH_B),
        ])
        entries = ls(client, "/users/brian", "mac")
        docs = entry_by_segment(entries, "docs")
        assert docs["total_bytes"] == 3000

    def test_total_bytes_for_single_file(self, client):
        insert_files([make_file(path="/users/brian/photo.jpg", filename="photo.jpg", size=5000)])
        entries = ls(client, "/users/brian", "mac")
        e = entry_by_segment(entries, "photo.jpg")
        assert e["size_bytes"] == 5000

    def test_other_host_files_not_visible(self, client):
        insert_files([
            make_file(host="mac", path="/users/brian/mac_only.txt", filename="mac_only.txt"),
            make_file(host="nas", path="/users/brian/nas_only.txt", filename="nas_only.txt"),
        ])
        entries = ls(client, "/users/brian", "mac")
        segments = {e["segment"] for e in entries}
        assert "mac_only.txt" in segments
        assert "nas_only.txt" not in segments

    def test_root_listing(self, client):
        insert_files([make_file(path="/users/brian/file.txt", filename="file.txt")])
        entries = ls(client, "/", "mac")
        e = entry_by_segment(entries, "users")
        assert e is not None
        assert e["entry_type"] == "dir"

    def test_empty_path_returns_empty(self, client):
        entries = ls(client, "/nonexistent", "mac")
        assert entries == []

    def test_path_query_case_insensitive(self, client):
        """The server should lowercase the path param before querying."""
        insert_files([make_file(path="/users/brian/file.txt", filename="file.txt")])
        entries = ls(client, "/Users/Brian", "mac")
        assert entry_by_segment(entries, "file.txt") is not None

    def test_prefix_slash_separator_required(self, client):
        """
        /users/brian2 must NOT appear in ls for path=/users/brian.
        The SQL uses path LIKE root || '/%', not root || '%'.
        """
        insert_files([
            make_file(host="mac", path="/users/brian/file.txt", filename="file.txt"),
            make_file(host="mac", path="/users/brian2/file.txt", filename="file.txt",
                      hash=HASH_B),
        ])
        entries = ls(client, "/users/brian", "mac")
        segments = {e["segment"] for e in entries}
        assert "file.txt" in segments
        # brian2's file should not leak into brian's listing
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Duplicate detection — same-host
# ---------------------------------------------------------------------------

class TestLsSameHostDuplicates:
    def test_two_files_same_host_same_hash_dup_count(self, client):
        """Two files on the same host with the same hash: both are dups."""
        insert_files([
            make_file(path="/users/brian/photos/beach.jpg", filename="beach.jpg", hash=HASH_A),
            make_file(path="/users/brian/photos/copy.jpg", filename="copy.jpg", hash=HASH_A),
        ])
        entries = ls(client, "/users/brian/photos", "mac")
        dup_entries = [e for e in entries if e["dup_count"] > 0]
        assert len(dup_entries) == 2  # both files are in the dup set

    def test_same_host_dup_dup_hash_count(self, client):
        insert_files([
            make_file(path="/users/brian/photos/beach.jpg", filename="beach.jpg", hash=HASH_A),
            make_file(path="/users/brian/photos/copy.jpg", filename="copy.jpg", hash=HASH_A),
        ])
        entries = ls(client, "/users/brian/photos", "mac")
        beach = entry_by_segment(entries, "beach.jpg")
        copy = entry_by_segment(entries, "copy.jpg")
        # Each file: dup_count=1, dup_hash_count=1 → extra_copies=0 at file level
        assert beach["dup_count"] == 1
        assert beach["dup_hash_count"] == 1

    def test_parent_dir_extra_copies_for_same_host_dup(self, client):
        """
        In the parent dir view, photos/ should show extra_copies = dup_count - dup_hash_count.
        With 2 files sharing HASH_A: dup_count=2, dup_hash_count=1 → 1 extra copy.
        """
        insert_files([
            make_file(path="/users/brian/photos/beach.jpg", filename="beach.jpg", hash=HASH_A),
            make_file(path="/users/brian/photos/copy.jpg", filename="copy.jpg", hash=HASH_A),
            make_file(path="/users/brian/photos/unique.jpg", filename="unique.jpg", hash=HASH_B),
        ])
        entries = ls(client, "/users/brian", "mac")
        photos = entry_by_segment(entries, "photos")
        extra_copies = photos["dup_count"] - photos["dup_hash_count"]
        assert extra_copies == 1  # one HASH_A beyond the first

    def test_three_same_hash_files_extra_copies(self, client):
        """
        Three files sharing HASH_F inside a subdir.
        Viewing the parent: the subdir entry should show dup_count=3,
        dup_hash_count=1 → 2 extra copies.
        (extra_copies is a directory-level aggregate, not per-file)
        """
        insert_files([
            make_file(path="/users/brian/photos/a.jpg", filename="a.jpg", hash=HASH_F),
            make_file(path="/users/brian/photos/b.jpg", filename="b.jpg", hash=HASH_F),
            make_file(path="/users/brian/photos/c.jpg", filename="c.jpg", hash=HASH_F),
        ])
        entries = ls(client, "/users/brian", "mac")
        photos = entry_by_segment(entries, "photos")
        assert photos is not None
        extra = photos["dup_count"] - photos["dup_hash_count"]
        assert extra == 2

    def test_unique_file_dup_count_zero(self, client):
        """A file with no duplicates anywhere has dup_count=0."""
        insert_files([make_file(path="/users/brian/unique.txt", filename="unique.txt", hash=HASH_B)])
        entries = ls(client, "/users/brian", "mac")
        e = entry_by_segment(entries, "unique.txt")
        assert e["dup_count"] == 0


# ---------------------------------------------------------------------------
# Duplicate detection — cross-host
# BUG: these tests document the CORRECT expected behavior.
# They will FAIL on current code because the dupes CTE is not host-scoped.
# ---------------------------------------------------------------------------

class TestLsCrossHostDuplicates:
    def test_cross_host_dup_not_in_dup_count(self, client):
        """
        CORRECT BEHAVIOR (will fail on buggy code):
        A file that exists on mac AND nas (same hash) but only ONCE on mac
        should have dup_count=0 when querying mac. It is not a same-host dup.
        The cross-host information belongs in other_hosts.
        """
        insert_files([
            make_file(host="mac", path="/users/brian/photo.jpg",
                      filename="photo.jpg", hash=HASH_C),
            make_file(host="nas", path="/mnt/backup/photo.jpg",
                      filename="photo.jpg", hash=HASH_C),
        ])
        entries = ls(client, "/users/brian", "mac")
        photo = entry_by_segment(entries, "photo.jpg")
        assert photo is not None
        # FAILS on current code: dup_count=1 because global dupes sees 2 copies
        assert photo["dup_count"] == 0

    def test_cross_host_dup_in_other_hosts(self, client):
        """Cross-host copy appears in other_hosts, not dup_count."""
        insert_files([
            make_file(host="mac", path="/users/brian/photo.jpg",
                      filename="photo.jpg", hash=HASH_C),
            make_file(host="nas", path="/mnt/backup/photo.jpg",
                      filename="photo.jpg", hash=HASH_C),
        ])
        entries = ls(client, "/users/brian", "mac")
        photo = entry_by_segment(entries, "photo.jpg")
        assert photo["other_hosts"] == "nas"

    def test_dir_extra_copies_only_counts_same_host(self, client):
        """
        CORRECT BEHAVIOR (will fail on buggy code):
        A directory containing files that exist cross-host but are NOT
        duplicated within the queried host should show extra_copies=0.
        """
        insert_files([
            # mac has 3 files, each with a unique hash (no same-host dups)
            make_file(host="mac", path="/users/brian/docs/a.pdf",
                      filename="a.pdf", hash=HASH_A),
            make_file(host="mac", path="/users/brian/docs/b.pdf",
                      filename="b.pdf", hash=HASH_B),
            make_file(host="mac", path="/users/brian/docs/c.pdf",
                      filename="c.pdf", hash=HASH_C),
            # nas has copies of all three (cross-host dups)
            make_file(host="nas", path="/mnt/backup/a.pdf",
                      filename="a.pdf", hash=HASH_A),
            make_file(host="nas", path="/mnt/backup/b.pdf",
                      filename="b.pdf", hash=HASH_B),
            make_file(host="nas", path="/mnt/backup/c.pdf",
                      filename="c.pdf", hash=HASH_C),
        ])
        entries = ls(client, "/users/brian", "mac")
        docs = entry_by_segment(entries, "docs")
        # FAILS on current code: dup_count=3, dup_hash_count=3 → extra=0 (coincidentally ok)
        # But dup_count=3 itself is wrong — these are not same-host dups
        assert docs["dup_count"] == 0

    def test_mixed_same_and_cross_host_dups(self, client):
        """
        CORRECT BEHAVIOR (will fail on buggy code):
        Mac has HASH_A twice (same-host dup) and HASH_C once (cross-host to nas).
        When querying mac:
          - HASH_A files: dup_count=2, dup_hash_count=1 → 1 extra copy (correct)
          - HASH_C file: dup_count=0 (correct, not a same-host dup)
        Parent dir should show dup_count=2, dup_hash_count=1 → 1 extra copy total.
        """
        insert_files([
            make_file(host="mac", path="/users/brian/docs/a1.pdf",
                      filename="a1.pdf", hash=HASH_A),
            make_file(host="mac", path="/users/brian/docs/a2.pdf",
                      filename="a2.pdf", hash=HASH_A),
            make_file(host="mac", path="/users/brian/docs/cross.pdf",
                      filename="cross.pdf", hash=HASH_C),
            make_file(host="nas", path="/mnt/cross.pdf",
                      filename="cross.pdf", hash=HASH_C),
        ])
        entries = ls(client, "/users/brian", "mac")
        docs = entry_by_segment(entries, "docs")
        # dup_count should be 2 (the two HASH_A files only)
        # FAILS on current code: dup_count=3 (HASH_A×2 + HASH_C×1 from global dupes)
        assert docs["dup_count"] == 2
        assert docs["dup_hash_count"] == 1

    def test_three_hosts_same_hash_no_same_host_dup(self, client):
        """
        File exists on mac, nas, pi — each host has exactly one copy.
        When querying mac: dup_count=0, other_hosts should list nas and pi.
        """
        insert_files([
            make_file(host="mac", path="/users/brian/shared.jpg",
                      filename="shared.jpg", hash=HASH_A),
            make_file(host="nas", path="/mnt/shared.jpg",
                      filename="shared.jpg", hash=HASH_A),
            make_file(host="pi", path="/home/pi/shared.jpg",
                      filename="shared.jpg", hash=HASH_A),
        ])
        entries = ls(client, "/users/brian", "mac")
        e = entry_by_segment(entries, "shared.jpg")
        # FAILS on current code
        assert e["dup_count"] == 0
        assert e["other_hosts"] is not None
        hosts = set(e["other_hosts"].split(","))
        assert "nas" in hosts
        assert "pi" in hosts


# ---------------------------------------------------------------------------
# Segment display / path_display passthrough
# ---------------------------------------------------------------------------

class TestLsDisplay:
    def test_segment_display_preserves_case(self, client):
        insert_files([
            make_file(
                path="/users/brian/my documents/report.pdf",
                path_display="/Users/Brian/My Documents/report.pdf",
                filename="report.pdf",
            )
        ])
        entries = ls(client, "/users/brian", "mac")
        d = entry_by_segment(entries, "my documents")
        assert d is not None
        # segment_display should preserve original case
        assert d["segment_display"] == "My Documents"

    def test_file_path_display_set(self, client):
        insert_files([
            make_file(
                path="/users/brian/photo.jpg",
                path_display="/Users/Brian/Photo.JPG",
                filename="Photo.JPG",
            )
        ])
        entries = ls(client, "/users/brian", "mac")
        e = entry_by_segment(entries, "photo.jpg")
        assert e["path_display"] == "/Users/Brian/Photo.JPG"


# ---------------------------------------------------------------------------
# Hard link detection
# ---------------------------------------------------------------------------

class TestLsHardLinks:
    def test_hard_linked_file_is_not_a_dup(self, client):
        """
        Two paths with the same (device, inode) are hard links to the same
        physical file. They should NOT be counted as duplicates (dup_count=0).
        """
        insert_files([
            make_file(path="/users/brian/bin/bash",    filename="bash",    hash=HASH_A, inode=101, device=10),
            make_file(path="/users/brian/bin/sh",      filename="sh",      hash=HASH_A, inode=101, device=10),
        ])
        entries = ls(client, "/users/brian/bin", "mac")
        bash = entry_by_segment(entries, "bash")
        sh   = entry_by_segment(entries, "sh")
        assert bash["dup_count"] == 0, "hard link should not count as dup"
        assert sh["dup_count"]   == 0, "hard link should not count as dup"

    def test_hard_linked_file_is_flagged(self, client):
        """Hard-linked files should have is_hard_linked=True."""
        insert_files([
            make_file(path="/users/brian/bin/bash", filename="bash", hash=HASH_A, inode=101, device=10),
            make_file(path="/users/brian/bin/sh",   filename="sh",   hash=HASH_A, inode=101, device=10),
        ])
        entries = ls(client, "/users/brian/bin", "mac")
        bash = entry_by_segment(entries, "bash")
        assert bash["is_hard_linked"] is True

    def test_non_hard_linked_dup_still_counted(self, client):
        """
        Two files with same hash but DIFFERENT inodes are real duplicates,
        not hard links → dup_count > 0.
        """
        insert_files([
            make_file(path="/users/brian/docs/a.pdf", filename="a.pdf", hash=HASH_A, inode=201, device=10),
            make_file(path="/users/brian/docs/b.pdf", filename="b.pdf", hash=HASH_A, inode=202, device=10),
        ])
        entries = ls(client, "/users/brian/docs", "mac")
        a = entry_by_segment(entries, "a.pdf")
        b = entry_by_segment(entries, "b.pdf")
        assert a["dup_count"] == 1
        assert b["dup_count"] == 1
        assert a["is_hard_linked"] is False
        assert b["is_hard_linked"] is False

    def test_files_without_inode_not_hard_linked(self, client):
        """Files with inode=None (e.g., Windows) are never flagged as hard linked."""
        insert_files([
            make_file(path="/users/brian/a.txt", filename="a.txt", hash=HASH_A, inode=None, device=None),
            make_file(path="/users/brian/b.txt", filename="b.txt", hash=HASH_A, inode=None, device=None),
        ])
        entries = ls(client, "/users/brian", "mac")
        a = entry_by_segment(entries, "a.txt")
        assert a["is_hard_linked"] is False
        # Same hash, different paths, no inode → they ARE dups
        assert a["dup_count"] == 1

    def test_hard_links_across_different_devices_not_linked(self, client):
        """
        Same inode number on different devices are NOT hard links.
        (Inodes are only unique within a device.)
        """
        insert_files([
            make_file(path="/users/brian/a.txt", filename="a.txt", hash=HASH_A, inode=101, device=10),
            make_file(path="/users/brian/b.txt", filename="b.txt", hash=HASH_A, inode=101, device=20),
        ])
        entries = ls(client, "/users/brian", "mac")
        a = entry_by_segment(entries, "a.txt")
        b = entry_by_segment(entries, "b.txt")
        # Different devices: not hard links; same hash: they ARE dups
        assert a["is_hard_linked"] is False
        assert b["is_hard_linked"] is False
        assert a["dup_count"] == 1
        assert b["dup_count"] == 1
