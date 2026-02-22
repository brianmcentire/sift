"""sift ls — list files/directories in the inventory."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Optional

from sift import client
from sift.commands import print_server_info
from sift.config import get_cli_config
from sift.normalize import local_hostname, normalize_query_path


def _human_size(n: Optional[int]) -> str:
    if n is None:
        return "  0B"
    for unit in ("B", "K", "M", "G", "T", "P"):
        if abs(n) < 1024:
            if unit == "B":
                return f"{n:4d}B"
            return f"{n:5.1f}{unit}"
        n /= 1024
    return f"{n:5.1f}P"


def _fmt_size(n: Optional[int], human: bool) -> str:
    if human:
        return _human_size(n)
    return str(n) if n is not None else "0"


def _fmt_mtime(mtime: Optional[int]) -> str:
    if mtime is None:
        return "          "
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _fmt_hash(hash_val: Optional[str], full: bool = False) -> str:
    if not hash_val:
        return " " * (64 if full else 8)
    return hash_val if full else hash_val[:8]


def cmd_ls(args) -> None:
    print_server_info()
    cli_cfg = get_cli_config()

    # Resolve host
    host = getattr(args, "host", None) or os.environ.get("SIFT_HOST") or cli_cfg.get("host") or local_hostname()
    all_hosts = getattr(args, "all_hosts", False)

    # Normalize path
    raw_path = getattr(args, "path", "/") or "/"
    path = normalize_query_path(raw_path)

    # Flags
    full_hash = getattr(args, "full_hash", False)
    long_fmt = getattr(args, "long", False)
    human = getattr(args, "human", False)
    sort_size = getattr(args, "sort_size", False)
    sort_time = getattr(args, "sort_time", False)
    reverse = getattr(args, "reverse", False)
    one_per_line = getattr(args, "one_per_line", False)
    recursive = getattr(args, "recursive", False)
    duplicates_only = getattr(args, "duplicates", False)

    # Determine depth
    depth = 0 if recursive else 1

    if all_hosts:
        # Query each host separately — collect all results
        try:
            hosts_resp = client.get("/hosts")
        except Exception as e:
            print(f"sift: cannot reach server: {e}", file=sys.stderr)
            sys.exit(1)
        host_names = [h["host"] for h in hosts_resp]
    else:
        host_names = [host]

    all_entries = []
    for h in host_names:
        try:
            entries = client.get("/files/ls", params={"path": path, "host": h, "depth": max(depth, 1)})
        except Exception as e:
            print(f"sift: error querying {h}: {e}", file=sys.stderr)
            continue
        for entry in entries:
            entry["_host"] = h
            all_entries.append(entry)

    # If no results, path may point to a file rather than a directory.
    # Re-query the parent and filter for the matching file entry.
    file_lookup = False
    if not all_entries and "/" in path:
        parent, name = path.rsplit("/", 1)
        if name:
            parent = parent or "/"
            for h in host_names:
                try:
                    entries = client.get("/files/ls", params={"path": parent, "host": h, "depth": 1})
                except Exception:
                    continue
                for entry in entries:
                    if (entry.get("entry_type") == "file"
                            and entry.get("segment", "").lower() == name.lower()):
                        entry["_host"] = h
                        all_entries.append(entry)
                        file_lookup = True

    if duplicates_only:
        all_entries = [e for e in all_entries if e.get("dup_count", 0) > 0 or e.get("other_hosts")]

    # Sort
    if sort_size:
        all_entries.sort(key=lambda e: e.get("total_bytes") or 0, reverse=not reverse)
    elif sort_time:
        all_entries.sort(key=lambda e: e.get("mtime") or 0, reverse=not reverse)
    else:
        # Default: dirs first, then alpha
        all_entries.sort(
            key=lambda e: (0 if e["entry_type"] == "dir" else 1, e["segment"]),
            reverse=reverse,
        )

    # Compute totals for header
    total_bytes = sum(e.get("total_bytes") or 0 for e in all_entries)
    total_dups = sum(1 for e in all_entries if e.get("other_hosts"))

    if long_fmt and not file_lookup:
        if total_dups:
            print(f"total {_fmt_size(total_bytes, human)}  ({total_dups} duplicates on other hosts)")
        else:
            print(f"total {_fmt_size(total_bytes, human)}")

    for entry in all_entries:
        _print_entry(entry, long_fmt=long_fmt, human=human, one_per_line=one_per_line, full_hash=full_hash)

    if recursive and all_entries:
        # Recurse into directories
        dirs = [e for e in all_entries if e["entry_type"] == "dir"]
        for d in dirs:
            child_path = path.rstrip("/") + "/" + d["segment"]
            print(f"\n{child_path}:")
            child_args = type("A", (), {
                "path": child_path,
                "host": host,
                "all_hosts": all_hosts,
                "long": long_fmt,
                "human": human,
                "sort_size": sort_size,
                "sort_time": sort_time,
                "reverse": reverse,
                "one_per_line": one_per_line,
                "recursive": recursive,
                "duplicates": duplicates_only,
                "full_hash": full_hash,
            })()
            cmd_ls(child_args)


def _print_entry(entry: dict, long_fmt: bool, human: bool, one_per_line: bool, full_hash: bool = False) -> None:
    segment = entry.get("segment", "")
    entry_type = entry.get("entry_type", "file")
    other_hosts = entry.get("other_hosts")
    also = f"  [also: {other_hosts}]" if other_hosts else ""

    segment_display = entry.get("segment_display") or segment

    if not long_fmt and not one_per_line:
        # Short format
        if entry_type == "file":
            path_display = entry.get("path_display") or ""
            display_name = os.path.basename(path_display) if path_display else segment_display
            if full_hash:
                hash_str = _fmt_hash(entry.get("hash"), full=True)
                print(f"{hash_str}  {display_name}{also}")
            else:
                print(f"{display_name}{also}")
        else:
            print(f"{segment_display}/{also}")
        return

    # Long format
    if entry_type == "dir":
        perm = "drwxr-xr-x"
        size_str = _fmt_size(entry.get("total_bytes"), human)
        date_str = "          "
        hash_str = "        "
        name = segment_display + "/"
        file_count = entry.get("file_count", 0)
        name_display = f"{name}  ({file_count} files)"
    else:
        perm = "-rw-r--r--"
        size_str = _fmt_size(entry.get("size_bytes"), human)
        date_str = _fmt_mtime(entry.get("mtime"))
        hash_str = _fmt_hash(entry.get("hash"), full=full_hash)
        path_display = entry.get("path_display") or ""
        name = os.path.basename(path_display) if path_display else segment
        name_display = name

    print(f"{perm}  {size_str:>8}  {date_str}  {hash_str}  {name_display}{also}")
