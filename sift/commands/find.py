"""sift find — search the inventory."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Optional

from sift import client
from sift.commands import print_server_info
from sift.config import get_cli_config
from sift.normalize import local_hostname, normalize_query_path


def _parse_size(size_str: str) -> tuple[Optional[int], Optional[int]]:
    """
    Parse a size filter like +1M, -500k, 100M.
    Returns (min_size, max_size) with None for unconstrained.
    """
    if not size_str:
        return None, None

    sign = None
    s = size_str.strip()
    if s.startswith("+"):
        sign = "+"
        s = s[1:]
    elif s.startswith("-"):
        sign = "-"
        s = s[1:]

    units = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
    if s and s[-1].lower() in units:
        mult = units[s[-1].lower()]
        val = int(float(s[:-1]) * mult)
    else:
        val = int(s)

    if sign == "+":
        return val, None
    elif sign == "-":
        return None, val
    else:
        return val, val


def _parse_mtime(mtime_str: str) -> tuple[Optional[int], Optional[int]]:
    """
    Parse a mtime filter like -7 (within last 7 days), +30 (older than 30 days).
    Returns (min_age_days, max_age_days) — unused for now, converted to timestamps.
    """
    import time

    if not mtime_str:
        return None, None

    s = mtime_str.strip()
    now = time.time()
    day = 86400

    if s.startswith("+"):
        days = int(s[1:])
        # older than N days
        max_ts = int(now - days * day)
        return None, max_ts
    elif s.startswith("-"):
        days = int(s[1:])
        # within last N days
        min_ts = int(now - days * day)
        return min_ts, None
    else:
        days = int(s)
        min_ts = int(now - days * day)
        max_ts = int(now - (days - 1) * day)
        return min_ts, max_ts


def cmd_find(args) -> None:
    print_server_info()
    cli_cfg = get_cli_config()
    host = getattr(args, "host", None) or os.environ.get("SIFT_HOST") or cli_cfg.get("host") or local_hostname()
    all_hosts = getattr(args, "all_hosts", False)

    raw_path = getattr(args, "path", "/") or "/"
    path_prefix = normalize_query_path(raw_path)

    params: dict = {
        "path_prefix": path_prefix,
        "limit": 10000,
    }
    if not all_hosts:
        params["host"] = host

    if getattr(args, "ext", None):
        params["ext"] = args.ext.lstrip(".")

    if getattr(args, "category", None):
        params["category"] = args.category

    if getattr(args, "hash", None):
        params["hash"] = args.hash

    if getattr(args, "duplicates", False):
        params["has_duplicates"] = "true"

    if getattr(args, "name", None):
        params["name"] = args.name

    if getattr(args, "iname", None):
        params["iname"] = args.iname

    size_str = getattr(args, "size", None)
    if size_str:
        min_size, max_size = _parse_size(size_str)
        if min_size is not None:
            params["min_size"] = min_size
        if max_size is not None:
            params["max_size"] = max_size

    # mtime filter is a best-effort: server doesn't directly filter by mtime age,
    # so we filter client-side after receiving results
    mtime_str = getattr(args, "mtime", None)
    mtime_filter: Optional[tuple] = None
    if mtime_str:
        min_ts, max_ts = _parse_mtime(mtime_str)
        mtime_filter = (min_ts, max_ts)

    try:
        entries = client.get("/files", params=params)
    except Exception as e:
        print(f"sift: error: {e}", file=sys.stderr)
        sys.exit(1)

    ls_mode = getattr(args, "ls", False)

    for entry in entries:
        mtime = entry.get("mtime")
        if mtime_filter:
            min_ts, max_ts = mtime_filter
            if min_ts is not None and mtime is not None and mtime < min_ts:
                continue
            if max_ts is not None and mtime is not None and mtime > max_ts:
                continue

        if ls_mode:
            _print_ls(entry)
        else:
            _print_short(entry)


def _print_short(entry: dict) -> None:
    host_val = entry.get("host", "")
    path_display = entry.get("path_display", "")
    drive = entry.get("drive", "")
    size_bytes = entry.get("size_bytes")
    other_hosts = entry.get("other_hosts")

    size_str_out = _format_size(size_bytes) if size_bytes is not None else ""
    drive_prefix = f"{drive}:" if drive else ""
    location = f"{host_val}:{drive_prefix}{path_display}"
    also = f" [also: {other_hosts}]" if other_hosts else ""
    size_part = f" ({size_str_out})" if size_str_out else ""
    print(f"{location}{size_part}{also}")


def _print_ls(entry: dict) -> None:
    """Print one entry in long format: perms  size  date  hash  host:path  [also: ...]"""
    host_val = entry.get("host", "")
    path_display = entry.get("path_display", "")
    drive = entry.get("drive", "")
    size_bytes = entry.get("size_bytes")
    hash_val = entry.get("hash")
    mtime = entry.get("mtime")
    other_hosts = entry.get("other_hosts")

    perm = "-rw-r--r--"
    size_str = f"{size_bytes:>12}" if size_bytes is not None else f"{'':>12}"
    date_str = _fmt_mtime(mtime)
    hash_str = hash_val[:8] if hash_val else "        "
    drive_prefix = f"{drive}:" if drive else ""
    location = f"{host_val}:{drive_prefix}{path_display}"
    also = f"  [also: {other_hosts}]" if other_hosts else ""

    print(f"{perm}  {size_str}  {date_str}  {hash_str}  {location}{also}")


def _fmt_mtime(mtime: Optional[int]) -> str:
    if mtime is None:
        return "          "
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _format_size(n: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}P"
