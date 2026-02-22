"""Exclusion rules and volatile file detection."""
from __future__ import annotations

import fnmatch
import math
import os
import time
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
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset([
    # VCS
    ".git", ".svn", ".hg", ".bzr",
    # Python tooling
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".hypothesis",
    # Python virtual environments
    ".venv", "venv",
    # Node
    "node_modules", ".yarn", ".npm", ".pnpm-store",
    # JVM build/package caches
    ".gradle", ".m2",
    # Rust
    ".cargo",
    # .NET
    ".nuget",
    # Caches
    "Caches", "Cache", ".cache",
    # Linux thumbnail and font caches
    ".thumbnails", "fontconfig", "mesa_shader_cache",
    # macOS system
    ".Trash", ".trash", ".Spotlight-V100", ".fseventsd", ".DocumentRevisions-V100",
    ".TemporaryItems", ".DS_Store",
    # macOS app internals
    "PhotoLibraryThumbnails",
    # macOS metadata injected into zip archives
    "__MACOSX",
    # Unix system
    "lost+found", "proc", "sys", "dev", "run",
    # Linux package systems
    "snap", ".var",
    # Windows
    "$RECYCLE.BIN", "System Volume Information",
    # Browser / Electron internal storage (Chrome, Edge, VS Code, Slack, Discord, etc.)
    "CacheStorage", "Code Cache", "GPUCache", "ShaderCache", "DawnCache",
    "blob_storage", "IndexedDB", "Service Worker",
])

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


def is_excluded_dir(dirpath: str, dirname: str, source_os: str) -> bool:
    """
    Return True if this directory should be skipped entirely.
    dirpath is the full path of the directory; dirname is its basename.
    """
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
