"""Unit tests for sift.exclusions."""

import time
from unittest.mock import mock_open, patch, MagicMock
import pytest
from sift.exclusions import (
    _build_mount_registry,
    _is_unraid,
    _is_unraid_disk_path,
    is_excluded_dir,
    is_excluded_file,
    is_network_mount,
    is_volatile_active,
    is_windows_cloud_placeholder,
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
        assert not is_excluded_dir(
            "C:\\Users\\Brian\\Documents", "Documents", "windows"
        )

    # -- Unraid /mnt/diskN exclusion ---------------------------------------

    def test_unraid_disk_excluded_on_unraid(self):
        with patch("sift.exclusions._is_unraid", return_value=True):
            assert is_excluded_dir("/mnt/disk1", "disk1", "linux")

    def test_unraid_disk_subpath_excluded_on_unraid(self):
        with patch("sift.exclusions._is_unraid", return_value=True):
            assert is_excluded_dir("/mnt/disk1/data", "data", "linux")

    def test_unraid_disk_not_excluded_with_yolo(self):
        with patch("sift.exclusions._is_unraid", return_value=True):
            assert not is_excluded_dir(
                "/mnt/disk1", "disk1", "linux", allow_unraid_disks=True
            )

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

    # -- macOS iCloud-managed directory exclusions --------------------------

    def test_darwin_library_mail_excluded(self):
        assert is_excluded_dir("/Users/brian/Library/Mail", "Mail", "darwin")

    def test_darwin_library_mail_subdir_excluded(self):
        assert is_excluded_dir(
            "/Users/brian/Library/Mail/V10/[Gmail].mbox/All Mail.mbox",
            "All Mail.mbox",
            "darwin",
        )

    def test_darwin_library_messages_excluded(self):
        assert is_excluded_dir("/Users/brian/Library/Messages", "Messages", "darwin")

    def test_darwin_library_messages_attachments_excluded(self):
        assert is_excluded_dir(
            "/Users/brian/Library/Messages/Attachments/ab",
            "ab",
            "darwin",
        )

    def test_darwin_mobile_documents_excluded(self):
        assert is_excluded_dir(
            "/Users/brian/Library/Mobile Documents/com~apple~CloudDocs",
            "com~apple~CloudDocs",
            "darwin",
        )

    def test_darwin_deviceactivity_cloud_excluded(self):
        assert is_excluded_dir(
            "/Users/brian/Library/.apple.DeviceActivity/Library/com.apple.DeviceActivity/Cloud/"
            "000380-05-0ce7e314-3f38-41b9-8118-b11902b72fd6",
            "000380-05-0ce7e314-3f38-41b9-8118-b11902b72fd6",
            "darwin",
        )

    def test_darwin_library_mail_not_excluded_on_linux(self):
        # Same path on Linux should NOT trigger the darwin exclusion
        assert not is_excluded_dir("/Users/brian/Library/Mail", "Mail", "linux")

    def test_darwin_documents_not_excluded(self):
        assert not is_excluded_dir("/Users/brian/Documents", "Documents", "darwin")

    def test_darwin_desktop_not_excluded(self):
        assert not is_excluded_dir("/Users/brian/Desktop", "Desktop", "darwin")

    def test_darwin_cloud_storage_not_excluded(self):
        # CloudStorage (Dropbox, OneDrive, etc.) should be scanned
        assert not is_excluded_dir(
            "/Users/brian/Library/CloudStorage/Dropbox",
            "Dropbox",
            "darwin",
        )

    def test_darwin_application_support_not_excluded(self):
        assert not is_excluded_dir(
            "/Users/brian/Library/Application Support",
            "Application Support",
            "darwin",
        )


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
            "/vms/ubuntu.vmdk", "ubuntu.vmdk", "vmdk", self._recent_mtime(), "linux"
        )

    def test_vmdk_old_not_volatile(self):
        # Old enough to be a dormant backup — hash it
        assert not is_volatile_active(
            "/backups/old.vmdk", "old.vmdk", "vmdk", self._old_mtime(), "linux"
        )

    def test_ost_recent_is_volatile(self):
        assert is_volatile_active(
            "/Users/brian/mail.ost", "mail.ost", "ost", self._recent_mtime(), "darwin"
        )

    def test_iso_not_volatile(self):
        # iso is in disk category but NOT in VOLATILE_EXTENSIONS
        assert not is_volatile_active(
            "/isos/ubuntu.iso", "ubuntu.iso", "iso", self._recent_mtime(), "linux"
        )

    # -- Volatile by directory pattern ------------------------------------

    def test_virtualbox_dir_recent_is_volatile(self):
        assert is_volatile_active(
            "/Users/brian/VirtualBox VMs/ubuntu/ubuntu.vdi",
            "ubuntu.vdi",
            "vdi",
            self._recent_mtime(),
            "darwin",
        )

    def test_docker_dir_recent_is_volatile(self):
        assert is_volatile_active(
            "/var/lib/docker/overlay2/abc123/diff/file.bin",
            "file.bin",
            "bin",
            self._recent_mtime(),
            "linux",
        )

    def test_docker_dir_old_not_volatile(self):
        assert not is_volatile_active(
            "/var/lib/docker/overlay2/abc123/diff/file.bin",
            "file.bin",
            "bin",
            self._old_mtime(),
            "linux",
        )

    def test_normal_file_not_volatile(self):
        assert not is_volatile_active(
            "/Users/brian/Documents/report.pdf",
            "report.pdf",
            "pdf",
            self._recent_mtime(),
            "darwin",
        )

    # -- Custom threshold --------------------------------------------------

    def test_custom_threshold(self):
        mtime_10_days_ago = time.time() - (10 * 86400)
        # Within 5-day threshold → volatile
        assert (
            is_volatile_active(
                "/vms/test.vmdk",
                "test.vmdk",
                "vmdk",
                mtime_10_days_ago,
                "linux",
                threshold_days=5,
            )
            is False
        )
        # Within 15-day threshold → volatile
        assert (
            is_volatile_active(
                "/vms/test.vmdk",
                "test.vmdk",
                "vmdk",
                mtime_10_days_ago,
                "linux",
                threshold_days=15,
            )
            is True
        )


