"""Unit tests for sift.exclusions."""
import time
from unittest.mock import patch
import pytest
from sift.exclusions import (
    _is_unraid, _is_unraid_disk_path,
    is_excluded_dir, is_excluded_file, is_volatile_active,
)


class TestIsExcludedDir:
    # -- Leaf name exclusions -----------------------------------------------

    def test_git_dir(self):
        assert is_excluded_dir("/Users/brian/project/.git", ".git", "darwin")

    def test_git_dir_uppercase(self):
        # Case-insensitive leaf check
        assert is_excluded_dir("/Users/brian/project/.GIT", ".GIT", "darwin")

    def test_node_modules(self):
        assert is_excluded_dir("/app/node_modules", "node_modules", "darwin")

    def test_pycache(self):
        assert is_excluded_dir("/app/__pycache__", "__pycache__", "linux")

    def test_venv(self):
        assert is_excluded_dir("/project/.venv", ".venv", "darwin")

    def test_trash(self):
        assert is_excluded_dir("/Users/brian/.Trash", ".Trash", "darwin")

    def test_normal_dir_not_excluded(self):
        assert not is_excluded_dir("/Users/brian/Documents", "Documents", "darwin")

    def test_photos_not_excluded(self):
        assert not is_excluded_dir("/Users/brian/Photos", "Photos", "darwin")

    # -- POSIX path prefix exclusions ---------------------------------------

    def test_proc_excluded(self):
        assert is_excluded_dir("/proc/123", "123", "linux")

    def test_sys_excluded(self):
        assert is_excluded_dir("/sys/kernel", "kernel", "linux")

    def test_dev_excluded(self):
        assert is_excluded_dir("/dev/disk0", "disk0", "linux")

    def test_tmp_excluded(self):
        assert is_excluded_dir("/tmp/cache", "cache", "linux")

    def test_var_cache_excluded(self):
        assert is_excluded_dir("/var/cache/apt", "apt", "linux")

    def test_usr_not_excluded(self):
        assert not is_excluded_dir("/usr/local/bin", "bin", "linux")

    # -- Windows path prefix exclusions ------------------------------------

    def test_windows_system32_excluded(self):
        assert is_excluded_dir("C:\\Windows\\System32", "System32", "windows")

    def test_windows_temp_excluded(self):
        assert is_excluded_dir("C:\\Windows\\Temp", "Temp", "windows")

    def test_windows_recycle_bin_excluded(self):
        assert is_excluded_dir("C:\\$RECYCLE.BIN", "$RECYCLE.BIN", "windows")

    def test_windows_documents_not_excluded(self):
        assert not is_excluded_dir("C:\\Users\\Brian\\Documents", "Documents", "windows")

    # -- Unraid /mnt/diskN exclusion ---------------------------------------

    def test_unraid_disk_excluded_on_unraid(self):
        with patch("sift.exclusions._is_unraid", return_value=True):
            assert is_excluded_dir("/mnt/disk1", "disk1", "linux")

    def test_unraid_disk_subpath_excluded_on_unraid(self):
        with patch("sift.exclusions._is_unraid", return_value=True):
            assert is_excluded_dir("/mnt/disk1/data", "data", "linux")

    def test_unraid_disk_not_excluded_with_yolo(self):
        with patch("sift.exclusions._is_unraid", return_value=True):
            assert not is_excluded_dir("/mnt/disk1", "disk1", "linux", allow_unraid_disks=True)

    def test_unraid_disk_not_excluded_on_non_unraid(self):
        with patch("sift.exclusions._is_unraid", return_value=False):
            assert not is_excluded_dir("/mnt/disk1", "disk1", "linux")

    def test_mnt_user_not_excluded_on_unraid(self):
        with patch("sift.exclusions._is_unraid", return_value=True):
            assert not is_excluded_dir("/mnt/user", "user", "linux")

    def test_mnt_appdata_not_excluded_on_unraid(self):
        with patch("sift.exclusions._is_unraid", return_value=True):
            assert not is_excluded_dir("/mnt/appdata", "appdata", "linux")

    def test_unraid_disk_re_pattern_disk10(self):
        assert _is_unraid_disk_path("/mnt/disk10")
        assert _is_unraid_disk_path("/mnt/disk10/foo")

    def test_unraid_disk_re_pattern_not_disklike(self):
        assert not _is_unraid_disk_path("/mnt/user")
        assert not _is_unraid_disk_path("/mnt/cache")
        assert not _is_unraid_disk_path("/mnt/diskabc")


