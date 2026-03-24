"""sift sets — hash-based set operations."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from sift import client
from sift.commands import extract_drive_path, parse_host_path, print_server_info, resolve_host
from sift.config import get_cli_config
from sift.normalize import local_hostname


def cmd_sets(args) -> None:
    print_server_info()
    cli_cfg = get_cli_config()
    _user_host = os.environ.get("SIFT_HOST") or cli_cfg.get("host")
    default_host = resolve_host(_user_host) if _user_host else local_hostname()

    # --- Parse arguments ---------------------------------------------------
    a_paths_raw = getattr(args, "a_paths", None) or []
    b_paths_raw = getattr(args, "b_paths", None) or []
    positionals = getattr(args, "paths", None) or []
    covered = getattr(args, "covered", None)
    min_size = _parse_size(getattr(args, "min_size", None))
    limit = getattr(args, "n", None)
    summary_only = getattr(args, "summary", False)
    no_summary = getattr(args, "no_summary", False)
    long_fmt = getattr(args, "long", False)
    reverse_mode = getattr(args, "reverse", False)
    common_mode = getattr(args, "common", False)
    json_mode = getattr(args, "json", False)

    if reverse_mode and common_mode:
        print("sift sets: error: --reverse and --common are mutually exclusive", file=sys.stderr)
        sys.exit(2)

    # --- Resolve A and B ---------------------------------------------------
    a_specs, b_mode = _resolve_sets(
        a_paths_raw, b_paths_raw, positionals, covered, default_host,
    )

    if not a_specs:
        print("sift sets: error: no source paths specified", file=sys.stderr)
        sys.exit(2)

    # --- Fetch A entries (full, for file list) -----------------------------
    _progress = sys.stderr.isatty()
    try:
        a_entries: list[dict] = []
        for host, path, drive in a_specs:
            if _progress:
                label = f"{host}:{path}" if host else path
                sys.stderr.write(f"  Fetching source {label} ...\r")
                sys.stderr.flush()
            entries = _fetch_entries(host, path, drive, min_size)
            a_entries.extend(entries)
        if _progress:
            sys.stderr.write("\r\033[2K")
            sys.stderr.flush()
    except Exception as e:
        if _progress:
            sys.stderr.write("\r\033[2K")
            sys.stderr.flush()
        print(f"sift sets: error: {e}", file=sys.stderr)
        sys.exit(2)

    if not a_entries:
        if not no_summary:
            print("sift sets: source has no files.", file=sys.stderr)
        sys.exit(0)

    # --- Build A hash index ------------------------------------------------
    a_hash_index, a_unhashed = _build_hash_index(a_entries)
    a_hashes = set(a_hash_index.keys())
    if _progress:
        sys.stderr.write(
            f"  Source: {len(a_entries):,} files, {len(a_hashes):,} unique hashes\r"
        )
        sys.stderr.flush()

    # --- Fetch B -----------------------------------------------------------
    # --reverse needs full B entries to list B-only files.
    # All other modes POST A's hashes to the server and get back the
    # intersection — much faster than streaming all of B.
    need_b_entries = reverse_mode
    b_complete = False  # do we know ALL of B's hashes?

    try:
        if need_b_entries:
            # Must fetch full B entries for --reverse file list
            if b_mode[0] == "covered":
                print(
                    "sift sets: error: --reverse with --covered is not supported "
                    "(target set too large to enumerate)",
                    file=sys.stderr,
                )
                sys.exit(2)
            b_hashes, b_entries = _fetch_b_entries(b_mode[1], min_size)
            b_complete = True
        elif b_mode[0] == "covered":
            b_hashes, b_entries = _check_covered(
                a_specs, a_hashes, b_mode[1], min_size,
            )
        else:
            b_hashes, b_entries = _check_targets(
                b_mode[1], a_hashes, min_size,
            )
    except Exception as e:
        print(f"sift sets: error: {e}", file=sys.stderr)
        sys.exit(2)

    # --- Set operations ----------------------------------------------------
    a_only_hashes = a_hashes - b_hashes
    b_only_hashes = b_hashes - a_hashes if b_complete else set()
    common_hashes = a_hashes & b_hashes

    # --- Unhashed handling -------------------------------------------------
    unhashed_covered = 0
    unhashed_unverifiable = 0
    unverifiable_entries: list[dict] = []

    if a_unhashed:
        if b_entries is not None:
            b_unhashed_tuples = _build_unhashed_index(
                [e for e in b_entries if not e.get("hash")]
            )
            for entry in a_unhashed:
                key = _unhashed_key(entry)
                if key and key in b_unhashed_tuples:
                    unhashed_covered += 1
                else:
                    unhashed_unverifiable += 1
                    unverifiable_entries.append(entry)
        else:
            # Streaming mode — can't match unhashed files
            unhashed_unverifiable = len(a_unhashed)
            unverifiable_entries = list(a_unhashed)

    # --- Compute stats -----------------------------------------------------
    a_total_files = len(a_entries)
    a_total_size = sum(e.get("size_bytes") or 0 for e in a_entries)
    a_unique_hashes = len(a_hashes)
    a_unhashed_count = len(a_unhashed)

    a_only_files = [e for h in a_only_hashes for e in a_hash_index[h]]
    a_only_size = sum(e.get("size_bytes") or 0 for e in a_only_files)

    common_files_a = [e for h in common_hashes for e in a_hash_index[h]]
    common_size_a = sum(e.get("size_bytes") or 0 for e in common_files_a)

    covered_pct = (
        (len(common_hashes) / a_unique_hashes * 100) if a_unique_hashes else 100.0
    )
    fully_covered = len(a_only_hashes) == 0 and unhashed_unverifiable == 0

    # --- JSON output -------------------------------------------------------
    if json_mode:
        import json as _json

        result = {
            "source": {
                "files": a_total_files,
                "size_bytes": a_total_size,
                "unique_hashes": a_unique_hashes,
                "unhashed": a_unhashed_count,
            },
            "a_only": {
                "hashes": len(a_only_hashes),
                "files": len(a_only_files),
                "size_bytes": a_only_size,
            },
            "b_only_hashes": len(b_only_hashes) if b_complete else None,
            "common": {
                "hashes": len(common_hashes),
                "files_in_a": len(common_files_a),
                "size_bytes": common_size_a,
            },
            "coverage_pct": round(covered_pct, 1),
            "unhashed_covered": unhashed_covered,
            "unhashed_unverifiable": unhashed_unverifiable,
            "fully_covered": fully_covered,
        }
        if not summary_only:
            file_list = _select_file_list(
                reverse_mode, common_mode, a_only_files,
                b_only_hashes, b_entries,
                common_files_a, unverifiable_entries,
            )
            if limit is not None and limit > 0:
                file_list = file_list[:limit]
            json_a_hosts = {h for h, _p, _d in a_specs}
            json_host_map = _fetch_hash_hosts(file_list, exclude_hosts=json_a_hosts)
            result["files"] = [
                {
                    "path": _display_path(e),
                    "size_bytes": e.get("size_bytes"),
                    "hash": e.get("hash"),
                    **({"hosts": json_host_map[e["hash"]].split(",")}
                       if e.get("hash") and e["hash"] in json_host_map else {}),
                }
                for e in file_list
            ]
        print(_json.dumps(result, indent=2))
        sys.exit(0 if fully_covered else 1)

    # --- Summary → stderr --------------------------------------------------
    if not no_summary:
        _print_summary(
            a_specs, b_mode,
            a_total_files, a_total_size, a_unique_hashes, a_unhashed_count,
            len(a_only_hashes), len(a_only_files), a_only_size,
            len(b_only_hashes) if b_complete else None,
            len(common_hashes), len(common_files_a), common_size_a,
            covered_pct,
            unhashed_covered, unhashed_unverifiable,
            fully_covered,
        )

    # --- File list → stdout ------------------------------------------------
    if not summary_only:
        file_list = _select_file_list(
            reverse_mode, common_mode, a_only_files,
            b_only_hashes, b_entries,
            common_files_a, unverifiable_entries,
        )
        file_list.sort(key=lambda e: _display_path(e))
        if limit is not None and limit > 0:
            file_list = file_list[:limit]

        # Enrich with host locations for -l output
        host_map: dict[str, str] = {}
        if long_fmt and file_list:
            a_hosts = {h for h, _p, _d in a_specs}
            host_map = _fetch_hash_hosts(file_list, exclude_hosts=a_hosts)

        _print_file_list(file_list, long_fmt, host_map)

    sys.exit(0 if fully_covered else 1)


# ---------------------------------------------------------------------------
# Argument resolution
# ---------------------------------------------------------------------------


def _resolve_sets(a_paths_raw, b_paths_raw, positionals, covered, default_host):
    """Resolve arguments into (a_specs, b_mode).

    a_specs: list of (host, path, drive)
    b_mode: ("explicit", [(host, path, drive), ...]) | ("covered", [host_str, ...])
    """
    a_specs = [_parse_spec(raw, default_host) for raw in a_paths_raw]

    # --covered mode
    if covered is not None:
        if b_paths_raw:
            print(
                "sift sets: error: --covered and -b are mutually exclusive",
                file=sys.stderr,
            )
            sys.exit(2)
        if not a_specs:
            if not positionals:
                print("sift sets: error: no source paths specified", file=sys.stderr)
                sys.exit(2)
            a_specs = [_parse_spec(raw, default_host) for raw in positionals]
        return a_specs, ("covered", covered)

    # Explicit -b mode
    if b_paths_raw:
        b_specs = [_parse_spec(raw, default_host) for raw in b_paths_raw]
        if not a_specs:
            if not positionals:
                print(
                    "sift sets: error: no source paths specified "
                    "(use -a or positional args)",
                    file=sys.stderr,
                )
                sys.exit(2)
            a_specs = [_parse_spec(raw, default_host) for raw in positionals]
        return a_specs, ("explicit", b_specs)

    # -a used, positionals are B
    if a_specs:
        b_specs = [_parse_spec(raw, default_host) for raw in positionals]
        if not b_specs:
            print(
                "sift sets: error: must specify targets via "
                "positional args, -b, or --covered",
                file=sys.stderr,
            )
            sys.exit(2)
        return a_specs, ("explicit", b_specs)

    # Positional-only mode: first = A, rest = B
    if len(positionals) < 2:
        if len(positionals) == 1:
            print(
                "sift sets: error: need at least one target (or use --covered)",
                file=sys.stderr,
            )
        else:
            print(
                "sift sets: error: must specify at least two paths, or use --covered",
                file=sys.stderr,
            )
        sys.exit(2)

    a_specs = [_parse_spec(positionals[0], default_host)]
    b_specs = [_parse_spec(raw, default_host) for raw in positionals[1:]]
    return a_specs, ("explicit", b_specs)


def _parse_spec(raw: str, default_host: str) -> tuple[str, str, str]:
    """Parse a single path argument into (host, path, drive)."""
    host, norm = parse_host_path(raw, default_host)
    drive, path = extract_drive_path(norm)
    return host, path, drive


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def _fetch_entries(host: str, path: str, drive: str, min_size: int) -> list[dict]:
    """Fetch full file entries via /files endpoint."""
    params: dict = {
        "path_prefix": path,
        "host": host,
        "lite": "true",
        "limit": 1_000_000,
    }
    if drive:
        params["drive"] = drive
    if min_size:
        params["min_size"] = min_size

    entries = client.get("/files", params=params)

    if isinstance(entries, dict) and entries.get("status") == "pending":
        raise RuntimeError(
            entries.get("detail", "Duplicate index is still building")
        )

    return entries if isinstance(entries, list) else []


_CLIENT_BATCH = 50_000  # hashes per POST request (progress granularity)


def _check_hashes_remote(
    a_hashes: set[str],
    host: str = "",
    path_prefix: str = "",
    drive: str = "",
    min_size: int = 0,
    exclude: list[dict] | None = None,
    progress_label: str = "",
) -> set[str]:
    """POST A hashes to server, get back the subset that exist in scope.

    If progress_label is set and stderr is a tty, prints incremental progress.
    """
    if not a_hashes:
        return set()

    hash_list = list(a_hashes)
    total = len(hash_list)
    show_progress = progress_label and total > _CLIENT_BATCH and sys.stderr.isatty()
    found: set[str] = set()

    for i in range(0, total, _CLIENT_BATCH):
        batch = hash_list[i : i + _CLIENT_BATCH]
        body: dict = {"hashes": batch}
        if host:
            body["host"] = host
        if path_prefix:
            body["path_prefix"] = path_prefix
        if drive:
            body["drive"] = drive
        if min_size:
            body["min_size"] = min_size
        if exclude:
            body["exclude"] = exclude
        result = client.post("/files/hashes/check", body, timeout=(5, 120))
        found.update(result)
        if show_progress:
            sent = min(i + _CLIENT_BATCH, total)
            sys.stderr.write(
                f"\r  {progress_label} ... {sent:,} / {total:,} checked, "
                f"{len(found):,} found"
            )
            sys.stderr.flush()

    if show_progress:
        # Clear progress line — final status printed by caller
        sys.stderr.write("\r\033[2K")
        sys.stderr.flush()

    return found


def _fetch_hash_hosts(
    entries: list[dict],
    exclude_hosts: set[str] | None = None,
) -> dict[str, str]:
    """Batch-lookup hash → comma-separated hosts via host_hash_stats.

    Returns a dict like {"abc123": "host1,host2"}.
    If exclude_hosts is set, those hosts are removed from the result.
    Entries with no remaining hosts after filtering are omitted.
    """
    hashes = list({e["hash"] for e in entries if e.get("hash")})
    if not hashes:
        return {}
    try:
        raw = client.post("/files/hashes/hosts", hashes, timeout=(5, 30))
    except Exception:
        return {}
    if not exclude_hosts:
        return raw
    result: dict[str, str] = {}
    for h, hosts_str in raw.items():
        filtered = [x for x in hosts_str.split(",") if x not in exclude_hosts]
        if filtered:
            result[h] = ",".join(filtered)
    return result


def _fetch_b_entries(
    b_specs: list[tuple[str, str, str]],
    min_size: int,
) -> tuple[set[str], list[dict]]:
    """Fetch full B entries via /files (needed for --reverse file list)."""
    all_entries: list[dict] = []
    for host, path, drive in b_specs:
        entries = _fetch_entries(host, path, drive, min_size)
        all_entries.extend(entries)
    b_hashes = {e["hash"] for e in all_entries if e.get("hash")}
    return b_hashes, all_entries


def _check_targets(
    b_specs: list[tuple[str, str, str]],
    a_hashes: set[str],
    min_size: int,
) -> tuple[set[str], None]:
    """Check which A hashes exist in explicit B targets (POST approach)."""
    found: set[str] = set()
    for host, path, drive in b_specs:
        label = f"{host}:{path}" if host else path
        batch_found = _check_hashes_remote(
            a_hashes - found,  # only check hashes not yet found
            host, path, drive, min_size,
            progress_label=f"Checking {label}",
        )
        found |= batch_found
        if sys.stderr.isatty():
            print(
                f"  Checked {label} ... {len(found):,} of {len(a_hashes):,} found",
                file=sys.stderr,
            )
        if found == a_hashes:
            break  # all found, skip remaining targets
    return found, None


def _check_covered(
    a_specs: list[tuple[str, str, str]],
    a_hashes: set[str],
    covered_hosts: list[str],
    min_size: int,
) -> tuple[set[str], None]:
    """Check which A hashes exist elsewhere in the datastore (POST approach)."""
    # Build exclusion list so source files don't cover themselves
    exclude = [{"host": h, "prefix": p} for h, p, _d in a_specs]

    if covered_hosts:
        # Resolve specified hosts
        try:
            all_hosts_data = client.get("/hosts")
            all_host_names = [h["host"] for h in all_hosts_data]
        except Exception as e:
            raise RuntimeError(f"cannot fetch host list: {e}")

        found: set[str] = set()
        for ch in covered_hosts:
            resolved = resolve_host(ch)
            if resolved not in all_host_names:
                print(
                    f"sift sets: warning: host '{ch}' not found in datastore",
                    file=sys.stderr,
                )
                continue
            batch_found = _check_hashes_remote(
                a_hashes - found, host=resolved, min_size=min_size,
                exclude=exclude,
                progress_label=f"Checking {resolved}",
            )
            found |= batch_found
            if sys.stderr.isatty():
                print(
                    f"  Checked {resolved} ... {len(found):,} of {len(a_hashes):,} found",
                    file=sys.stderr,
                )
            if found == a_hashes:
                break
    else:
        # All hosts — single call, no host filter
        found = _check_hashes_remote(
            a_hashes, min_size=min_size, exclude=exclude,
            progress_label="Checking all hosts",
        )
        if sys.stderr.isatty():
            print(
                f"  Checked all hosts ... {len(found):,} of {len(a_hashes):,} found",
                file=sys.stderr,
            )

    return found, None


# ---------------------------------------------------------------------------
# Hash index building
# ---------------------------------------------------------------------------


def _build_hash_index(
    entries: list[dict],
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Build hash → [entries] index. Returns (index, unhashed_entries)."""
    index: dict[str, list[dict]] = {}
    unhashed: list[dict] = []
    for e in entries:
        h = e.get("hash")
        if h:
            index.setdefault(h, []).append(e)
        else:
            unhashed.append(e)
    return index, unhashed


