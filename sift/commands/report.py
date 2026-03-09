"""sift report - datastore report across all hosts."""

from __future__ import annotations

import sys
import time

from sift import client
from sift.commands import get_version
from sift.config import get_server_url


def _fmt_int(n: int) -> str:
    return f"{int(n):,}"


def _fmt_percent(value: float, trim: bool = True) -> str:
    text = f"{value:.1f}"
    if trim and text.endswith(".0"):
        text = text[:-2]
    return f"{text}%"


def _fmt_bytes(n: int) -> str:
    val = float(max(int(n), 0))
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if val < 1024.0:
            if unit == "B":
                return f"{int(val)} B"
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{val:.1f} PB"


def _print_section(title: str) -> None:
    print(title)
    print("-" * len(title))


def _print_kv(rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    key_w = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"{k:<{key_w}} : {v}")


def _print_table(
    headers: list[str], rows: list[list[str]], right_align: set[int] | None = None
) -> None:
    right_align = right_align or set()
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def _fmt(cell: str, i: int, is_header: bool = False) -> str:
        if i in right_align and not is_header:
            return cell.rjust(widths[i])
        return cell.ljust(widths[i])

    header_line = "  ".join(
        _fmt(headers[i], i, is_header=True) for i in range(len(headers))
    )
    sep_line = "  ".join("-" * widths[i] for i in range(len(headers)))
    print(header_line)
    print(sep_line)
    for row in rows:
        print("  ".join(_fmt(row[i], i) for i in range(len(headers))))


def _progress_start(step: int, total: int, label: str) -> None:
    dots = "." * max(1, 44 - len(label))
    print(f"Building report: [{step}/{total}] {label} {dots}", end="", flush=True)


def _progress_done(step: int, total: int, label: str, elapsed: float) -> None:
    del step, total, label
    print(f" done ({elapsed:.1f}s)")


def _fetch(path: str, params: dict | None = None) -> dict:
    payload = client.get(path, params=params)
    if isinstance(payload, dict) and payload.get("status") == "pending":
        detail = payload.get("detail") or "report data is still building"
        print(f"sift: {detail}", file=sys.stderr)
        sys.exit(1)
    return payload