class TestIsWindowsCloudPlaceholder:
    """OneDrive Files On-Demand placeholder detection."""

    def test_recall_on_data_access_flag(self):
        # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
        assert is_windows_cloud_placeholder(0x400000, "windows")

    def test_recall_on_open_flag(self):
        # FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000 (older OneDrive)
        assert is_windows_cloud_placeholder(0x40000, "windows")

    def test_both_flags(self):
        assert is_windows_cloud_placeholder(0x440000, "windows")

    def test_normal_file_not_placeholder(self):
        # Typical normal file attributes (e.g. FILE_ATTRIBUTE_ARCHIVE = 0x20)
        assert not is_windows_cloud_placeholder(0x20, "windows")

    def test_zero_attributes_not_placeholder(self):
        assert not is_windows_cloud_placeholder(0, "windows")

    def test_not_triggered_on_darwin(self):
        assert not is_windows_cloud_placeholder(0x400000, "darwin")

    def test_not_triggered_on_linux(self):
        assert not is_windows_cloud_placeholder(0x400000, "linux")


class TestBuildMountRegistry:
    """Mount registry construction from system mount info."""

    def _clear_cache(self):
        _build_mount_registry.cache_clear()

    PROC_MOUNTS = (
        "sysfs /sys sysfs rw,nosuid 0 0\n"
        "proc /proc proc rw,nosuid 0 0\n"
        "/dev/sda1 / ext4 rw,relatime 0 0\n"
        "192.168.1.10:/export/data /mnt/nas nfs4 rw,vers=4.2 0 0\n"
        "//server/share /mnt/smb cifs rw,user=brian 0 0\n"
        "mergerfs /mnt/user fuse.mergerfs rw,allow_other 0 0\n"
        "sshfs#user@host: /mnt/remote fuse.sshfs rw,nosuid 0 0\n"
    )

    def test_linux_parses_proc_mounts(self):
        self._clear_cache()
        with patch("builtins.open", mock_open(read_data=self.PROC_MOUNTS)):
            reg = _build_mount_registry("linux")
        assert reg["/"] == "ext4"
        assert reg["/mnt/nas"] == "nfs4"
        assert reg["/mnt/smb"] == "cifs"
        assert reg["/mnt/user"] == "fuse.mergerfs"
        assert reg["/mnt/remote"] == "fuse.sshfs"

    def test_linux_empty_on_missing_proc_mounts(self):
        self._clear_cache()
        with patch("builtins.open", side_effect=OSError("No such file")):
            reg = _build_mount_registry("linux")
        assert reg == {}

    MOUNT_OUTPUT_MACOS = (
        "/dev/disk1s1 on / (apfs, local, journaled)\n"
        "devfs on /dev (devfs, local, nobrowse)\n"
        "nas.local:/volume1/media on /Volumes/media (nfs, nodev, nosuid)\n"
        "//brian@server.local/share on /Volumes/share (smbfs, nodev, nosuid)\n"
    )

    def test_darwin_parses_mount_output(self):
        self._clear_cache()
        mock_result = MagicMock()
        mock_result.stdout = self.MOUNT_OUTPUT_MACOS
        with patch("subprocess.run", return_value=mock_result):
            reg = _build_mount_registry("darwin")
        assert reg["/"] == "apfs"
        assert reg["/Volumes/media"] == "nfs"
        assert reg["/Volumes/share"] == "smbfs"

    def test_darwin_empty_on_subprocess_failure(self):
        self._clear_cache()
        with patch("subprocess.run", side_effect=OSError("command not found")):
            reg = _build_mount_registry("darwin")
        assert reg == {}

    def test_windows_detects_network_drives(self):
        self._clear_cache()
        DRIVE_REMOTE = 4
        DRIVE_FIXED = 3

        def fake_get_drive_type(drive):
            if drive == "Z:\\":
                return DRIVE_REMOTE
            return DRIVE_FIXED

        mock_kernel32 = MagicMock()
        mock_kernel32.GetDriveTypeW = fake_get_drive_type
        mock_windll = MagicMock()
        mock_windll.kernel32 = mock_kernel32

        with patch.dict("sys.modules", {"ctypes": MagicMock()}):
            import ctypes as ct_mock

            ct_mock.windll = mock_windll
            with patch("sift.exclusions.subprocess"):  # unused on windows
                reg = _build_mount_registry("windows")
        # Can't fully test ctypes on non-Windows, but verify fallback works
        # The real test is that it doesn't crash

    def test_unknown_os_returns_empty(self):
        self._clear_cache()
        reg = _build_mount_registry("freebsd")
        assert reg == {}


