"""sift du — disk usage summary."""

from __future__ import annotations

import os
import sys
from typing import Optional

from sift import client
from sift.commands import print_config_hint, print_server_info, resolve_host
from sift.config import get_cli_config
from sift.normalize import local_hostname, normalize_query_path


def _human_size(n: Optional[int]) -> str:
    if n is None:
        return "0"
    val = float(n)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if abs(val) < 1024:
            return f"{val:.1f}{unit}" if unit != "B" else f"{int(val)}B"
        val /= 1024
    return f"{val:.1f}P"


def _fetch_tree_entries(
    path: str,
    host: str,
    drive: str = "",
    min_size: int = 0,
    depth: int = 1,
) -> list[dict]:
    """Fetch tree children + dup metrics and merge into ls-like entries."""
    all_items: list[dict] = []
    cursor = None
    page_size = 2000
    while True:
        params = {"limit": page_size}
        if cursor is not None:
            params["cursor"] = cursor
        resp = client.get(
            "/tree/children",
            params={
                "path": path,
                "host": host,
                "drive": drive,
                "depth": depth,
                **params,
            },
        )
        items = resp.get("items") or []
        all_items.extend(items)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
        if cursor is None:
            break

    if not all_items:
        return []

    segments = [e.get("segment") for e in all_items if e.get("segment")]
    metrics: dict = {}
    chunk_size = 200
    for i in range(0, len(segments), chunk_size):
        seg_chunk = segments[i : i + chunk_size]
        metrics_resp = client.get(
            "/tree/dup-metrics",
            params={
                "path": path,
                "host": host,
                "drive": drive,
                "depth": depth,
                "min_size": min_size,
                "segments": seg_chunk,
            },
        )
        metrics.update((metrics_resp or {}).get("metrics") or {})
    merged: list[dict] = []
    for entry in all_items:
        seg = entry.get("segment")
        m = metrics.get(seg, {})
        merged.append(
            {
                **entry,
                "dup_count": m.get("dup_count", 0),
                "dup_hash_count": m.get("dup_hash_count", 0),
                "other_hosts": m.get("other_hosts"),
                "is_hard_linked": bool(m.get("is_hard_linked", False)),
                "file_count": m.get("file_count", entry.get("file_count")),
                "total_bytes": m.get("total_bytes", entry.get("total_bytes")),
            }
        )
    return merged


def cmd_du(args) -> None:
    print_server_info()
    cli_cfg = get_cli_config()
    _user_host = (
        getattr(args, "host", None)
        or os.environ.get("SIFT_HOST")
        or cli_cfg.get("host")
    )
    host = resolve_host(_user_host) if _user_host else local_hostname()
    all_hosts = getattr(args, "all_hosts", False)

    raw_path = getattr(args, "path", "/") or "/"
    path_prefix = normalize_query_path(raw_path)

    human = getattr(args, "human", False)
    summarize = getattr(args, "summarize", False)
    depth = getattr(args, "depth", 1)
    sort_by = getattr(args, "sort", "size")
    duplicates_only = getattr(args, "duplicates_only", False)
    by_category = getattr(args, "by_category", False)

    if summarize:
        depth = 0

    if by_category:
        _du_by_category(
            None if all_hosts else host, path_prefix, human, duplicates_only
        )
        return

    if all_hosts:
        try:
            hosts_resp = client.get("/hosts")
        except Exception as e:
            print(f"sift: cannot reach server: {e}", file=sys.stderr)
            print_config_hint()
            sys.exit(1)
        host_names = [h["host"] for h in hosts_resp]
    else:
        host_names = [host]

    entries = []
    for h in host_names:
        try:
            entries.extend(
                _fetch_tree_entries(
                    path=path_prefix,
                    host=h,
                    min_size=0,
                    depth=max(depth, 1),
                )
            )
        except Exception as e:
            print(f"sift: error querying {h}: {e}", file=sys.stderr)

    if summarize:
        total = sum(e.get("total_bytes") or 0 for e in entries)
        size_str = _human_size(total) if human else str(total)
        print(f"{size_str}\t{path_prefix}")
        return

    if duplicates_only:
        entries = [e for e in entries if (e.get("dup_count") or 0) > 0]

    # Sort
    if sort_by == "size":
        entries.sort(key=lambda e: e.get("total_bytes") or 0, reverse=True)
    else:
        entries.sort(key=lambda e: e.get("segment", ""))

    for entry in entries:
        size_bytes = entry.get("total_bytes")
        size_str = _human_size(size_bytes) if human else str(size_bytes or 0)
        segment = entry.get("segment", "")
        entry_type = entry.get("entry_type", "file")
        full_path = path_prefix.rstrip("/") + "/" + segment
        if entry_type == "dir":
            full_path += "/"
        print(f"{size_str}\t{full_path}")

    # Total
    total = sum(e.get("total_bytes") or 0 for e in entries)
    total_str = _human_size(total) if human else str(total)
    print(f"{total_str}\ttotal")


def _du_by_category(
    host: Optional[str], path_prefix: str, human: bool, duplicates_only: bool
) -> None:
    """Show disk usage broken down by file category."""
    params: dict = {
        "path_prefix": path_prefix,
        "limit": 100000,
    }
    if host:
        params["host"] = host
    if duplicates_only:
        params["has_duplicates"] = "true"

    try:
        entries = client.get("/files", params=params)
    except Exception as e:
        print(f"sift: error: {e}", file=sys.stderr)
        sys.exit(1)

    # Server returns a dict (not a list) when duplicate index is pending (HTTP 202).
    if isinstance(entries, dict) and entries.get("status") == "pending":
        print(
            f"sift: {entries.get('detail', 'Duplicate index is still building')}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Aggregate by category
    by_cat: dict[str, int] = {}
    for entry in entries:
        cat = entry.get("file_category") or "other"
        size = entry.get("size_bytes") or 0
        by_cat[cat] = by_cat.get(cat, 0) + size

    # Sort by size descending
    rows = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
    for cat, total in rows:
        size_str = _human_size(total) if human else str(total)
        print(f"{size_str}\t{cat}")

    total_all = sum(v for _, v in rows)
    total_str = _human_size(total_all) if human else str(total_all)
    print(f"{total_str}\ttotal")
