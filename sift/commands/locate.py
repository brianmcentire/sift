"""sift locate — search the inventory by filename pattern."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Optional

from sift import client
from sift.commands import print_server_info, resolve_host
from sift.config import get_cli_config
from sift.normalize import local_hostname


def cmd_locate(args) -> None:
    print_server_info()
    cli_cfg = get_cli_config()

    _user_host = (
        getattr(args, "host", None)
        or os.environ.get("SIFT_HOST")
        or cli_cfg.get("host")
    )
    all_hosts = getattr(args, "all_hosts", False)
    host = resolve_host(_user_host) if _user_host else local_hostname()

    pattern = args.pattern
    case_insensitive = getattr(args, "case_insensitive", False)
    count_only = getattr(args, "count", False)
    long_fmt = getattr(args, "long", False)

    limit = getattr(args, "limit", 1000)
    if limit is None:
        limit = 1000
    if getattr(args, "all_results", False):
        limit = 0
    if limit == 0:
        limit = 1_000_000

    params: dict = {
        "limit": limit,
        "lite": "true",
    }

    if case_insensitive:
        params["iname"] = pattern
    else:
        params["name"] = pattern

    if not all_hosts:
        params["host"] = host

    try:
        entries = client.get("/files", params=params)
    except Exception as e:
        print(f"sift: error: {e}", file=sys.stderr)
        sys.exit(1)

    # Pending index check
    if isinstance(entries, dict) and entries.get("status") == "pending":
        print(
            f"sift: {entries.get('detail', 'Duplicate index is still building')}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Filter out hidden hosts in --all-hosts mode unless --include-hidden
    if all_hosts and not getattr(args, "include_hidden", False):
        try:
            hidden_hosts = {h["host"] for h in client.get("/hosts") if h.get("hidden")}
        except Exception:
            hidden_hosts = set()
        if hidden_hosts:
            entries = [e for e in entries if e.get("host") not in hidden_hosts]

    if count_only:
        print(len(entries))
        return

    for entry in entries:
        host_val = entry.get("host", "")
        path_display = entry.get("path_display", "")
        drive = entry.get("drive", "")
        drive_prefix = f"{drive}:" if drive else ""

        full_path = f"{drive_prefix}{path_display}"

        if long_fmt:
            size_bytes = entry.get("size_bytes")
            mtime = entry.get("mtime")
            size_str = _human_size(size_bytes) if size_bytes is not None else "     ?"
            date_str = _fmt_mtime(mtime)
            if all_hosts:
                print(f"{size_str} {date_str} {host_val}:{full_path}")
            else:
                print(f"{size_str} {date_str} {full_path}")
        else:
            if all_hosts:
                print(f"{host_val}:{full_path}")
            else:
                print(f"{full_path}")

    # Truncation warning
    if len(entries) >= limit and limit < 1_000_000:
        print(
            f"(showing {limit} results, use --limit 0 for all)",
            file=sys.stderr,
        )



def _human_size(n: Optional[int]) -> str:
    if n is None:
        return "     ?"
    val = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if val < 1024:
            if unit == "B":
                return f"{val:>5.0f}{unit}"
            return f"{val:>5.1f}{unit}"
        val /= 1024
    return f"{val:>5.1f}P"


def _fmt_mtime(mtime: Optional[int]) -> str:
    if mtime is None:
        return "          "
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")