def _build_unhashed_index(entries: list[dict]) -> set[tuple]:
    """Build (filename, size_bytes, mtime) set from unhashed entries."""
    result: set[tuple] = set()
    for e in entries:
        key = _unhashed_key(e)
        if key:
            result.add(key)
    return result


def _unhashed_key(entry: dict) -> tuple | None:
    """Extract (filename, size_bytes, mtime) tuple for size+mtime matching."""
    path = entry.get("path_display") or entry.get("path") or ""
    filename = path.rsplit("/", 1)[-1] if "/" in path else path
    size = entry.get("size_bytes")
    mtime = entry.get("mtime")
    if filename and size is not None and mtime is not None:
        return (filename, size, mtime)
    return None


# ---------------------------------------------------------------------------
# File list selection
# ---------------------------------------------------------------------------


def _select_file_list(
    reverse_mode: bool,
    common_mode: bool,
    a_only_files: list[dict],
    b_only_hashes: set[str],
    b_entries: list[dict] | None,
    common_files_a: list[dict],
    unverifiable_entries: list[dict],
) -> list[dict]:
    """Select which files to list based on mode."""
    if reverse_mode:
        if b_entries is not None:
            b_hash_index, _ = _build_hash_index(b_entries)
            return [
                e
                for h in b_only_hashes
                if h in b_hash_index
                for e in b_hash_index[h]
            ]
        return []

    if common_mode:
        return list(common_files_a)

    # Default: A-B (files in A not in B) + unverifiable unhashed
    return list(a_only_files) + unverifiable_entries


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _display_path(entry: dict) -> str:
    """Extract display-friendly path from entry."""
    drive = entry.get("drive", "")
    path = entry.get("path_display") or entry.get("path") or ""
    if drive:
        return f"{drive}:{path}"
    return path


