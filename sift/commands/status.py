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


def _restore_root_case(root_path: str | None, sample_display_path: str | None) -> str:
    """Best-effort restoration of root path casing using a sample path_display."""
    if not root_path:
        return "?"
    if root_path == "/" or not sample_display_path:
        return root_path

    root_parts = root_path.split("/")
    display_parts = sample_display_path.split("/")

    # Both are absolute POSIX-style paths in the API model, so index 0 is "".
    if not root_parts or not display_parts or root_parts[0] != "" or display_parts[0] != "":
        return root_path

    restored = [""]
    for i in range(1, len(root_parts)):
        rp = root_parts[i]
        if i >= len(display_parts):
            return root_path
        dp = display_parts[i]
        if dp.lower() != rp.lower():
            return root_path
        restored.append(dp)

    out = "/".join(restored)
    return out or "/"


def _display_scan_root(host: str, root_path: str | None) -> str:
    """Resolve display-cased scan root using files.path_display as source of truth."""
    if not root_path:
        return "?"
    if root_path == "/":
        return "/"

    try:
        rows = client.get("/files", params={"host": host, "path_prefix": root_path, "limit": 1})
        sample = rows[0]["path_display"] if rows else None
        return _restore_root_case(root_path, sample)
    except Exception:
        return root_path


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
        f"{_human_size(overview.get('wasted_bytes'))} duplicated"
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

    scanning = {r["host"] for r in runs if r.get("status") == "running"}

    if hosts:
        rows = []
        for h in hosts:
            host = h["host"]

            last = "scanning..." if host in scanning else _fmt_dt(h.get("last_scan_at"))
            root = _display_scan_root(host, h.get("last_scan_root"))

            rows.append({
                "host": host,
                "files": f"{h.get('total_files', 0):,}",
                "size": _human_size(h.get('total_bytes')),
                "hashed": f"{h.get('total_hashed', 0):,}",
                "last_scan": last,
                "scan_root": root,
            })

        host_w = max(len("host"), max(len(r["host"]) for r in rows))
        files_w = max(len("files"), max(len(r["files"]) for r in rows))
        size_w = max(len("size"), max(len(r["size"]) for r in rows))
        hashed_w = max(len("hashed"), max(len(r["hashed"]) for r in rows))
        last_w = max(len("last scan"), max(len(r["last_scan"]) for r in rows))

        print(
            f"  {'host':<{host_w}}  {'files':>{files_w}}  {'size':>{size_w}}"
            f"  {'hashed':>{hashed_w}}  {'last scan':<{last_w}}  scan root"
        )
        print(
            f"  {'-' * host_w}  {'-' * files_w}  {'-' * size_w}"
            f"  {'-' * hashed_w}  {'-' * last_w}  {'-' * len('scan root')}"
        )

        for r in rows:
            print(
                f"  {r['host']:<{host_w}}  {r['files']:>{files_w}}  {r['size']:>{size_w}}"
                f"  {r['hashed']:>{hashed_w}}  {r['last_scan']:<{last_w}}  {r['scan_root']}"
            )
        print()

    verbose = getattr(args, "verbose", False)
    if verbose and runs:
        print("recent scans")
        for r in runs:
            print(
                f"  [{r['id']}] {r['host']}:{r['root_path']}"
                f"  {r['status']}"
                f"  {_fmt_dt(r.get('started_at'))}"
            )
