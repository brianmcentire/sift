"""Unit tests for sift.commands.scan helpers."""
import io
import sys
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from sift.commands.scan import _is_macos_dataless, _print_progress


# ---------------------------------------------------------------------------
# _is_macos_dataless — APFS cloud-evicted stubs (st_blocks == 0 on darwin)
# ---------------------------------------------------------------------------

class TestIsMacosDataless:
    """st_blocks == 0 detection, gated on darwin."""

    def test_zero_blocks_darwin_is_dataless(self):
        assert _is_macos_dataless(st_blocks=0, source_os="darwin")

    def test_zero_blocks_linux_not_dataless(self):
        assert not _is_macos_dataless(st_blocks=0, source_os="linux")

    def test_zero_blocks_windows_not_dataless(self):
        assert not _is_macos_dataless(st_blocks=0, source_os="windows")

    def test_nonzero_blocks_darwin_not_dataless(self):
        assert not _is_macos_dataless(st_blocks=8, source_os="darwin")

    def test_nonzero_blocks_linux_not_dataless(self):
        assert not _is_macos_dataless(st_blocks=16, source_os="linux")


# ---------------------------------------------------------------------------
# _print_progress — regression test: total=None must not crash
# ---------------------------------------------------------------------------

def _make_stats(files_scanned=0, files_skipped=0, bytes_scanned=0, bytes_hashed=0,
                files_hashed=0, files_cached=0):
    return {
        "files_scanned": files_scanned,
        "files_skipped": files_skipped,
        "bytes_scanned": bytes_scanned,
        "bytes_hashed": bytes_hashed,
        "files_hashed": files_hashed,
        "files_cached": files_cached,
    }


def _make_display(total=None, total_is_estimate=False, current_file=""):
    return {
        "total": total,
        "total_is_estimate": total_is_estimate,
        "current_file": current_file,
        "precount": {},
        "lines": 0,
    }


class TestPrintProgress:
    """_print_progress must not raise regardless of display state."""

    def _call(self, stats, display, final=False):
        scan_start = datetime.now(timezone.utc)
        with patch("sys.stderr", new_callable=io.StringIO):
            _print_progress(stats, scan_start, display, final=final)

    def test_total_none_does_not_crash(self):
        """Regression: total=None caused TypeError: unsupported format string for NoneType."""
        self._call(_make_stats(), _make_display(total=None))

    def test_total_zero_does_not_crash(self):
        self._call(_make_stats(), _make_display(total=0))

    def test_total_known_renders_percentage(self):
        display = _make_display(total=100, total_is_estimate=False)
        stats = _make_stats(files_scanned=50, bytes_scanned=1024)
        self._call(stats, display)

    def test_total_estimate_renders_tilde(self):
        display = _make_display(total=200, total_is_estimate=True)
        self._call(_make_stats(files_scanned=10), display)

    def test_final_mode_does_not_crash(self):
        display = _make_display(total=50, total_is_estimate=False)
        self._call(_make_stats(files_scanned=50), display, final=True)

    def test_precount_picked_up_when_total_none(self):
        display = _make_display(total=None)
        display["precount"] = {"count": 500}
        self._call(_make_stats(files_scanned=100), display)
        assert display["total"] == 500
        assert display["total_is_estimate"] is True