def _human_size(n: int) -> str:
    """Format bytes as human-readable size for summary output."""
    val = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            if unit == "B":
                return f"{val:.0f} {unit}"
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} PB"


def _fmt_size_col(n: int) -> str:
    """Format size for -l column output (right-aligned, compact)."""
    val = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if val < 1024:
            if unit == "B":
                return f"{val:>5.0f}{unit}"
            return f"{val:>5.1f}{unit}"
        val /= 1024
    return f"{val:>5.1f}P"


def _fmt_mtime(mtime) -> str:
    """Format mtime as YYYY-MM-DD."""
    if mtime is None:
        return "          "
    try:
        dt = datetime.fromtimestamp(int(mtime), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return "          "


def _parse_size(size_str: str | None) -> int:
    """Parse human-readable size string (e.g. '1M', '500k') to bytes."""
    if not size_str:
        return 0
    s = size_str.strip().upper()
    multipliers = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    for suffix, mult in multipliers.items():
        if s.endswith(suffix):
            try:
                return int(float(s[: -len(suffix)]) * mult)
            except ValueError:
                print(
                    f"sift sets: error: invalid size '{size_str}'", file=sys.stderr
                )
                sys.exit(2)
    try:
        return int(s)
    except ValueError:
        print(f"sift sets: error: invalid size '{size_str}'", file=sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _spec_label(specs: list[tuple[str, str, str]]) -> str:
    """Format a list of (host, path, drive) specs as a display string."""
    parts = []
    for host, path, drive in specs:
        dp = f"{drive}:{path}" if drive else path
        parts.append(f"{host}:{dp}" if host else dp)
    return ", ".join(parts)


def _print_summary(
    a_specs,
    b_mode,
    a_total_files,
    a_total_size,
    a_unique_hashes,
    a_unhashed_count,
    a_only_hash_count,
    a_only_file_count,
    a_only_size,
    b_only_hash_count,
    common_hash_count,
    common_file_count_a,
    common_size_a,
    covered_pct,
    unhashed_covered,
    unhashed_unverifiable,
    fully_covered,
):
    """Print summary statistics to stderr."""
    w = sys.stderr.write

    # Header
    a_label = _spec_label(a_specs)
    if b_mode[0] == "covered":
        if b_mode[1]:
            b_label = f"--covered {' '.join(b_mode[1])}"
        else:
            b_label = "--covered (all hosts)"
    else:
        b_label = _spec_label(b_mode[1])
    w(f"\nsift sets: {a_label} \u2192 {b_label}\n\n")

    # Source stats
    unhashed_note = f", {a_unhashed_count:,} unhashed" if a_unhashed_count else ""
    w(
        f"  source (A):  {a_total_files:>10,} files   {_human_size(a_total_size):>10}   "
        f"({a_unique_hashes:,} unique hashes{unhashed_note})\n"
    )

    # Set operation results
    w(
        f"  A only:      {a_only_hash_count:>10,} hashes  "
        f"({a_only_file_count:,} files)   {_human_size(a_only_size):>10}\n"
    )
    if b_only_hash_count is not None:
        w(f"  B only:      {b_only_hash_count:>10,} hashes\n")
    w(
        f"  A \u2229 B:       {common_hash_count:>10,} hashes  "
        f"({common_file_count_a:,} files)   {_human_size(common_size_a):>10}"
        f"   {covered_pct:.1f}% of A covered\n"
    )

    # Unhashed summary
    if a_unhashed_count:
        w(
            f"  unhashed:    {unhashed_covered:>10,} covered by size+mtime, "
            f"{unhashed_unverifiable} unverifiable\n"
        )

    # Result line
    w("\n")
    if fully_covered:
        w("  result: FULLY COVERED \u2014 all hashes found in target\n")
    else:
        reasons = []
        if a_only_hash_count:
            reasons.append(f"{a_only_hash_count:,} unique hashes only in source")
        if unhashed_unverifiable:
            reasons.append(
                f"{unhashed_unverifiable:,} unverifiable unhashed files"
            )
        w(f"  result: NOT FULLY COVERED \u2014 {'; '.join(reasons)}\n")
    w("\n")


def _print_file_list(
    entries: list[dict],
    long_fmt: bool,
    host_map: dict[str, str] | None = None,
) -> None:
    """Print file list to stdout."""
    for entry in entries:
        path = _display_path(entry)
        if long_fmt:
            size = entry.get("size_bytes") or 0
            mtime = entry.get("mtime")
            hosts = ""
            if host_map:
                h = entry.get("hash")
                if h and h in host_map:
                    hosts = f"  [{host_map[h]}]"
            print(f"{_fmt_size_col(size)}  {_fmt_mtime(mtime)}  {path}{hosts}")
        else:
            print(path)
