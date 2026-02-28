"""Exclusion rules and volatile file detection."""

from __future__ import annotations

import fnmatch
import math
import os
import re
import subprocess
import time
from functools import lru_cache
from typing import Optional

# ---------------------------------------------------------------------------
# Exclusion lists informed by:
#   Backblaze default exclusions  https://help.backblaze.com/hc/en-us/articles/217666538
#   Arq Backup exclusions          https://www.arqbackup.com/documentation/arq7/English.lproj/excludeFiles.html
#   CrashPlan default exclusions   https://help.it.ox.ac.uk/crashplan-default-file-exclusions-from-backup
#   Microsoft VSS documentation    https://learn.microsoft.com/en-us/windows/win32/vss/excluding-files-from-shadow-copies
#   Restic / Borg community lists  https://forum.restic.net/t/what-gnu-linux-directories-to-exclude-from-backups/6653
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Excluded directory names (leaf name only)
# ---------------------------------------------------------------------------
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    [
        # VCS
        ".git",
        ".svn",
        ".hg",
        ".bzr",
        # Python tooling
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        # Python virtual environments
        ".venv",
        "venv",
        # Node
        "node_modules",
        ".yarn",
        ".npm",
        ".pnpm-store",
        # JVM build/package caches
        ".gradle",
        ".m2",
        # Rust
        ".cargo",
        # .NET
        ".nuget",
        # Caches
        "Caches",
        "Cache",
        ".cache",
        # Linux thumbnail and font caches
        ".thumbnails",
        "fontconfig",
        "mesa_shader_cache",
        # macOS system
        ".Trash",
        ".trash",
        ".Spotlight-V100",
        ".fseventsd",
        ".DocumentRevisions-V100",
        ".TemporaryItems",
        ".DS_Store",
        # macOS app internals
        "PhotoLibraryThumbnails",
        # macOS metadata injected into zip archives
        "__MACOSX",
        # Unix system
        "lost+found",
        "proc",
        "sys",
        "dev",
        "run",
        # Linux package systems
        "snap",
        ".var",
        # Windows
        "$RECYCLE.BIN",
        "System Volume Information",
        # Browser / Electron internal storage (Chrome, Edge, VS Code, Slack, Discord, etc.)
        "CacheStorage",
        "Code Cache",
        "GPUCache",
        "ShaderCache",
        "DawnCache",
        "blob_storage",
        "IndexedDB",
        "Service Worker",
    ]
)

# ---------------------------------------------------------------------------
# Excluded path prefixes (lowercased, forward slashes)
# ---------------------------------------------------------------------------
EXCLUDED_PATH_PREFIXES_POSIX: tuple[str, ...] = (
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/tmp",
    "/snap",
    "/var/run",
    "/var/lock",
    "/var/tmp",
    "/var/cache",
)

# ---------------------------------------------------------------------------
# macOS: iCloud-managed directory subtrees (matched as path segments)
# Reading ANY file in these trees can trigger on-demand iCloud downloads,
# even when st_blocks > 0. Exclude the entire tree rather than playing
# whack-a-mole with extensions.
# ---------------------------------------------------------------------------
EXCLUDED_DARWIN_DIR_SEGMENTS: tuple[str, ...] = (
    "/library/mail",  # Apple Mail — .mbox bundles, attachments, etc.
    "/library/messages",  # iMessage/SMS attachments
    "/library/mobile documents",  # iCloud Drive per-app containers
    "/library/com.apple.deviceactivity",  # Screen Time / DeviceActivity cloud shards
)

# Windows: drive letter excluded paths are handled separately at scan time
EXCLUDED_PATH_PREFIXES_WINDOWS: tuple[str, ...] = (
    "windows/system32",
    "windows/syswow64",
    "windows/winsxs",
    "windows/temp",
    "$recycle.bin",
    "system volume information",
)

# ---------------------------------------------------------------------------
# Excluded filenames (exact, case-insensitive)
# ---------------------------------------------------------------------------
EXCLUDED_FILENAMES: frozenset[str] = frozenset(
    """
    .ds_store thumbs.db desktop.ini
    pagefile.sys hiberfil.sys swapfile.sys
    """.split()
)

# ---------------------------------------------------------------------------
# Excluded extensions (lowercase, no dot)
# ---------------------------------------------------------------------------
EXCLUDED_EXTENSIONS: frozenset[str] = frozenset(
    """
    tmp temp swp swo lock lck pid
    part crdownload
    """.split()
)

