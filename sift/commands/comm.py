"""sift comm — compare two directories, three-column output."""

from __future__ import annotations

import os
import sys
from typing import Optional

from sift import client
from sift.commands import extract_drive_path, parse_host_path, print_server_info, resolve_host
from sift.config import get_cli_config
from sift.normalize import local_hostname


def cmd_comm(args) -> None:
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
    hash_mode = getattr(args, "hashes", False)
    depth = getattr(args, "depth", None)
    suppress_1 = getattr(args, "suppress_1", False)
    suppress_2 = getattr(args, "suppress_2", False)
    suppress_3 = getattr(args, "suppress_3", False)
    yes = getattr(args, "yes", False)

    try:
        entries1 = _fetch_entries(host1, path1, drive1, recursive, depth)
        entries2 = _fetch_entries(host2, path2, drive2, recursive, depth)
    except Exception as e:
        print(f"sift: error: {e}", file=sys.stderr)
        sys.exit(2)

    if hash_mode:
        lines = _compare_hashes(entries1, entries2, path1, path2, suppress_1, suppress_2, suppress_3)
    else:
        lines = _compare_filenames(entries1, entries2, path1, path2, suppress_1, suppress_2, suppress_3)

    # Large output warning
    if len(lines) > 1000 and sys.stdout.isatty() and not yes:
        print(
            f"Warning: {len(lines)} lines of output. Continue? [y/N]",
            file=sys.stderr,
        )
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)
        if answer != "y":
            sys.exit(0)

    for line in lines:
        print(line)


def _fetch_entries(host: str, path: str, drive: str, recursive: bool, depth: Optional[int]) -> list[dict]:
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
        # Apply depth filter client-side if specified
        if depth is not None:
            base = path.rstrip("/")
            filtered = []
            for e in (entries if isinstance(entries, list) else []):
                ep = e.get("path", "")
                if ep.lower().startswith(base.lower() + "/"):
                    rel = ep[len(base) + 1:]
                    if rel.count("/") < depth:
                        filtered.append(e)
            entries = filtered
    else:
        d = depth if depth is not None else 1
        params = {
            "path": path,
            "host": host,
            "depth": d,
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


def _compare_filenames(
    entries1: list[dict],
    entries2: list[dict],
    path1: str,
    path2: str,
    suppress_1: bool,
    suppress_2: bool,
    suppress_3: bool,
) -> list[str]:
    map1 = _build_rel_map(entries1, path1)
    map2 = _build_rel_map(entries2, path2)
    all_keys = sorted(set(map1.keys()) | set(map2.keys()))

    lines = []
    for rel in all_keys:
        in1 = rel in map1
        in2 = rel in map2

        if in1 and not in2:
            if not suppress_1:
                lines.append(rel)
        elif in2 and not in1:
            if not suppress_2:
                lines.append(f"\t{rel}")
        else:
            if not suppress_3:
                # Dirs in common: no hash comparison possible
                if map1[rel].get("entry_type") == "dir":
                    lines.append(f"\t\t{rel}")
                    continue
                h1 = map1[rel].get("hash")
                h2 = map2[rel].get("hash")
                if h1 is None and h2 is None:
                    lines.append(f"\t\t{rel} [no-hash]")
                elif h1 != h2:
                    lines.append(f"\t\t{rel} [differs]")
                else:
                    lines.append(f"\t\t{rel}")

    return lines


def _fmt_hash(h: Optional[str]) -> str:
    if h is None:
        return "????????"
    return h[:8]


def _compare_hashes(
    entries1: list[dict],
    entries2: list[dict],
    path1: str,
    path2: str,
    suppress_1: bool,
    suppress_2: bool,
    suppress_3: bool,
) -> list[str]:
    map1 = _build_rel_map(entries1, path1)
    map2 = _build_rel_map(entries2, path2)

    # Build hash → [relative paths] maps (files only — dirs have no hash)
    hash_files1: dict[str, list[str]] = {}
    hash_files2: dict[str, list[str]] = {}

    for rel, entry in map1.items():
        h = entry.get("hash")
        if h:
            hash_files1.setdefault(h, []).append(rel)

    for rel, entry in map2.items():
        h = entry.get("hash")
        if h:
            hash_files2.setdefault(h, []).append(rel)

    all_hashes = sorted(set(hash_files1.keys()) | set(hash_files2.keys()))
    lines = []

    for h in all_hashes:
        in1 = h in hash_files1
        in2 = h in hash_files2
        prefix = _fmt_hash(h)

        if in1 and not in2:
            if not suppress_1:
                files = sorted(hash_files1[h])
                extra = f" (+{len(files) - 1} extra copies)" if len(files) > 1 else ""
                lines.append(f"{prefix} {files[0]}{extra}")
        elif in2 and not in1:
            if not suppress_2:
                files = sorted(hash_files2[h])
                extra = f" (+{len(files) - 1} extra copies)" if len(files) > 1 else ""
                lines.append(f"\t{prefix} {files[0]}{extra}")
        else:
            if not suppress_3:
                files1 = sorted(hash_files1[h])
                extra = f" (+{len(files1) - 1} extra copies)" if len(files1) > 1 else ""
                lines.append(f"\t\t{prefix} {files1[0]}{extra}")

    return lines
