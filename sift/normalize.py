"""Hostname and path normalization — shared between agent and CLI."""
import os
import platform
import socket
from typing import Tuple


def local_hostname() -> str:
    """Return short hostname, stripping FQDN domain suffix."""
    return socket.gethostname().split(".")[0]


def get_source_os() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "darwin"
    else:
        return "linux"


def normalize_path(raw_path: str, source_os: str) -> Tuple[str, str, str]:
    """
    Normalize a file path for storage.

    Returns:
        (path, path_display, drive)
        - path: lowercase, forward slashes, drive-stripped — PRIMARY KEY
        - path_display: original case, forward slashes — for display
        - drive: Windows drive letter uppercase ('C', 'D'), empty string for POSIX
    """
    drive = ""

    if source_os == "windows":
        # Convert backslashes
        display = raw_path.replace("\\", "/")
        # Strip \\?\ long-path prefix if present
        if display.startswith("//?/"):
            display = display[4:]
        # Extract drive letter
        if len(display) >= 2 and display[1] == ":":
            drive = display[0].upper()
            display = display[2:]  # strip "C:" from display
    else:
        display = raw_path

    # path is lowercase version of display
    path = display.lower()

    return path, display, drive


def normalize_path_for_storage(abs_path: str, source_os: str | None = None) -> Tuple[str, str, str]:
    """
    Given an absolute path (already realpath'd), return (path, path_display, drive).
    Handles platform detection automatically if source_os is None.
    """
    if source_os is None:
        source_os = get_source_os()
    return normalize_path(abs_path, source_os)


def safe_path(raw_path: str) -> str:
    """
    Return a path safe for os.stat / open on Windows (adds \\?\\ prefix for long paths).
    No-op on POSIX.
    """
    if get_source_os() != "windows":
        return raw_path
    if raw_path.startswith("\\\\?\\"):
        return raw_path
    abs_path = os.path.abspath(raw_path)
    return "\\\\?\\" + abs_path


def normalize_query_path(user_path: str) -> str:
    """
    Normalize a user-supplied path for use as an API query parameter.
    Expands ~, resolves to absolute, lowercases, uses forward slashes.
    Drive letter is stripped (POSIX behavior; Windows drive stored separately).

    Paths starting with '/', '~', or '.' are resolved normally (relative to
    cwd or home). Bare names like 'users' or 'users/brian' have no cwd
    context in the inventory and are treated as absolute inventory paths
    (i.e. 'users' → '/users').
    """
    p = user_path.strip()
    if p and not p.startswith(("/", "~", ".", os.sep)):
        # Relative name: resolve against CWD
        p = "./" + p
    abs_path = os.path.realpath(os.path.expanduser(p))
    source_os = get_source_os()
    path, _, _ = normalize_path(abs_path, source_os)
    return path