# ---------------------------------------------------------------------------
# Volatile extensions — skip hashing if recently modified
# ---------------------------------------------------------------------------
VOLATILE_EXTENSIONS: frozenset[str] = frozenset(
    """
    vmdk vdi vhd vhdx qcow2 img
    ost nst pst
    """.split()
)

# ---------------------------------------------------------------------------
# Volatile directory patterns (fnmatch against full path, lowercased)
# ---------------------------------------------------------------------------
VOLATILE_DIR_PATTERNS: tuple[str, ...] = (
    "*/virtualbox vms/*",
    "*/vmware/*",
    "*/parallels/*",
    "*/utm/*",
    "*/docker/*",
    "*/.docker/*",
    "*/containers/*",
    "*/.local/share/gnome-boxes/*",
)


@lru_cache(maxsize=1)
def _is_unraid() -> bool:
    """Return True if the current host is an Unraid server."""
    return os.path.exists("/etc/unraid-version")


_UNRAID_DISK_RE = re.compile(r"^/mnt/disk\d+(/|$)")


def _is_unraid_disk_path(dirpath: str) -> bool:
    """Return True if dirpath is an Unraid raw disk mount (/mnt/diskN/...)."""
    return bool(_UNRAID_DISK_RE.match(dirpath))


def is_excluded_dir(
    dirpath: str,
    dirname: str,
    source_os: str,
    allow_unraid_disks: bool = False,
) -> bool:
    """
    Return True if this directory should be skipped entirely.
    dirpath is the full path of the directory; dirname is its basename.
    allow_unraid_disks: if True, skip the Unraid /mnt/diskN exclusion (--yolo).
    """
    # UNC paths (\\server\share) — network mounts excluded by default
    if dirpath.startswith("\\\\"):
        return True

    # Leaf name check (case-insensitive)
    if dirname.lower() in {n.lower() for n in EXCLUDED_DIR_NAMES}:
        return True

    # Path prefix check
    path_lower = dirpath.lower().replace("\\", "/")
    if source_os == "windows":
        # Strip drive letter for comparison
        if len(path_lower) >= 2 and path_lower[1] == ":":
            path_lower = path_lower[2:]
        for prefix in EXCLUDED_PATH_PREFIXES_WINDOWS:
            if path_lower.startswith("/" + prefix) or path_lower == prefix:
                return True
    else:
        for prefix in EXCLUDED_PATH_PREFIXES_POSIX:
            if path_lower == prefix or path_lower.startswith(prefix + "/"):
                return True

    # macOS: exclude iCloud-managed directory trees (Mail, Messages, iCloud Drive
    # app containers). Any file in these trees can trigger an on-demand download.
    if source_os == "darwin":
        for seg in EXCLUDED_DARWIN_DIR_SEGMENTS:
            if seg in path_lower:
                return True

    # Unraid: exclude raw disk mounts (/mnt/diskN) unless --yolo was passed.
    # These duplicate the content already visible under /mnt/user (mergerfs union).
    if not allow_unraid_disks and source_os != "windows" and _is_unraid():
        if _is_unraid_disk_path(dirpath):
            return True

    return False


def is_excluded_file(filename: str, ext: str) -> bool:
    """
    Return True if this file should be completely skipped (not recorded at all).
    """
    if filename.lower() in EXCLUDED_FILENAMES:
        return True
    if ext in EXCLUDED_EXTENSIONS:
        return True
    return False


def is_volatile_active(
    filepath: str,
    filename: str,
    ext: str,
    mtime: float,
    source_os: str,
    threshold_days: int = 30,
) -> bool:
    """
    Return True if this file is volatile AND recently modified (should skip hashing).
    Volatile = volatile extension OR in a volatile dir pattern.
    Recently modified = mtime within threshold_days.
    """
    is_volatile = False

    if ext in VOLATILE_EXTENSIONS:
        is_volatile = True
    else:
        path_lower = filepath.lower().replace("\\", "/")
        # Strip drive letter on Windows
        if source_os == "windows" and len(path_lower) >= 2 and path_lower[1] == ":":
            path_lower = path_lower[2:]
        for pat in VOLATILE_DIR_PATTERNS:
            if fnmatch.fnmatch(path_lower, pat):
                is_volatile = True
                break

    if not is_volatile:
        return False

    # Check if recently modified
    age_seconds = time.time() - mtime
    threshold_seconds = threshold_days * 86400
    return age_seconds < threshold_seconds


