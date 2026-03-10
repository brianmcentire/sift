"""sift status — show server and host status."""

from __future__ import annotations

import sys
from datetime import datetime

from sift import client
from sift.commands import print_config_hint, print_server_info
from sift.normalize import local_hostname


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
    val = float(n)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if abs(val) < 1024:
            return f"{val:.1f}{unit}" if unit != "B" else f"{int(val)}B"
        val /= 1024
    return f"{val:.1f}P"


def cmd_status(args) -> None:
    print()
    print_server_info()
    filter_host = getattr(args, "host", None)
    show_stats = getattr(args, "stats", False)
    show_roots = getattr(args, "showroots", False)

    try:
        hosts = client.get("/hosts")
    except Exception as e:
        print(f"sift: cannot reach server: {e}", file=sys.stderr)
        print_config_hint()
        sys.exit(1)

    resolved_filter_host = filter_host
    if filter_host:
        _input = str(filter_host)
        if _input.lower() in ("localhost", "127.0.0.1"):
            _input = local_hostname()
        needle = _input.lower()
        canonical = next(
            (h.get("host") for h in hosts if str(h.get("host", "")).lower() == needle),
            None,
        )
        if canonical:
            resolved_filter_host = canonical
        hosts = [h for h in hosts if str(h.get("host", "")).lower() == needle]
    else:
        # Keep default status focused on currently indexed hosts.
        # Hosts that have been fully trimmed (0 files) still appear in -v
        # scan-run history below.
        hosts = [h for h in hosts if h.get("total_files", 0) > 0]

    # Compute totals from /hosts response (no full-table scan needed)
    total_hosts = len(hosts)
    total_files = sum(h.get("total_files", 0) for h in hosts)
    total_bytes = sum(h.get("total_bytes") or 0 for h in hosts)

    summary = (
        f"{total_hosts} hosts  ·  {total_files:,} files  ·  {_human_size(total_bytes)}"
    )

    if show_stats:
        try:
            overview = client.get("/stats/overview")
            summary += (
                f"  ·  {overview.get('duplicate_sets', 0):,} dup sets  ·  "
                f"{_human_size(overview.get('wasted_bytes'))} duplicated"
            )
        except Exception as e:
            summary += f"  ·  (dup stats unavailable: {e})"

    # Check aggregate freshness
    stale_aggregates: list[dict] = []
    try:
        agg_rows = client.get("/aggregate-status")
        stale_aggregates = [
            r for r in agg_rows if r.get("status") in ("stale", "building")
        ]
    except Exception:
        pass  # server may be older version without this endpoint

    if stale_aggregates:
        building = any(r.get("status") == "building" for r in stale_aggregates)
        summary += "  ·  dup stats " + ("building" if building else "stale")

    print()
    print(f"  {summary}")
    print()

    try:
        run_params = {"limit": 50 if filter_host else 10}
        if filter_host:
            run_params["host"] = resolved_filter_host
        runs = client.get("/scan-runs", params=run_params)
    except Exception:
        runs = []

    scanning = set()
    seen_hosts = set()
    for r in runs:
        host = r["host"]
        if host not in seen_hosts:
            seen_hosts.add(host)
            if r.get("status") == "running":
                scanning.add(host)

    if hosts:
        rows = []
        for h in hosts:
            host = h["host"]

            last = "scanning..." if host in scanning else _fmt_dt(h.get("last_scan_at"))
            root = h.get("last_scan_root") or "?"

            rows.append(
                {
                    "host": host,
                    "files": f"{h.get('total_files', 0):,}",
                    "size": _human_size(h.get("total_bytes")),
                    "hashed": f"{h.get('total_hashed', 0):,}",
                    "last_scan": last,
                    "scan_root": root,
                }
            )

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

    if show_roots:
        try:
            params = {"host": resolved_filter_host} if filter_host else None
            roots = client.get("/hosts/roots", params=params)
        except Exception as e:
            print(f"sift: cannot fetch roots: {e}", file=sys.stderr)
            roots = []

        if roots:
            root_rows = []
            has_any_drive = False
            for r in roots:
                drive = r.get("drive") or ""
                if drive:
                    has_any_drive = True
                root_rows.append(
                    {
                        "host": r.get("host") or "",
                        "drive": drive,
                        "root": r.get("root_path") or "",
                        "latest": _fmt_dt(r.get("latest_complete_at")),
                    }
                )

            host_w = max(len("host"), max(len(r["host"]) for r in root_rows))
            latest_w = max(
                len("latest complete"), max(len(r["latest"]) for r in root_rows)
            )

            print("  effective complete roots")
            if has_any_drive:
                drive_w = max(len("drive"), max(len(r["drive"]) for r in root_rows))
                print(
                    f"  {'host':<{host_w}}  {'drive':<{drive_w}}"
                    f"  {'latest complete':<{latest_w}}  root"
                )
                print(
                    f"  {'-' * host_w}  {'-' * drive_w}"
                    f"  {'-' * len('latest complete'):<{latest_w}}  {'-' * len('root')}"
                )
                for r in root_rows:
                    drive = r["drive"] or "-"
                    print(
                        f"  {r['host']:<{host_w}}  {drive:<{drive_w}}"
                        f"  {r['latest']:<{latest_w}}  {r['root']}"
                    )
            else:
                print(f"  {'host':<{host_w}}  {'latest complete':<{latest_w}}  root")
                print(
                    f"  {'-' * host_w}  {'-' * len('latest complete'):<{latest_w}}  {'-' * len('root')}"
                )
                for r in root_rows:
                    print(
                        f"  {r['host']:<{host_w}}  {r['latest']:<{latest_w}}  {r['root']}"
                    )
            print()
        else:
            print("  effective complete roots: none")
            print()

    verbose = bool(getattr(args, "verbose", False))

    if verbose and stale_aggregates:
        print("  stale aggregates")
        for r in stale_aggregates:
            key = r.get("key", "?")
            status = r.get("status", "?")
            refreshed = _fmt_dt(r.get("updated_at"))
            note = r.get("note") or ""
            note_str = f"  ({note})" if note else ""
            label = f"{key} [{status}]" if status == "building" else key
            print(f"    {label:<35s} last refreshed {refreshed}{note_str}")
        print()

    if verbose and runs:
        print("  recent scans")
        for r in runs:
            root = r.get("root_path_display") or r["root_path"]
            print(
                f"    [{r['id']}] {r['host']}:{root}"
                f"  {r['status']}"
                f"  {_fmt_dt(r.get('started_at'))}"
            )
