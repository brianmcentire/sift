"""sift status — show server and host status."""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from sift import client
from sift.commands import get_version, print_server_info


def _fmt_dt(dt_str: str | None) -> str:
    if not dt_str:
        return "never"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return dt_str or "?"


def _human_size(n: int | None) -> str:
    if n is None:
        return "0B"
    for unit in ("B", "K", "M", "G", "T", "P"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n:.1f}P"


def cmd_status(args) -> None:
    print_server_info()
    filter_host = getattr(args, "host", None)

    # Fetch overview stats
    try:
        overview = client.get("/stats/overview")
    except Exception as e:
        print(f"sift: cannot reach server: {e}", file=sys.stderr)
        sys.exit(1)

    print("=== Sift Server Status ===")
    print(f"  Version:         {get_version()}")
    print(f"  Total files:     {overview.get('total_files', 0):,}")
    print(f"  Total hosts:     {overview.get('total_hosts', 0)}")
    print(f"  Unique hashes:   {overview.get('unique_hashes', 0):,}")
    print(f"  Duplicate sets:  {overview.get('duplicate_sets', 0):,}")

    wasted = overview.get("wasted_bytes")
    total = overview.get("total_bytes")
    print(f"  Wasted bytes:    {_human_size(wasted)}")
    print(f"  Total bytes:     {_human_size(total)}")
    print()

    # Fetch hosts
    try:
        hosts = client.get("/hosts")
    except Exception as e:
        print(f"sift: cannot fetch hosts: {e}", file=sys.stderr)
        return

    if filter_host:
        hosts = [h for h in hosts if h["host"] == filter_host]

    if not hosts:
        print("No hosts found.")
        return

    print("=== Hosts ===")
    for h in hosts:
        print(f"  {h['host']}")
        print(f"    Last scan:  {_fmt_dt(h.get('last_scan_at'))}")
        print(f"    Scan root:  {h.get('last_scan_root') or '?'}")
        print(f"    Files:      {h.get('total_files', 0):,}")
        print(f"    Total size: {_human_size(h.get('total_bytes'))}")
        print(f"    Hashed:     {h.get('total_hashed', 0):,}")
        print()

    # Recent scan runs
    try:
        runs = client.get("/scan-runs", params={"limit": 10})
    except Exception:
        return

    if filter_host:
        runs = [r for r in runs if r["host"] == filter_host]

    if runs:
        print("=== Recent Scan Runs ===")
        for r in runs[:10]:
            print(
                f"  [{r['id']}] {r['host']}:{r['root_path']}"
                f"  {r['status']}"
                f"  started {_fmt_dt(r.get('started_at'))}"
            )