class TestIsExcludedFile:
    def test_ds_store(self):
        assert is_excluded_file(".DS_Store", "")

    def test_thumbs_db(self):
        assert is_excluded_file("Thumbs.db", "")

    def test_pagefile(self):
        assert is_excluded_file("pagefile.sys", "sys")

    def test_tmp_extension(self):
        assert is_excluded_file("download.tmp", "tmp")

    def test_lock_extension(self):
        assert is_excluded_file("app.lock", "lock")

    def test_part_extension(self):
        # Partial download
        assert is_excluded_file("video.part", "part")

    def test_normal_file_not_excluded(self):
        assert not is_excluded_file("document.pdf", "pdf")

    def test_photo_not_excluded(self):
        assert not is_excluded_file("photo.jpg", "jpg")


class TestIsVolatileActive:
    def _recent_mtime(self):
        # 1 day ago — within any reasonable threshold
        return time.time() - 86400

    def _old_mtime(self):
        # 60 days ago — outside default 30-day threshold
        return time.time() - (60 * 86400)

    # -- Volatile by extension ---------------------------------------------

    def test_vmdk_recent_is_volatile(self):
        assert is_volatile_active(
            "/vms/ubuntu.vmdk", "ubuntu.vmdk", "vmdk",
            self._recent_mtime(), "linux"
        )

    def test_vmdk_old_not_volatile(self):
        # Old enough to be a dormant backup — hash it
        assert not is_volatile_active(
            "/backups/old.vmdk", "old.vmdk", "vmdk",
            self._old_mtime(), "linux"
        )

    def test_ost_recent_is_volatile(self):
        assert is_volatile_active(
            "/Users/brian/mail.ost", "mail.ost", "ost",
            self._recent_mtime(), "darwin"
        )

    def test_iso_not_volatile(self):
        # iso is in disk category but NOT in VOLATILE_EXTENSIONS
        assert not is_volatile_active(
            "/isos/ubuntu.iso", "ubuntu.iso", "iso",
            self._recent_mtime(), "linux"
        )

    # -- Volatile by directory pattern ------------------------------------

    def test_virtualbox_dir_recent_is_volatile(self):
        assert is_volatile_active(
            "/Users/brian/VirtualBox VMs/ubuntu/ubuntu.vdi",
            "ubuntu.vdi", "vdi",
            self._recent_mtime(), "darwin"
        )

    def test_docker_dir_recent_is_volatile(self):
        assert is_volatile_active(
            "/var/lib/docker/overlay2/abc123/diff/file.bin",
            "file.bin", "bin",
            self._recent_mtime(), "linux"
        )

    def test_docker_dir_old_not_volatile(self):
        assert not is_volatile_active(
            "/var/lib/docker/overlay2/abc123/diff/file.bin",
            "file.bin", "bin",
            self._old_mtime(), "linux"
        )

    def test_normal_file_not_volatile(self):
        assert not is_volatile_active(
            "/Users/brian/Documents/report.pdf", "report.pdf", "pdf",
            self._recent_mtime(), "darwin"
        )

    # -- Custom threshold --------------------------------------------------

    def test_custom_threshold(self):
        mtime_10_days_ago = time.time() - (10 * 86400)
        # Within 5-day threshold → volatile
        assert is_volatile_active(
            "/vms/test.vmdk", "test.vmdk", "vmdk",
            mtime_10_days_ago, "linux", threshold_days=5
        ) is False
        # Within 15-day threshold → volatile
        assert is_volatile_active(
            "/vms/test.vmdk", "test.vmdk", "vmdk",
            mtime_10_days_ago, "linux", threshold_days=15
        ) is True
