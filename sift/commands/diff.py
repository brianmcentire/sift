"""sift diff — compare two directories in the inventory."""

from __future__ import annotations

import os
import sys
from typing import Optional

from sift import client
from sift.commands import extract_drive_path, parse_host_path, print_server_info, resolve_host
from sift.config import get_cli_config
from sift.normalize import local_hostname


def cmd_diff(args) -> None:
    print_server_info()
    cli_cfg = get_cli_config()
    _user_host = (
        os.environ.get("SIFT_HOST")
        or cli_cfg.get("host")
    )
    default_host = resolve_host(_user_host) if _user_host else local_hostname()

    host1, raw1 = parse_host_path(args.dir1, default_host)
    host2, raw2 = parse_host_path(args.dir2, default_host)
    drive1, path1 = extract_drive_path(raw1)
    drive2, path2 = extract_drive_path(raw2)
    recursive = getattr(args, "recursive", False)

    cross_host = (host1 != host2)

    try:
        entries1 = _fetch_entries(host1, path1, drive1, recursive)
        entries2 = _fetch_entries(host2, path2, drive2, recursive)
    except Exception as e:
        print(f"sift: error: {e}", file=sys.stderr)
        sys.exit(2)

    map1 = _build_rel_map(entries1, path1)
    map2 = _build_rel_map(entries2, path2)

    all_keys = sorted(set(map1.keys()) | set(map2.keys()))
    has_diff = False

    for rel in all_keys:
        in1 = rel in map1
        in2 = rel in map2

        if in1 and not in2:
            parent, basename = _split_parent_basename(rel)
            display_dir = _display_path(host1, drive1, path1, parent, cross_host)
            print(f"Only in {display_dir}: {basename}")
            has_diff = True
        elif in2 and not in1:
            parent, basename = _split_parent_basename(rel)
            display_dir = _display_path(host2, drive2, path2, parent, cross_host)
            print(f"Only in {display_dir}: {basename}")
            has_diff = True
        else:
            # Both present — dirs in common: skip (no hash to compare)
            if map1[rel].get("entry_type") == "dir":
                continue
            h1 = map1[rel].get("hash")
            h2 = map2[rel].get("hash")
            if h1 is None and h2 is None:
                p1 = _display_file(host1, drive1, path1, rel, cross_host)
                p2 = _display_file(host2, drive2, path2, rel, cross_host)
                print(f"Files {p1} and {p2} no-hash")
                has_diff = True
            elif h1 != h2:
                p1 = _display_file(host1, drive1, path1, rel, cross_host)
                p2 = _display_file(host2, drive2, path2, rel, cross_host)
                print(f"Files {p1} and {p2} differ")
                has_diff = True

    sys.exit(1 if has_diff else 0)


def _fetch_entries(host: str, path: str, drive: str, recursive: bool) -> list[dict]:
    if recursive:
        params: dict = {
            "path_prefix": path,
            "host": host,
            "lite": "true",
            "limit": 1_000_000,
        }
        if drive:
            params["drive"] = drive
        entries = client.get("/files", params=params)
    else:
        params = {
            "path": path,
            "host": host,
            "depth": 1,
        }
        if drive:
            params["drive"] = drive
        entries = client.get("/files/ls", params=params)

    if isinstance(entries, dict) and entries.get("status") == "pending":
        raise RuntimeError(entries.get("detail", "Duplicate index is still building"))

    return entries if isinstance(entries, list) else []


def _build_rel_map(entries: list[dict], base_path: str) -> dict[str, dict]:
    """Build relative_path → entry map. Includes both files and dir entries."""
    result = {}
    base = base_path.rstrip("/")
    base_lower = base.lower()

    for entry in entries:
        entry_type = entry.get("entry_type", "file")
        full_path = entry.get("path") or ""

        if entry_type == "dir" and not full_path:
            # Depth-1 dir entries from /files/ls: use segment as the relative key
            seg = entry.get("segment", "")
            if seg:
                result[seg + "/"] = entry
            continue

        full_path = full_path.rstrip("/")
        if not full_path:
            continue

        if full_path.lower().startswith(base_lower + "/"):
            rel = full_path[len(base) + 1:]
        elif full_path.lower() == base_lower:
            continue
        else:
            rel = full_path

        result[rel] = entry

    return result


def _split_parent_basename(rel_path: str) -> tuple[str, str]:
    """Split relative path into (parent_dir, basename). Strips trailing slash."""
    rel = rel_path.rstrip("/")
    if "/" in rel:
        idx = rel.rfind("/")
        return (rel[:idx], rel[idx + 1:])
    return ("", rel)


def _display_path(host: str, drive: str, base_path: str, rel_parent: str, cross_host: bool) -> str:
    """Format a directory path for 'Only in ...' output."""
    full = base_path.rstrip("/")
    if rel_parent:
        full = f"{full}/{rel_parent}"
    drive_prefix = f"{drive}:" if drive else ""
    if cross_host:
        return f"{host}:{drive_prefix}{full}"
    return f"{drive_prefix}{full}"


def _display_file(host: str, drive: str, base_path: str, rel_path: str, cross_host: bool) -> str:
    """Format a file path for 'Files ... differ' output."""
    rel = rel_path.rstrip("/")
    full = f"{base_path.rstrip('/')}/{rel}"
    drive_prefix = f"{drive}:" if drive else ""
    if cross_host:
        return f"{host}:{drive_prefix}{full}"
    return f"{drive_prefix}{full}"
