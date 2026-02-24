"""sift status — show server and host status."""
from __future__ import annotations

import sys
from datetime import datetime

from sift import client
from sift.commands import get_version, print_server_info


def _fmt_dt(dt_str: str | None) -> str:
    if not dt_str:
        return "never"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
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

    try:
        overview = client.get("/stats/overview")
    except Exception as e:
        print(f"sift: cannot reach server: {e}", file=sys.stderr)
        sys.exit(1)

    print(
        f"sift {get_version()}  ·  "
        f"{overview.get('total_hosts', 0)} hosts  ·  "
        f"{overview.get('total_files', 0):,} files  ·  "
        f"{_human_size(overview.get('total_bytes'))}  ·  "
        f"{overview.get('duplicate_sets', 0):,} dup sets  ·  "
        f"{_human_size(overview.get('wasted_bytes'))} wasted"
    )
    print()

    try:
        hosts = client.get("/hosts")
    except Exception as e:
        print(f"sift: cannot fetch hosts: {e}", file=sys.stderr)
        return

    if filter_host:
        hosts = [h for h in hosts if h["host"] == filter_host]

    try:
        runs = client.get("/scan-runs", params={"limit": 10})
    except Exception:
        runs = []

    if filter_host:
        runs = [r for r in runs if r["host"] == filter_host]

    scanning = {r["host"] for r in runs if r["status"] == "running"}

    if hosts:
        name_w = max(len(h["host"]) for h in hosts)
        print(f"  {'host':<{name_w}}  {'files':>8}  {'size':>7}  {'hashed':>8}  {'last scan':<17}  scan root")
        print(f"  {'-'*name_w}  {'------':>8}  {'-------':>7}  {'------':>8}  {'-'*17}  ---------")
        for h in hosts:
            last = "scanning..." if h["host"] in scanning else _fmt_dt(h.get("last_scan_at"))
            print(
                f"  {h['host']:<{name_w}}"
                f"  {h.get('total_files', 0):>8,}"
                f"  {_human_size(h.get('total_bytes')):>7}"
                f"  {h.get('total_hashed', 0):>8,}"
                f"  {last:<17}"
                f"  {h.get('last_scan_root') or '?'}"
            )
        print()

    if runs:
        print("recent scans")
        for r in runs:
            print(
                f"  [{r['id']}] {r['host']}:{r['root_path']}"
                f"  {r['status']}"
                f"  {_fmt_dt(r.get('started_at'))}"
            )