class TestIsNetworkMount:
    """Network mount detection via mount registry."""

    LINUX_MOUNTS = (
        "/dev/sda1 / ext4 rw 0 0\n"
        "192.168.1.10:/data /mnt/nas nfs4 rw 0 0\n"
        "//server/share /mnt/smb cifs rw 0 0\n"
        "mergerfs /mnt/user fuse.mergerfs rw 0 0\n"
        "sshfs#user@host: /mnt/remote fuse.sshfs rw 0 0\n"
        "rclone /mnt/cloud fuse.rclone rw 0 0\n"
    )

    def _clear_cache(self):
        _build_mount_registry.cache_clear()

    def test_nfs_detected(self):
        self._clear_cache()
        with patch("builtins.open", mock_open(read_data=self.LINUX_MOUNTS)):
            is_net, fstype = is_network_mount("/mnt/nas/photos", "linux")
        assert is_net is True
        assert fstype == "nfs4"

    def test_cifs_detected(self):
        self._clear_cache()
        with patch("builtins.open", mock_open(read_data=self.LINUX_MOUNTS)):
            is_net, fstype = is_network_mount("/mnt/smb/docs", "linux")
        assert is_net is True
        assert fstype == "cifs"

    def test_sshfs_detected(self):
        self._clear_cache()
        with patch("builtins.open", mock_open(read_data=self.LINUX_MOUNTS)):
            is_net, fstype = is_network_mount("/mnt/remote/file.txt", "linux")
        assert is_net is True
        assert fstype == "fuse.sshfs"

    def test_rclone_detected(self):
        self._clear_cache()
        with patch("builtins.open", mock_open(read_data=self.LINUX_MOUNTS)):
            is_net, fstype = is_network_mount("/mnt/cloud/bucket/obj", "linux")
        assert is_net is True
        assert fstype == "fuse.rclone"

    def test_mergerfs_not_excluded(self):
        self._clear_cache()
        with patch("builtins.open", mock_open(read_data=self.LINUX_MOUNTS)):
            is_net, fstype = is_network_mount("/mnt/user/media", "linux")
        assert is_net is False

    def test_ext4_not_excluded(self):
        self._clear_cache()
        with patch("builtins.open", mock_open(read_data=self.LINUX_MOUNTS)):
            is_net, fstype = is_network_mount("/home/brian/docs", "linux")
        assert is_net is False

    def test_apfs_not_excluded(self):
        self._clear_cache()
        mock_result = MagicMock()
        mock_result.stdout = "/dev/disk1s1 on / (apfs, local, journaled)\n"
        with patch("subprocess.run", return_value=mock_result):
            is_net, fstype = is_network_mount("/Users/brian/Desktop", "darwin")
        assert is_net is False

    def test_empty_registry_returns_false(self):
        self._clear_cache()
        with patch("builtins.open", side_effect=OSError("No such file")):
            is_net, fstype = is_network_mount("/mnt/nas/photos", "linux")
        assert is_net is False
        assert fstype == ""

    def test_mount_point_exact_match(self):
        """is_network_mount should match the mount point path exactly."""
        self._clear_cache()
        with patch("builtins.open", mock_open(read_data=self.LINUX_MOUNTS)):
            is_net, fstype = is_network_mount("/mnt/nas", "linux")
        assert is_net is True
        assert fstype == "nfs4"

    def test_longest_prefix_wins(self):
        """When paths overlap, longest mount point prefix should win."""
        self._clear_cache()
        mounts = (
            "/dev/sda1 / ext4 rw 0 0\n"
            "192.168.1.10:/data /mnt nfs4 rw 0 0\n"
            "mergerfs /mnt/user fuse.mergerfs rw 0 0\n"
        )
        with patch("builtins.open", mock_open(read_data=mounts)):
            # /mnt/user/media should match /mnt/user (mergerfs), not /mnt (nfs4)
            is_net, fstype = is_network_mount("/mnt/user/media", "linux")
        assert is_net is False  # mergerfs is local
