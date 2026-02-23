"""Unit tests for sift.hash_utils."""
import hashlib
import math
import os
import tempfile
import pytest
from sift.hash_utils import hash_file, needs_rehash


class TestHashFile:
    def _write_tmp(self, content: bytes) -> str:
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_empty_content_returns_known_hash(self):
        path = self._write_tmp(b"")
        try:
            result = hash_file(path)
            expected = hashlib.sha256(b"").hexdigest()
            assert result == expected
        finally:
            os.unlink(path)

    def test_known_content_returns_correct_hash(self):
        content = b"hello sift"
        path = self._write_tmp(content)
        try:
            result = hash_file(path)
            expected = hashlib.sha256(content).hexdigest()
            assert result == expected
        finally:
            os.unlink(path)

    def test_returns_64_char_hex_string(self):
        path = self._write_tmp(b"test data")
        try:
            result = hash_file(path)
            assert isinstance(result, str)
            assert len(result) == 64
            assert all(c in "0123456789abcdef" for c in result)
        finally:
            os.unlink(path)

    def test_same_content_same_hash(self):
        content = b"consistent content"
        path1 = self._write_tmp(content)
        path2 = self._write_tmp(content)
        try:
            assert hash_file(path1) == hash_file(path2)
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_different_content_different_hash(self):
        path1 = self._write_tmp(b"content A")
        path2 = self._write_tmp(b"content B")
        try:
            assert hash_file(path1) != hash_file(path2)
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_nonexistent_file_returns_none(self):
        result = hash_file("/nonexistent/path/to/file.txt")
        assert result is None

    def test_small_chunk_size_same_result(self):
        content = b"x" * 10000
        path = self._write_tmp(content)
        try:
            result_default = hash_file(path)
            result_tiny = hash_file(path, chunk_size=100)
            assert result_default == result_tiny
        finally:
            os.unlink(path)


class TestNeedsRehash:
    def _make_stat(self, mtime: float, size: int):
        """Return a minimal stat_result-like object."""
        class FakeStat:
            st_mtime = mtime
            st_size = size
        return FakeStat()

    def test_no_cache_means_rehash(self):
        stat = self._make_stat(1700000000.0, 1024)
        assert needs_rehash(stat, None) is True

    def test_matching_mtime_and_size_no_rehash(self):
        mtime = 1700000000.0
        size = 1024
        stat = self._make_stat(mtime, size)
        cached = {"mtime": math.floor(mtime), "size_bytes": size}
        assert needs_rehash(stat, cached) is False

    def test_changed_mtime_triggers_rehash(self):
        stat = self._make_stat(1700000999.0, 1024)
        cached = {"mtime": 1700000000, "size_bytes": 1024}
        assert needs_rehash(stat, cached) is True

    def test_changed_size_triggers_rehash(self):
        mtime = 1700000000.0
        stat = self._make_stat(mtime, 2048)
        cached = {"mtime": math.floor(mtime), "size_bytes": 1024}
        assert needs_rehash(stat, cached) is True

    def test_missing_cached_mtime_triggers_rehash(self):
        stat = self._make_stat(1700000000.0, 1024)
        cached = {"mtime": None, "size_bytes": 1024}
        assert needs_rehash(stat, cached) is True

    def test_missing_cached_size_triggers_rehash(self):
        stat = self._make_stat(1700000000.0, 1024)
        cached = {"mtime": 1700000000, "size_bytes": None}
        assert needs_rehash(stat, cached) is True

    def test_mtime_floored_for_comparison(self):
        # mtime with sub-second component — should match floored cached value
        stat = self._make_stat(1700000000.9, 1024)
        cached = {"mtime": 1700000000, "size_bytes": 1024}
        assert needs_rehash(stat, cached) is False