def cmd_report(args) -> None:
    del args

    print()
    print(f"sift server: {get_server_url()}")
    print(f"sift {get_version()}  ·  report scope: all hosts in datastore")
    print()

    total_steps = 7

    label = "inventory totals"
    _progress_start(1, total_steps, label)
    t0 = time.monotonic()
    inventory = _fetch("/stats/report/inventory")
    hosts_payload = client.get("/hosts")
    host_names = sorted(
        [str(h.get("host") or "") for h in hosts_payload if h.get("host")],
        key=lambda h: h.lower(),
    )
    _progress_done(1, total_steps, label, time.monotonic() - t0)

    label = "duplicate aggregates"
    _progress_start(2, total_steps, label)
    t0 = time.monotonic()
    dup = _fetch("/stats/report/duplicates")
    _progress_done(2, total_steps, label, time.monotonic() - t0)

    label = "host-only extra copies"
    _progress_start(3, total_steps, label)
    t0 = time.monotonic()
    host_rows = sorted(
        dup.get("host_only_rows") or [],
        key=lambda r: (
            -int(r.get("extra_bytes") or 0),
            str(r.get("host") or "").lower(),
        ),
    )
    _progress_done(3, total_steps, label, time.monotonic() - t0)

    label = "cross-host (3+ copies, 2+ hosts)"
    _progress_start(4, total_steps, label)
    t0 = time.monotonic()
    cross = dup.get("cross_host_summary") or {}
    _progress_done(4, total_steps, label, time.monotonic() - t0)

    label = "tombstone pressure"
    _progress_start(5, total_steps, label)
    t0 = time.monotonic()
    tomb = _fetch("/stats/report/tombstones")
    _progress_done(5, total_steps, label, time.monotonic() - t0)

    label = "file-size distribution"
    _progress_start(6, total_steps, label)
    t0 = time.monotonic()
    size_distribution = _fetch(
        "/stats/report/size-distribution", params={"fast": "true"}
    )
    _progress_done(6, total_steps, label, time.monotonic() - t0)

    label = "top duplicate opportunities"
    _progress_start(7, total_steps, label)
    t0 = time.monotonic()
    top = dup.get("top_opportunities") or []
    _progress_done(7, total_steps, label, time.monotonic() - t0)

    print()
    _print_section("Inventory Summary")
    total_files = int(inventory.get("total_file_rows") or 0)
    zero_files = int(inventory.get("zero_byte_files") or 0)
    zero_pct = (100.0 * zero_files / total_files) if total_files > 0 else 0.0
    hosts_value = _fmt_int(int(inventory.get("hosts_in_datastore") or 0))
    if 0 < len(host_names) <= 5:
        hosts_value = ", ".join(host_names)
    _print_kv(
        [
            ("hosts in datastore", hosts_value),
            ("total file rows", _fmt_int(total_files)),
            ("total bytes", _fmt_bytes(int(inventory.get("total_bytes") or 0))),
            ("zero-byte files", f"{_fmt_int(zero_files)} ({_fmt_percent(zero_pct)})"),
        ]
    )
    print()

    g = dup.get("global_summary") or {}
    _print_section("Duplicate Summary (Global Criteria)")
    print("criteria: extra copies from intra-host duplicates + cross-host duplicates")
    print("          with >=3 total copies across >=2 hosts")
    print()
    _print_kv(
        [
            ("uniq dup hashes", _fmt_int(int(g.get("uniq_dup_hashes") or 0))),
            ("extra copies", _fmt_int(int(g.get("extra_copies") or 0))),
            (
                "extra bytes",
                _fmt_bytes(int(g.get("extra_bytes") or 0)),
            ),
            (
                "total duplicate bytes",
                _fmt_bytes(int(g.get("gross_duplicate_bytes") or 0)),
            ),
        ]
    )
    print()

    _print_section("Host-Only Extra Copies")
    host_table = []
    for row in host_rows:
        total_b = int(row.get("host_total_bytes") or 0)
        extra_b = int(row.get("extra_bytes") or 0)
        pct = (100.0 * extra_b / total_b) if total_b > 0 else 0.0
        host_table.append(
            [
                str(row.get("host") or ""),
                _fmt_int(int(row.get("uniq_dup_hashes") or 0)),
                _fmt_int(int(row.get("extra_copies") or 0)),
                f"{_fmt_bytes(extra_b)} ({_fmt_percent(pct, trim=False)})",
            ]
        )
    _print_table(
        ["host", "uniq dup hashes", "extra copies", "extra bytes (%)"],
        host_table,
        right_align={1, 2, 3},
    )
    print()

    _print_section("Cross-Host Extra Copies")
    print("criteria: >=3 total copies and present on >=2 hosts")
    print()
    _print_kv(
        [
            (
                "qualifying uniq dup hashes",
                _fmt_int(int(cross.get("qualifying_uniq_dup_hashes") or 0)),
            ),
            (
                "qualifying file copies",
                _fmt_int(int(cross.get("qualifying_file_copies") or 0)),
            ),
            ("extra copies", _fmt_int(int(cross.get("extra_copies") or 0))),
            ("extra bytes", _fmt_bytes(int(cross.get("extra_bytes") or 0))),
            (
                "total duplicate bytes",
                _fmt_bytes(int(cross.get("gross_duplicate_bytes") or 0)),
            ),
        ]
    )
    print()

    _print_section("Tombstone Pressure")
    print("definition: rows currently eligible for `sift trim --deleted` under")
    print("            covering complete-scan rules")
    print()
    hosts_pressure = list(tomb.get("hosts_with_pressure") or [])
    pressure_count = int(tomb.get("hosts_with_pressure_count") or 0)
    host_total = int(tomb.get("hosts_in_datastore") or 0)
    if pressure_count <= 5 and pressure_count > 0:
        host_pressure_label = ", ".join(hosts_pressure)
    elif pressure_count == host_total and pressure_count > 0:
        host_pressure_label = f"all {pressure_count}"
    else:
        host_pressure_label = _fmt_int(pressure_count)

    top_host = tomb.get("top_host")
    top_host_rows = int(tomb.get("top_host_rows") or 0)
    top_host_label = f"{top_host} ({_fmt_int(top_host_rows)})" if top_host else "none"
    _print_kv(
        [
            (
                "eligible tombstone rows",
                _fmt_int(int(tomb.get("eligible_tombstone_rows") or 0)),
            ),
            (
                "eligible tombstone bytes",
                _fmt_bytes(int(tomb.get("eligible_tombstone_bytes") or 0)),
            ),
            ("hosts with tombstone pressure", host_pressure_label),
            ("top host by tombstone files", top_host_label),
        ]
    )
    print()

    _print_section("File Size Distribution")
    size_rows = []
    for row in size_distribution.get("buckets") or []:
        size_rows.append(
            [
                str(row.get("bucket") or ""),
                _fmt_int(int(row.get("files") or 0)),
                _fmt_percent(float(row.get("pct_of_files") or 0.0), trim=False),
            ]
        )
    _print_table(
        ["bucket", "files", "pct"],
        size_rows,
        right_align={0, 1, 2},
    )
    print()

    _print_section("Top Duplicate Opportunities")
    top_rows = []
    for row in top:
        top_rows.append(
            [
                str(row.get("rank") or ""),
                _fmt_bytes(int(row.get("extra_bytes") or 0)),
                _fmt_int(int(row.get("copies") or 0)),
                _fmt_int(int(row.get("hosts") or 0)),
                str(row.get("file_category") or "other"),
                str(row.get("sample_filename") or ""),
            ]
        )
    _print_table(
        ["rank", "extra bytes", "copies", "hosts", "type", "sample filename"],
        top_rows,
        right_align={0, 1, 2, 3},
    )