# Windows OneDrive Files On-Demand: file exists as a cloud placeholder.
# Reading it triggers a download — same problem as macOS APFS dataless stubs.
# FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
# FILE_ATTRIBUTE_RECALL_ON_OPEN        = 0x40000  (older OneDrive versions)
_WIN_RECALL_FLAGS = 0x400000 | 0x40000


def is_windows_cloud_placeholder(st_file_attributes: int, source_os: str) -> bool:
    """Return True for Windows OneDrive Files On-Demand placeholders.

    These are cloud stubs — the file appears locally but bytes live in OneDrive.
    Hashing would trigger a download. Record with skipped_reason='windows_cloud_placeholder'.
    """
    if source_os != "windows":
        return False
    return bool(st_file_attributes & _WIN_RECALL_FLAGS)


# ---------------------------------------------------------------------------
# Network filesystem detection
# ---------------------------------------------------------------------------
NETWORK_FS_TYPES: frozenset[str] = frozenset(
    [
        # Traditional network filesystems
        "nfs",
        "nfs4",
        "cifs",
        "smbfs",
        "afp",
        "afs",
        "ncpfs",
        "9p",
        # Remote FUSE (known-remote whitelist)
        "fuse.sshfs",
        "fuse.rclone",
        "fuse.s3fs",
        "fuse.gcsfuse",
        "fuse.nfs",
    ]
)


@lru_cache(maxsize=1)
def _build_mount_registry(source_os: str) -> dict[str, str]:
    """Build a {mount_point: fstype} map from system mount info.

    Linux: parse /proc/mounts
    macOS: parse `mount` command output
    Windows: check drive types via kernel32.GetDriveTypeW

    Returns empty dict on failure (safe default — no exclusions).
    """
    registry: dict[str, str] = {}

    if source_os == "linux":
        try:
            with open("/proc/mounts", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3:
                        mount_point = parts[1]
                        fstype = parts[2]
                        registry[mount_point] = fstype
        except OSError:
            pass

    elif source_os == "darwin":
        try:
            result = subprocess.run(
                ["mount"], capture_output=True, text=True, timeout=10
            )
            # Format: <device> on <mount_point> (<fstype>, <options>)
            for line in result.stdout.splitlines():
                m = re.match(r".+ on (.+) \((\w[\w.]*)", line)
                if m:
                    mount_point = m.group(1)
                    fstype = m.group(2)
                    registry[mount_point] = fstype
        except (OSError, subprocess.TimeoutExpired):
            pass

    elif source_os == "windows":
        try:
            import ctypes

            get_drive_type = ctypes.windll.kernel32.GetDriveTypeW  # type: ignore[attr-defined]
            DRIVE_REMOTE = 4
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                drive = f"{letter}:\\"
                if get_drive_type(drive) == DRIVE_REMOTE:
                    registry[drive] = "network"
        except (AttributeError, OSError):
            pass

    return registry


def is_network_mount(dirpath: str, source_os: str) -> tuple[bool, str]:
    """Check if dirpath sits on a network filesystem.

    Returns (is_network, fstype_string). Uses longest-prefix match
    against the mount registry to find the correct mount point.
    """
    registry = _build_mount_registry(source_os)
    if not registry:
        return False, ""

    if source_os == "windows":
        # Windows: check if drive letter matches a network drive
        if len(dirpath) >= 2 and dirpath[1] == ":":
            drive = dirpath[:3].upper()
            if drive in registry:
                return True, registry[drive]
        return False, ""

    # POSIX: find longest matching mount point prefix
    best_mount = ""
    best_fstype = ""
    for mount_point, fstype in registry.items():
        if dirpath == mount_point or dirpath.startswith(mount_point + "/"):
            if len(mount_point) > len(best_mount):
                best_mount = mount_point
                best_fstype = fstype

    if best_mount and best_fstype in NETWORK_FS_TYPES:
        return True, best_fstype

    return False, ""


def is_sparse_file(st_size: int, st_blocks: int, source_os: str) -> bool:
    """Return True for large sparse files (VM disk images, container stores, etc.).

    st_blocks is in 512-byte units on POSIX. A file is considered sparse when
    it is >= 1 GB in logical size but less than 10% of that is actually
    allocated on disk. Skipped on Windows where st_blocks is unreliable.
    """
    if source_os == "windows":
        return False
    if st_size < 1_000_000_000:  # ignore sub-1GB files
        return False
    actual_bytes = st_blocks * 512
    return actual_bytes < st_size // 10
