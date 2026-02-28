"""Unit tests for sift.normalize."""
import pytest
from unittest.mock import patch
from sift.normalize import normalize_path, local_hostname, get_source_os, safe_path


class TestNormalizePath:
    # -- POSIX (darwin / linux) -------------------------------------------

    def test_posix_path_is_lowercased(self):
        path, display, drive = normalize_path("/Users/Brian/Documents", "darwin")
        assert path == "/users/brian/documents"

    def test_posix_display_preserves_case(self):
        path, display, drive = normalize_path("/Users/Brian/Documents", "darwin")
        assert display == "/Users/Brian/Documents"

    def test_posix_drive_is_empty(self):
        _, _, drive = normalize_path("/Users/Brian/Documents", "darwin")
        assert drive == ""

    def test_posix_already_lowercase_unchanged(self):
        path, _, _ = normalize_path("/home/brian/file.txt", "linux")
        assert path == "/home/brian/file.txt"

    def test_posix_forward_slashes_preserved(self):
        path, _, _ = normalize_path("/some/path/file.txt", "linux")
        assert "/" in path
        assert "\\" not in path

    # -- Windows ----------------------------------------------------------

    def test_windows_backslashes_converted(self):
        path, display, drive = normalize_path("C:\\Users\\Brian\\file.txt", "windows")
        assert "\\" not in path
        assert "\\" not in display

    def test_windows_drive_letter_extracted(self):
        _, _, drive = normalize_path("C:\\Users\\Brian\\file.txt", "windows")
        assert drive == "C"

    def test_windows_drive_letter_uppercased(self):
        _, _, drive = normalize_path("c:\\Users\\Brian\\file.txt", "windows")
        assert drive == "C"

    def test_windows_drive_stripped_from_path(self):
        path, display, _ = normalize_path("C:\\Users\\Brian\\file.txt", "windows")
        assert not path.startswith("c:")
        assert not display.startswith("C:")

    def test_windows_path_lowercased(self):
        path, _, _ = normalize_path("C:\\Users\\Brian\\File.TXT", "windows")
        assert path == path.lower()

    def test_windows_display_preserves_case(self):
        _, display, _ = normalize_path("C:\\Users\\Brian\\File.TXT", "windows")
        assert "Brian" in display

    def test_windows_long_path_prefix_stripped(self):
        # \\?\ prefix used by Windows for long paths
        path, display, drive = normalize_path("\\\\?\\C:\\Users\\Brian\\file.txt", "windows")
        assert "\\\\?\\" not in path
        assert "\\\\?\\" not in display
        assert drive == "C"

    def test_windows_d_drive(self):
        _, _, drive = normalize_path("D:\\Data\\archive.zip", "windows")
        assert drive == "D"

    # -- Path consistency -------------------------------------------------

    def test_same_path_different_case_same_key(self):
        """The path key must be identical for the same file regardless of case."""
        path1, _, _ = normalize_path("/Users/Brian/Doc.PDF", "darwin")
        path2, _, _ = normalize_path("/users/brian/doc.pdf", "darwin")
        assert path1 == path2

    def test_windows_same_path_different_case_same_key(self):
        path1, _, _ = normalize_path("C:\\Users\\Brian\\Doc.PDF", "windows")
        path2, _, _ = normalize_path("C:\\users\\brian\\doc.pdf", "windows")
        assert path1 == path2


class TestLocalHostname:
    def test_returns_string(self):
        host = local_hostname()
        assert isinstance(host, str)
        assert len(host) > 0

    def test_no_dots_in_result(self):
        host = local_hostname()
        # FQDN stripped — result should be just the short name
        assert "." not in host


class TestGetSourceOs:
    def test_returns_known_value(self):
        os_name = get_source_os()
        assert os_name in ("darwin", "linux", "windows")


class TestSafePath:
    def test_posix_passthrough(self):
        with patch("sift.normalize.get_source_os", return_value="darwin"):
            assert safe_path("/Users/brian/file.txt") == "/Users/brian/file.txt"

    def test_windows_adds_prefix(self):
        with patch("sift.normalize.get_source_os", return_value="windows"):
            result = safe_path("C:\\Users\\brian\\file.txt")
            assert result.startswith("\\\\?\\")
            assert "C:\\Users\\brian\\file.txt" in result

    def test_windows_already_prefixed(self):
        with patch("sift.normalize.get_source_os", return_value="windows"):
            prefixed = "\\\\?\\C:\\Users\\brian\\file.txt"
            assert safe_path(prefixed) == prefixed

    def test_windows_unc_path_gets_unc_prefix(self):
        with patch("sift.normalize.get_source_os", return_value="windows"):
            result = safe_path("\\\\server\\share\\file.txt")
            assert result.startswith("\\\\?\\UNC\\")
            assert "server\\share\\file.txt" in result
