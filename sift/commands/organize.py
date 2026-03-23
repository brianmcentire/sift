"""sift organize — generate a shell script to reorganize donor files to match
a model host's directory structure.

Reads file inventories from the sift datastore (no filesystem access needed
for planning).  For each file in the model, finds the best match among local
donor directories using hash comparison and path-similarity scoring, then
emits mv/cp/mkdir commands.  Whole-directory moves are collapsed when every
file in a donor dir maps to the same target dir.

Output goes to stdout; progress and summary go to stderr.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sift import client
from sift.commands import extract_drive_path, parse_host_path, print_server_info, resolve_host
from sift.config import get_cli_config
from sift.normalize import local_hostname, normalize_query_path


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FileOp:
    model_rel_path: str  # relative path in model (display casing)
    source_path: str  # full path_display of donor file
    target_path: str  # full target path
    op: str  # "mv" or "cp"
    size_bytes: int
    donor_idx: int


@dataclass
class DirMove:
    source_dir: str
    target_dir: str
    file_count: int


@dataclass
class Plan:
    dir_moves: list[DirMove] = field(default_factory=list)
    file_ops: list[FileOp] = field(default_factory=list)
    already_in_place: int = 0
    already_in_place_bytes: int = 0
    missing: list[tuple[str, int]] = field(default_factory=list)  # (rel_path, size)
    unhashed: int = 0
    model_total: int = 0
    model_total_bytes: int = 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def cmd_organize(args) -> None:
    print_server_info()
    cli_cfg = get_cli_config()
    _user_host = os.environ.get("SIFT_HOST") or cli_cfg.get("host")
    default_host = resolve_host(_user_host) if _user_host else local_hostname()
    local_host = local_hostname()
    is_tty = sys.stderr.isatty()

    # --- Parse model spec ---
    model_host, model_norm = parse_host_path(args.model, default_host)
    model_drive, model_path = extract_drive_path(model_norm)
    model_label = args.model

    # --- Parse target ---
    target_real = os.path.realpath(os.path.expanduser(args.target))
    target_query = normalize_query_path(args.target)

    # --- Parse donors ---
    donor_reals = []
    donor_queries = []
    for d in args.donors:
        donor_reals.append(os.path.realpath(os.path.expanduser(d)))
        donor_queries.append(normalize_query_path(d))

    use_move = args.mode == "move"

    # --- Collision checks ---
    _status(is_tty, "Checking paths for collisions...")
    _validate_paths(model_host, model_path, target_real, target_query,
                    donor_reals, donor_queries, local_host)
    _status(is_tty, "  Paths OK.\n")

    # --- Fetch model inventory ---
    _status(is_tty, f"Fetching model inventory ({model_label})...")
    model_entries = _fetch_inventory(model_host, model_path, model_drive)
    if not model_entries:
        print("sift organize: error: model has no files in datastore", file=sys.stderr)
        sys.exit(2)
    _status(is_tty, f"  Model: {len(model_entries):,} files\n")

    # --- Fetch donor inventories ---
    all_donor_entries: list[list[dict]] = []
    total_donor_files = 0
    for i, (dq, dr) in enumerate(zip(donor_queries, donor_reals)):
        _status(is_tty, f"Fetching donor {i + 1}/{len(donor_queries)} ({dr})...")
        entries = _fetch_inventory(local_host, dq, "")
        all_donor_entries.append(entries)
        total_donor_files += len(entries)
        _status(is_tty, f"  Donor {i + 1}: {len(entries):,} files\n")
    _status(is_tty, f"  Total donor files: {total_donor_files:,}\n")

    # --- Fetch target inventory (for "already in place" detection) ---
    _status(is_tty, f"Fetching target inventory ({target_real})...")
    target_entries = _fetch_inventory(local_host, target_query, "")
    _status(is_tty, f"  Target: {len(target_entries):,} existing files\n")

    # --- Build plan ---
    _status(is_tty, "Building plan...")
    plan = _build_plan(
        model_entries, all_donor_entries, target_entries,
        model_path, target_real, donor_reals, use_move, is_tty,
    )
    _status(is_tty, "  Plan complete.\n")

    # --- Collapse directories ---
    if use_move and plan.file_ops:
        _status(is_tty, "Detecting directory-level moves...")
        _collapse_directories(plan, all_donor_entries, donor_reals, donor_queries)
        dir_file_count = sum(dm.file_count for dm in plan.dir_moves)
        _status(
            is_tty,
            f"  {len(plan.dir_moves):,} directory moves"
            f" ({dir_file_count:,} files collapsed)\n" if plan.dir_moves
            else "  No directory-level collapses found.\n",
        )

    # --- Print summary to stderr ---
    _print_summary(plan, model_label, target_real, donor_reals, use_move)

    # --- Generate script to stdout ---
    _status(is_tty, "Writing script to stdout...\n")
    _generate_script(plan, model_label, target_real, donor_reals, use_move)

    has_missing = len(plan.missing) > 0
    sys.exit(1 if has_missing else 0)


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


def _validate_paths(
    model_host: str,
    model_path: str,
    target_real: str,
    target_query: str,
    donor_reals: list[str],
    donor_queries: list[str],
    local_host: str,
) -> None:
    target_n = target_real.rstrip("/")

    for i, dr in enumerate(donor_reals):
        donor_n = dr.rstrip("/")

        # Target inside donor
        if target_n == donor_n or target_n.startswith(donor_n + "/"):
            print(
                f"sift organize: error: target ({target_real}) is inside "
                f"donor ({dr})",
                file=sys.stderr,
            )
            sys.exit(2)

        # Donor inside target
        if donor_n.startswith(target_n + "/"):
            print(
                f"sift organize: error: donor ({dr}) is inside "
                f"target ({target_real})",
                file=sys.stderr,
            )
            sys.exit(2)

    # Donor overlap warning
    for i in range(len(donor_reals)):
        for j in range(i + 1, len(donor_reals)):
            a = donor_reals[i].rstrip("/")
            b = donor_reals[j].rstrip("/")
            if a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                print(
                    f"sift organize: warning: donors overlap: {donor_reals[i]} "
                    f"and {donor_reals[j]}",
                    file=sys.stderr,
                )

    # Model on local host overlapping donor or target
    if model_host.lower() == local_host.lower():
        model_n = model_path.rstrip("/")
        if target_query.rstrip("/").startswith(model_n) or model_n.startswith(
            target_query.rstrip("/")
        ):
            print(
                f"sift organize: error: model path overlaps target "
                f"(both on {local_host})",
                file=sys.stderr,
            )
            sys.exit(2)
        for dq in donor_queries:
            dq_n = dq.rstrip("/")
            if dq_n.startswith(model_n) or model_n.startswith(dq_n):
                print(
                    f"sift organize: error: model path overlaps a donor "
                    f"(both on {local_host})",
                    file=sys.stderr,
                )
                sys.exit(2)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def _fetch_inventory(host: str, path: str, drive: str) -> list[dict]:
    params: dict = {
        "path_prefix": path,
        "host": host,
        "lite": "true",
        "limit": 1_000_000,
    }
    if drive:
        params["drive"] = drive
    entries = client.get("/files", params=params)
    if isinstance(entries, dict) and entries.get("status") == "pending":
        raise RuntimeError(entries.get("detail", "Index is still building"))
    if not isinstance(entries, list):
        return []
    # Client-side drive filter for multi-drive hosts
    if drive:
        entries = [e for e in entries if e.get("drive", "").upper() == drive.upper()]
    return entries


# ---------------------------------------------------------------------------
# Plan building
# ---------------------------------------------------------------------------


def _compute_relative_path(path_display: str, base_path_lower: str) -> str:
    """Compute relative path from a file's path_display, stripping the base prefix.

    Comparison is case-insensitive (cross-OS), but the returned path preserves
    the original casing from path_display.
    """
    base = base_path_lower.rstrip("/")
    pd_lower = path_display.lower()
    if base == "/" or base == "":
        # Full drive/root scan — strip leading slash
        return path_display.lstrip("/")
    if pd_lower.startswith(base + "/"):
        return path_display[len(base) + 1:]
    # Shouldn't happen, but fall back to full path
    return path_display.lstrip("/")


def _trailing_match_count(model_segments: list[str], donor_segments: list[str]) -> int:
    """Count matching path segments from the right (case-insensitive)."""
    count = 0
    for m, d in zip(reversed(model_segments), reversed(donor_segments)):
        if m.lower() == d.lower():
            count += 1
        else:
            break
    return count


def _build_plan(
    model_entries: list[dict],
    all_donor_entries: list[list[dict]],
    target_entries: list[dict],
    model_base_path: str,
    target_real: str,
    donor_reals: list[str],
    use_move: bool,
    is_tty: bool,
) -> Plan:
    plan = Plan()
    plan.model_total = len(model_entries)
    plan.model_total_bytes = sum(e.get("size_bytes") or 0 for e in model_entries)

    model_base_lower = model_base_path.lower()

    # Build hash → [(donor_idx, entry)] lookup
    _status(is_tty, "  Indexing donor files by hash...")
    hash_to_donors: dict[str, list[tuple[int, dict]]] = {}
    for idx, entries in enumerate(all_donor_entries):
        for e in entries:
            h = e.get("hash")
            if h:
                hash_to_donors.setdefault(h, []).append((idx, e))
    donor_hash_count = len(hash_to_donors)
    _status(is_tty, f" {donor_hash_count:,} unique hashes\n")

    # Build target hash+relpath set for "already in place" detection
    _status(is_tty, "  Indexing target files...")
    target_query_lower = normalize_query_path(target_real).rstrip("/")
    target_in_place: dict[str, set[str]] = {}  # hash → set of relative paths
    for e in target_entries:
        h = e.get("hash")
        pd = e.get("path_display") or ""
        if h and pd:
            rel = _compute_relative_path(pd, target_query_lower)
            target_in_place.setdefault(h, set()).add(rel.lower())
    _status(is_tty, f" {len(target_in_place):,} unique hashes in target\n")

    # Track consumed donor files (for move mode)
    consumed: set[tuple[int, str]] = set()  # (donor_idx, path_lower)

    # Match model files to donors
    total = len(model_entries)
    matched = 0
    _status(is_tty, f"  Matching {total:,} model files to donors...\n")
    report_interval = max(1, total // 20)  # report every ~5%

    for i, entry in enumerate(model_entries):
        if is_tty and i > 0 and i % report_interval == 0:
            pct = i * 100 // total
            sys.stderr.write(
                f"\r\x1b[2K  Matching: {i:,}/{total:,} ({pct}%)"
                f" — {plan.already_in_place:,} in place,"
                f" {matched:,} matched,"
                f" {len(plan.missing):,} missing"
            )
            sys.stderr.flush()

        h = entry.get("hash")
        size = entry.get("size_bytes") or 0
        pd = entry.get("path_display") or ""

        if not h:
            plan.unhashed += 1
            continue

        rel_path = _compute_relative_path(pd, model_base_lower)
        rel_path_lower = rel_path.lower()

        # Check if already in place in target
        if h in target_in_place and rel_path_lower in target_in_place[h]:
            plan.already_in_place += 1
            plan.already_in_place_bytes += size
            continue

        # Find best donor
        candidates = hash_to_donors.get(h)
        if not candidates:
            plan.missing.append((rel_path, size))
            continue

        model_segments = rel_path.split("/")

        best_score = -1
        best_donor_idx = len(donor_reals)  # worse than any real index
        best_entry = None

        for donor_idx, donor_entry in candidates:
            donor_pd = donor_entry.get("path_display") or ""
            donor_segments = donor_pd.strip("/").split("/")
            score = _trailing_match_count(model_segments, donor_segments)
            # Higher score wins; on tie, lower donor_idx wins
            if (score, -donor_idx) > (best_score, -best_donor_idx):
                best_score = score
                best_donor_idx = donor_idx
                best_entry = donor_entry

        donor_pd = best_entry.get("path_display") or ""
        # Build the real filesystem source path from donor_real + relative part
        donor_query_base = normalize_query_path(donor_reals[best_donor_idx]).rstrip("/")
        donor_rel = _compute_relative_path(donor_pd, donor_query_base)
        source_path = os.path.join(donor_reals[best_donor_idx], donor_rel)

        target_path = os.path.join(target_real, rel_path)

        # Determine op: mv or cp
        consumed_key = (best_donor_idx, donor_pd.lower())
        if use_move and consumed_key not in consumed:
            op = "mv"
            consumed.add(consumed_key)
        else:
            op = "cp"

        plan.file_ops.append(FileOp(
            model_rel_path=rel_path,
            source_path=source_path,
            target_path=target_path,
            op=op,
            size_bytes=size,
            donor_idx=best_donor_idx,
        ))
        matched += 1

    if is_tty:
        sys.stderr.write(
            f"\r\x1b[2K  Matching complete: {plan.already_in_place:,} in place,"
            f" {matched:,} matched,"
            f" {len(plan.missing):,} missing,"
            f" {plan.unhashed:,} unhashed\n"
        )
        sys.stderr.flush()

    return plan


# ---------------------------------------------------------------------------
# Directory collapse
# ---------------------------------------------------------------------------


def _collapse_directories(
    plan: Plan,
    all_donor_entries: list[list[dict]],
    donor_reals: list[str],
    donor_queries: list[str],
) -> None:
    """Detect donor dirs where ALL files are being moved to the same target dir.

    Replace individual file moves with a single directory move.
    Only applies to 'mv' operations.
    """
    # Count total files per donor directory (from full inventory)
    donor_dir_counts: dict[tuple[int, str], int] = {}
    for idx, entries in enumerate(all_donor_entries):
        dq_base = donor_queries[idx].rstrip("/")
        for e in entries:
            pd = e.get("path_display") or ""
            rel = _compute_relative_path(pd, dq_base)
            parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
            full_parent = os.path.join(donor_reals[idx], parent) if parent else donor_reals[idx]
            donor_dir_counts[(idx, full_parent)] = donor_dir_counts.get((idx, full_parent), 0) + 1

    # Group mv file_ops by (source_parent, target_parent)
    from collections import defaultdict
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, op in enumerate(plan.file_ops):
        if op.op != "mv":
            continue
        src_parent = os.path.dirname(op.source_path)
        tgt_parent = os.path.dirname(op.target_path)
        groups[(src_parent, tgt_parent)].append(i)

    collapse_indices: set[int] = set()

    for (src_dir, tgt_dir), op_indices in groups.items():
        if len(op_indices) < 2:
            continue

        # All ops from this src_dir must go to same tgt_dir
        # (already guaranteed by grouping key)

        # Find the donor_idx for this group
        sample_op = plan.file_ops[op_indices[0]]
        donor_idx = sample_op.donor_idx

        # Check: do we account for ALL files in this donor directory?
        total_in_dir = donor_dir_counts.get((donor_idx, src_dir), 0)
        if total_in_dir != len(op_indices):
            continue  # some files in this dir aren't being moved → can't collapse

        # Check: no cp ops from same source dir (those files are needed elsewhere)
        has_cp_from_same_dir = any(
            op.op == "cp" and os.path.dirname(op.source_path) == src_dir
            for op in plan.file_ops
        )
        if has_cp_from_same_dir:
            continue

        plan.dir_moves.append(DirMove(
            source_dir=src_dir,
            target_dir=tgt_dir,
            file_count=len(op_indices),
        ))
        collapse_indices.update(op_indices)

    # Remove collapsed file ops
    if collapse_indices:
        plan.file_ops = [op for i, op in enumerate(plan.file_ops) if i not in collapse_indices]


# ---------------------------------------------------------------------------
# Script generation
# ---------------------------------------------------------------------------


def _shell_quote(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


def _human_size(n: int) -> str:
    val = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            if unit == "B":
                return f"{val:.0f} {unit}"
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} PB"


def _generate_script(
    plan: Plan,
    model_label: str,
    target_real: str,
    donor_reals: list[str],
    use_move: bool,
) -> None:
    w = sys.stdout.write
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    w("#!/bin/bash\n")
    w("set -euo pipefail\n")
    w(f"# sift organize — generated {now}\n")
    w(f"# Model: {model_label} ({plan.model_total:,} files)\n")
    w(f"# Target: {target_real}\n")
    for i, dr in enumerate(donor_reals):
        w(f"# Donor {i + 1}: {dr}\n")
    w("\n")

    # Directory moves
    if plan.dir_moves:
        dir_file_total = sum(dm.file_count for dm in plan.dir_moves)
        w(f"# --- Directory moves ({len(plan.dir_moves):,} dirs,"
          f" {dir_file_total:,} files) ---\n")
        # Sort by target path for readability
        for dm in sorted(plan.dir_moves, key=lambda d: d.target_dir):
            w(f"mkdir -p {_shell_quote(os.path.dirname(dm.target_dir))}\n")
            w(f"mv {_shell_quote(dm.source_dir)} {_shell_quote(dm.target_dir)}\n")
        w("\n")

    # File operations
    mv_count = sum(1 for op in plan.file_ops if op.op == "mv")
    cp_count = sum(1 for op in plan.file_ops if op.op == "cp")
    if plan.file_ops:
        parts = []
        if mv_count:
            parts.append(f"{mv_count:,} moves")
        if cp_count:
            parts.append(f"{cp_count:,} copies")
        w(f"# --- File operations ({', '.join(parts)}) ---\n")

        # Sort by target path so mkdir -p calls are grouped
        sorted_ops = sorted(plan.file_ops, key=lambda o: o.target_path)
        seen_dirs: set[str] = set()
        for op in sorted_ops:
            tgt_dir = os.path.dirname(op.target_path)
            if tgt_dir not in seen_dirs:
                seen_dirs.add(tgt_dir)
                w(f"mkdir -p {_shell_quote(tgt_dir)}\n")
            w(f"{op.op} {_shell_quote(op.source_path)} {_shell_quote(op.target_path)}\n")
        w("\n")

    # Summary
    dir_file_total = sum(dm.file_count for dm in plan.dir_moves)
    w("# --- Summary ---\n")
    w(f"# Model files:      {plan.model_total:>10,}\n")
    w(f"# Already in place: {plan.already_in_place:>10,}\n")
    if plan.dir_moves:
        w(f"# Directory moves:  {len(plan.dir_moves):>10,}"
          f" ({dir_file_total:,} files)\n")
    w(f"# File moves:       {mv_count:>10,}\n")
    if cp_count:
        w(f"# File copies:      {cp_count:>10,}\n")
    if plan.unhashed:
        w(f"# Unhashed (skip):  {plan.unhashed:>10,}\n")
    w(f"# Missing:          {len(plan.missing):>10,}\n")

    # Missing files
    if plan.missing:
        w("#\n")
        w("# --- Missing files (need transfer, e.g. rsync) ---\n")
        plan.missing.sort(key=lambda x: x[0])
        for rel_path, size in plan.missing:
            w(f"# {rel_path} ({_human_size(size)})\n")


# ---------------------------------------------------------------------------
# Summary (stderr)
# ---------------------------------------------------------------------------


def _print_summary(
    plan: Plan,
    model_label: str,
    target_real: str,
    donor_reals: list[str],
    use_move: bool,
) -> None:
    w = sys.stderr.write
    mv_count = sum(1 for op in plan.file_ops if op.op == "mv")
    cp_count = sum(1 for op in plan.file_ops if op.op == "cp")
    dir_file_total = sum(dm.file_count for dm in plan.dir_moves)
    matched = mv_count + cp_count + dir_file_total

    w(f"\nsift organize: {model_label} → {target_real}\n\n")
    w(f"  Model files:      {plan.model_total:>10,}  ({_human_size(plan.model_total_bytes)})\n")
    w(f"  Already in place: {plan.already_in_place:>10,}  ({_human_size(plan.already_in_place_bytes)})\n")
    if plan.dir_moves:
        w(f"  Directory moves:  {len(plan.dir_moves):>10,}  ({dir_file_total:,} files)\n")
    w(f"  File moves:       {mv_count:>10,}\n")
    if cp_count:
        w(f"  File copies:      {cp_count:>10,}\n")
    if plan.unhashed:
        w(f"  Unhashed (skip):  {plan.unhashed:>10,}\n")
    missing_size = sum(s for _, s in plan.missing)
    w(f"  Missing:          {len(plan.missing):>10,}  ({_human_size(missing_size)})\n")

    total_actionable = plan.model_total - plan.unhashed
    if total_actionable > 0:
        coverage = (plan.already_in_place + matched) * 100.0 / total_actionable
        w(f"\n  Coverage: {coverage:.1f}% of model files found in donors or target\n")
    w("\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status(is_tty: bool, msg: str) -> None:
    if is_tty:
        sys.stderr.write(msg)
        sys.stderr.flush()
