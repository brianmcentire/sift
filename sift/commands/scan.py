"""sift scan — scan a directory and POST file metadata to the server."""
from __future__ import annotations

import math
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from sift import client
from sift.classify import classify_file
from sift.config import get_agent_config
from sift.exclusions import is_excluded_dir, is_excluded_file, is_volatile_active
from sift.hash_utils import hash_file, needs_rehash
from sift.normalize import (
    get_source_os,
    local_hostname,
    normalize_path_for_storage,
    safe_path,
)


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


_PRECOUNT_TIMEOUT = 1200  # seconds (20 min) before giving up on background count


def _precount_files(
    root: str,
    source_os: str,
    result: dict,
    stop_event: threading.Event,
    root_dev: int | None = None,
    allow_unraid_disks: bool = False,
) -> None:
    """
    Background file count. Writes result['count'] when complete.
    Applies the same directory exclusions as the main walk; skips symlinks.
    Abandons after _PRECOUNT_TIMEOUT seconds so a blocked scandir (hung
    mount, stale share) never prevents the scan from making progress.
    root_dev: if set, skip directories on a different filesystem (--one-filesystem).
    """
    deadline = time.monotonic() + _PRECOUNT_TIMEOUT
    count = 0
    stack = [root]
    while stack and not stop_event.is_set():
        if time.monotonic() > deadline:
            return  # timed out — result['count'] not written, % won't appear
        dirpath = stack.pop()
        try:
            scan_root = safe_path(dirpath) if source_os == "windows" else dirpath
            with os.scandir(scan_root) as it:
                for entry in it:
                    if stop_event.is_set():
                        return
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if root_dev is not None and os.stat(entry.path).st_dev != root_dev:
                                continue
                            if not is_excluded_dir(entry.path, entry.name, source_os, allow_unraid_disks):
                                stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            ext, _ = classify_file(entry.name)
                            if not is_excluded_file(entry.name, ext):
                                count += 1
                    except OSError:
                        pass
        except OSError:
            pass
        time.sleep(0)  # yield the GIL between directories
    if not stop_event.is_set():
        result["count"] = count


def _format_size(n: Optional[int]) -> str:
    if n is None:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


def _format_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _print_progress(
    stats: dict,
    scan_start: datetime,
    display: dict,
    final: bool = False,
) -> None:
    elapsed = time.time() - scan_start.timestamp()
    files_rate = stats["files_scanned"] / elapsed if elapsed > 0 else 0
    # Hash throughput should reflect bytes actually read+hashed, not cache hits.
    mb_rate = stats["bytes_hashed"] / elapsed / (1024 * 1024) if elapsed > 0 else 0

    # Pick up precount total as soon as the background thread writes it
    if display["total"] is None and "count" in display.get("precount", {}):
        display["total"] = display["precount"]["count"]
        display["total_is_estimate"] = True

    total = display["total"]
    total_label = f"~{total:,}" if display.get("total_is_estimate") else f"{total:,}"
    if total is not None and total > 0:
        line1 = (
            f"Scanned {stats['files_scanned']:,} of {total_label} files"
            f" | {files_rate:,.0f} files/s"
            f" | {mb_rate:.1f} MB/s"
            f" | {_format_size(stats['bytes_scanned'])}"
        )
        pct = min(100.0, stats["files_scanned"] * 100.0 / total)
        line1 += f" | {pct:.0f}%"
        if files_rate > 0 and stats["files_scanned"] < total:
            ete_secs = (total - stats["files_scanned"]) / files_rate
            line1 += f" ETE {_format_duration(ete_secs)}"
    else:
        line1 = (
            f"Scanned {stats['files_scanned']:,} files"
            f" | {files_rate:,.0f} files/s"
            f" | {mb_rate:.1f} MB/s"
            f" | {_format_size(stats['bytes_scanned'])}"
        )
    line1 += f" | {_format_duration(elapsed)} elapsed"

    is_tty = sys.stderr.isatty()
    current_file = display.get("current_file", "")
    prev = display.get("lines", 0)

    if is_tty:
        try:
            cols = os.get_terminal_size(sys.stderr.fileno()).columns
        except OSError:
            cols = 120
    else:
        cols = 120

    # Truncate line1 to prevent wrapping — a wrapped line breaks \r and cursor-up ANSI codes
    if len(line1) > cols - 1:
        line1 = line1[:cols - 1]

    if is_tty and current_file and not final:
        # Two-line mode: status line + current file being hashed
        line2 = f"  {current_file}"
        if len(line2) > cols:
            # Keep the tail of the path so the filename is always visible
            line2 = "  ..." + current_file[-(cols - 5):]
        if prev >= 2:
            sys.stderr.write(f"\x1b[1A\r\x1b[2K{line1}\n\r\x1b[2K{line2}")
        else:
            sys.stderr.write(f"\r\x1b[2K{line1}\n\r\x1b[2K{line2}")
        display["lines"] = 2
    else:
        # Single-line mode (non-TTY, no file currently hashing, or final)
        if prev >= 2:
            # Collapse: clear both lines with a single erase-to-end-of-screen
            sys.stderr.write(f"\x1b[1A\r\x1b[J{line1}")
        else:
            sys.stderr.write(f"\r\x1b[2K{line1}")
        if final:
            sys.stderr.write("\n")
        display["lines"] = 0 if final else 1

    sys.stderr.flush()


def _print_current_file_only(display: dict) -> None:
    """Refresh only the current-file line (line 2) without touching stats line.

    Used for smoother feedback during cache-hit-heavy scans while keeping the
    stats line update interval independent and slower.
    """
    is_tty = sys.stderr.isatty()
    current_file = display.get("current_file", "")
    prev = display.get("lines", 0)
    if not is_tty or not current_file or prev < 2:
        return

    try:
        cols = os.get_terminal_size(sys.stderr.fileno()).columns
    except OSError:
        cols = 120

    line2 = f"  {current_file}"
    if len(line2) > cols:
        line2 = "  ..." + current_file[-(cols - 5):]

    # Rewrite line 2. Leave cursor on line 2 (same as _print_progress does),
    # so the next _print_progress call's \x1b[1A correctly moves back to line 1.
    sys.stderr.write(f"\r\x1b[2K{line2}")
    sys.stderr.flush()


class _ServerDown(Exception):
    """Raised when the sift server has been unreachable for too long."""


_RETRY_TIMEOUT = 90          # seconds before giving up and aborting the scan
_FLUSH_INTERVAL = 60  # flush accumulated records at least every minute


def _post_with_retry(fn, label: str) -> None:
    """Call fn(), retrying with exponential backoff up to _RETRY_TIMEOUT seconds.

    Prints a single warning on first failure, then retries silently.
    Raises _ServerDown if the server remains unreachable for the full timeout.
    """
    deadline = time.time() + _RETRY_TIMEOUT
    delay = 2
    first = True
    while True:
        try:
            fn()
            return
        except Exception as e:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise _ServerDown(
                    f"server unreachable for {_RETRY_TIMEOUT}s ({label}): {e}"
                ) from e
            if first:
                print(
                    f"\nsift: server unreachable ({label}), retrying for up to {_RETRY_TIMEOUT}s…",
                    file=sys.stderr,
                )
                first = False
            wait = min(delay, remaining)
            time.sleep(wait)
            delay = min(delay * 2, 10)


def _onerror(e: OSError) -> None:
    # Silently skip unreadable directories (called by os.walk)
    pass


def _onerror_debug(e: OSError) -> None:
    print(f"\nsift: cannot read directory: {e.filename}: {e.strerror}", file=sys.stderr)
    sys.exit(1)


def _debug(msg: str) -> None:
    print(f"  {msg}", file=sys.stderr)


def cmd_scan(args) -> None:
    cfg = get_agent_config()
    source_os = get_source_os()
    host = local_hostname()
    debug = getattr(args, "debug", False)
    quiet = getattr(args, "quiet", False)
    one_filesystem = getattr(args, "one_filesystem", False)
    allow_unraid_disks = getattr(args, "yolo", False)

    raw_root = getattr(args, "path", ".") or "."
    root = os.path.realpath(os.path.expanduser(raw_root))

    # On Windows use safe_path for os.walk root
    walk_root = safe_path(root) if source_os == "windows" else root
    root_dev = os.stat(walk_root).st_dev if one_filesystem else None

    # Normalize root path for storage
    root_path, _, _ = normalize_path_for_storage(root, source_os)

    if getattr(args, "ask", False):
        from sift.config import get_server_url
        print(file=sys.stderr)
        print(f"  Directory : {root}", file=sys.stderr)
        print(f"  Host tag  : {host}", file=sys.stderr)
        print(f"  Sift server: {get_server_url()}", file=sys.stderr)
        print(file=sys.stderr)
        try:
            answer = input("Proceed? [Y/n] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print(file=sys.stderr)
            sys.exit(0)
        if answer not in ("", "y", "yes"):
            sys.exit(0)

    scan_start = datetime.now(timezone.utc)
    scan_start_iso = scan_start.isoformat()

    volatile_threshold = cfg.get("volatile_mtime_threshold_days", 30)
    upsert_batch_size = cfg.get("upsert_batch_size", 500)
    seen_batch_size = cfg.get("seen_batch_size", 5000)
    chunk_size_mb = cfg.get("chunk_size_mb", 8)
    chunk_size_bytes = chunk_size_mb * 1024 * 1024

    # -----------------------------------------------------------------------
    # 1. Register scan run
    # -----------------------------------------------------------------------
    if not quiet:
        print(f"Registering scan run for {host}:{root_path}...", file=sys.stderr)

    stop_event = threading.Event()
    run_id = None
    try:
        run_resp = client.post("/scan-runs", {
            "host": host,
            "root_path": root_path,
            "started_at": scan_start_iso,
        })
        run_id = run_resp["id"]
    except Exception as e:
        print(f"sift: failed to register scan run: {e}", file=sys.stderr)
        sys.exit(1)

    # Start background file count (daemon thread — low impact via inter-directory sleep)
    precount_result: dict = {}
    if not quiet:
        threading.Thread(
            target=_precount_files,
            args=(root, source_os, precount_result, stop_event, root_dev, allow_unraid_disks),
            daemon=True,
            name="sift-precount",
        ).start()

    display: dict = {
        "total": None,
        "current_file": "",
        "lines": 0,
        "precount": precount_result,
    }

    try:
        # -------------------------------------------------------------------
        # 2. Fetch cache
        # -------------------------------------------------------------------
        if not quiet:
            sys.stderr.write("Fetching file cache...")
            sys.stderr.flush()
        try:
            cache_resp = client.get("/files/cache", params={"host": host, "root": root_path})
            # Response is compact array-of-arrays: [path, mtime, size_bytes]
            cache: dict[str, dict] = {
                entry[0]: {"mtime": entry[1], "size_bytes": entry[2]}
                for entry in cache_resp.get("files", [])
            }
            if not quiet:
                sys.stderr.write(f" {len(cache):,} entries.\n")
                sys.stderr.flush()
        except Exception as e:
            if not quiet:
                sys.stderr.write("\n")
            print(f"sift: warning — could not fetch cache: {e}", file=sys.stderr)
            cache = {}

        # -------------------------------------------------------------------
        # 3. Walk
        # -------------------------------------------------------------------
        upsert_records: list[dict] = []
        seen_paths: list[dict] = []
        # Maps (st_dev, st_ino) → hash for reusing hash across hard-linked paths.
        # Only populated when inode is non-zero (i.e., not Windows with st_ino=0).
        seen_inodes: dict[tuple[int, int], str] = {}
        stats = {
            "files_scanned": 0,
            "files_hashed": 0,
            "files_cached": 0,
            "files_skipped": 0,
            "bytes_scanned": 0,
            "bytes_hashed": 0,
            "read_errors": 0,
        }

        _error_log_path = os.path.expanduser("~/.sift-scan-errors.log")
        _error_log_fh = None

        def _log_error(path: str) -> None:
            nonlocal _error_log_fh
            if _error_log_fh is None:
                _error_log_fh = open(_error_log_path, "a")  # noqa: SIM115
                _error_log_fh.write(
                    f"--- sift scan errors: {scan_start_iso} | host: {host} | root: {walk_root} ---\n"
                )
            _error_log_fh.write(path + "\n")

        _stats_progress_interval = 1.0   # stats line refresh cadence
        _file_progress_interval = 0.10   # current-file line refresh cadence
        _last_stats_progress = time.time()
        _last_file_progress = _last_stats_progress
        _last_flush_time = time.time()

        def _maybe_render_progress(now: float) -> None:
            nonlocal _last_stats_progress, _last_file_progress
            if quiet:
                return
            if now - _last_stats_progress >= _stats_progress_interval:
                _print_progress(stats, scan_start, display)
                _last_stats_progress = now
                _last_file_progress = now
            elif now - _last_file_progress >= _file_progress_interval:
                _print_current_file_only(display)
                _last_file_progress = now

        def _on_chunk(_nbytes: int) -> None:
            if quiet:
                return
            now = time.time()
            _maybe_render_progress(now)

        onerror = _onerror_debug if debug else _onerror

        for dirpath, dirnames, filenames in os.walk(walk_root, onerror=onerror, followlinks=False):
            # Prune excluded directories in place
            kept = []
            for d in dirnames:
                full = os.path.join(dirpath, d)
                if is_excluded_dir(full, d, source_os, allow_unraid_disks):
                    if debug:
                        _debug(f"[excluded dir]  {full}")
                    continue
                if root_dev is not None:
                    try:
                        if os.stat(full).st_dev != root_dev:
                            if debug:
                                _debug(f"[cross-device]  {full}")
                            continue
                    except OSError:
                        continue
                kept.append(d)
            dirnames[:] = kept

            for filename in filenames:
                raw_path = os.path.join(dirpath, filename)
                sp = safe_path(raw_path) if source_os == "windows" else raw_path

                try:
                    # Skip symlinks
                    if os.path.islink(sp):
                        continue

                    stat_result = os.stat(sp)

                    if not os.path.isfile(sp):
                        continue

                    # Skip empty files
                    if stat_result.st_size == 0:
                        if debug:
                            _debug(f"[empty]         {raw_path}")
                        continue

                    ext, category = classify_file(filename)

                    # Skip excluded filenames/extensions entirely (don't record)
                    if is_excluded_file(filename, ext):
                        if debug:
                            _debug(f"[excluded file] {raw_path}")
                        continue

                    path_lower, path_display, drive = normalize_path_for_storage(raw_path, source_os)
                    cached = cache.get(path_lower)
                    mtime_val = math.floor(stat_result.st_mtime)

                    # Inode tracking for hard link detection.
                    # Windows returns st_ino=0 for most files — treat as unknown.
                    raw_ino = stat_result.st_ino
                    raw_dev = stat_result.st_dev
                    if raw_ino == 0:
                        inode_val = None
                        device_val = None
                        inode_key = None
                    else:
                        inode_val = raw_ino
                        device_val = raw_dev
                        inode_key = (raw_dev, raw_ino)

                    stats["bytes_scanned"] += stat_result.st_size
                    display["current_file"] = raw_path

                    # Check if volatile and active (skip hashing)
                    if is_volatile_active(
                        raw_path, filename, ext, stat_result.st_mtime, source_os, volatile_threshold
                    ):
                        if debug:
                            _debug(f"[volatile]      {raw_path}")
                        upsert_records.append(_make_record(
                            host=host, drive=drive, path=path_lower, path_display=path_display,
                            filename=filename, ext=ext, file_category=category,
                            size_bytes=stat_result.st_size, hash_val=None,
                            mtime=mtime_val, scan_start_iso=scan_start_iso,
                            source_os=source_os, skipped_reason="volatile_active",
                            inode=inode_val, device=device_val,
                        ))
                        stats["files_skipped"] += 1

                    elif needs_rehash(stat_result, cached):
                        # If we've already hashed another path with the same inode on
                        # this device (a hard link), reuse the cached hash — no I/O needed.
                        if inode_key is not None and inode_key in seen_inodes:
                            hash_val = seen_inodes[inode_key]
                            if debug:
                                _debug(f"[hard link]     {raw_path}")
                            upsert_records.append(_make_record(
                                host=host, drive=drive, path=path_lower, path_display=path_display,
                                filename=filename, ext=ext, file_category=category,
                                size_bytes=stat_result.st_size, hash_val=hash_val,
                                mtime=mtime_val, scan_start_iso=scan_start_iso,
                                source_os=source_os, skipped_reason=None,
                                inode=inode_val, device=device_val,
                            ))
                            stats["files_hashed"] += 1
                        else:
                            hash_val = hash_file(sp, chunk_size=chunk_size_bytes, on_chunk=_on_chunk)
                            if hash_val is None:
                                msg = f"cannot read {raw_path}: permission denied"
                                if debug:
                                    print(f"\nsift: {msg}", file=sys.stderr)
                                    sys.exit(1)
                                upsert_records.append(_make_record(
                                    host=host, drive=drive, path=path_lower, path_display=path_display,
                                    filename=filename, ext=ext, file_category=category,
                                    size_bytes=stat_result.st_size, hash_val=None,
                                    mtime=mtime_val, scan_start_iso=scan_start_iso,
                                    source_os=source_os, skipped_reason="permission_error",
                                    inode=inode_val, device=device_val,
                                ))
                                _log_error(raw_path)
                                stats["read_errors"] += 1
                                stats["files_skipped"] += 1
                            else:
                                if inode_key is not None:
                                    seen_inodes[inode_key] = hash_val
                                stats["bytes_hashed"] += stat_result.st_size
                                upsert_records.append(_make_record(
                                    host=host, drive=drive, path=path_lower, path_display=path_display,
                                    filename=filename, ext=ext, file_category=category,
                                    size_bytes=stat_result.st_size, hash_val=hash_val,
                                    mtime=mtime_val, scan_start_iso=scan_start_iso,
                                    source_os=source_os, skipped_reason=None,
                                    inode=inode_val, device=device_val,
                                ))
                                stats["files_hashed"] += 1

                    else:
                        # Unchanged — just update last_seen_at
                        seen_paths.append({"drive": drive, "path": path_lower})
                        stats["files_cached"] += 1

                except PermissionError as e:
                    if debug:
                        print(f"\nsift: permission denied: {raw_path}: {e.strerror}", file=sys.stderr)
                        sys.exit(1)
                    _log_error(raw_path)
                    stats["read_errors"] += 1
                except OSError as e:
                    if debug:
                        print(f"\nsift: error: {raw_path}: {e.strerror}", file=sys.stderr)
                        sys.exit(1)
                    _log_error(raw_path)
                    stats["read_errors"] += 1

                stats["files_scanned"] += 1

                # Flush on time interval (or when batch grows very large as a memory safety net)
                if (
                    len(upsert_records) >= 10_000
                    or (upsert_records and time.time() - _last_flush_time >= _FLUSH_INTERVAL)
                ):
                    for chunk in _chunks(upsert_records, upsert_batch_size):
                        _flush_upsert(chunk, host, scan_start_iso)
                    upsert_records.clear()
                    _last_flush_time = time.time()

                # seen_paths are flushed after the walk — don't block traversal with network I/O

                # Progress update
                now = time.time()
                _maybe_render_progress(now)

        display["current_file"] = ""
        if _error_log_fh is not None:
            _error_log_fh.close()

        # -------------------------------------------------------------------
        # 4. Flush batches
        # -------------------------------------------------------------------
        # Upsert: remaining records with new hash data
        for chunk in _chunks(upsert_records, upsert_batch_size):
            _flush_upsert(chunk, host, scan_start_iso)

        # Seen: all collected after the walk in one or a few large requests.
        # seen_batch_size is the max per request; server handles each as a single bulk UPDATE.
        for chunk in _chunks(seen_paths, seen_batch_size):
            _flush_seen(chunk, host, scan_start_iso)

        # -------------------------------------------------------------------
        # 5. Finalize
        # -------------------------------------------------------------------
        try:
            client.patch(f"/scan-runs/{run_id}", {"status": "complete"})
        except Exception as e:
            print(f"\nsift: warning — failed to mark scan complete: {e}", file=sys.stderr)

        if not quiet:
            _print_progress(stats, scan_start, display, final=True)
        elapsed = time.time() - scan_start.timestamp()
        err_suffix = (
            f", {stats['read_errors']:,} read errors (see {_error_log_path})"
            if stats["read_errors"] else ""
        )
        cached_str = f", {stats['files_cached']:,} cached" if stats["files_cached"] else ""
        print(
            f"\nScan complete: {stats['files_scanned']:,} files scanned, "
            f"{stats['files_hashed']:,} hashed{cached_str}, "
            f"{stats['files_skipped']:,} skipped, "
            f"{_format_size(stats['bytes_scanned'])} total, "
            f"{_format_duration(elapsed)} elapsed{err_suffix}",
            file=sys.stderr,
        )

    except _ServerDown as e:
        stop_event.set()
        print(f"\nsift: {e}", file=sys.stderr)
        print("Scan aborted. Re-run to resume once the server is back.", file=sys.stderr)
        try:
            client.patch(f"/scan-runs/{run_id}", {"status": "failed"})
        except Exception:
            pass
        sys.exit(1)

    except KeyboardInterrupt:
        stop_event.set()
        print("\nScan interrupted.", file=sys.stderr)
        if upsert_records:
            print(f"Flushing {len(upsert_records)} buffered records...", file=sys.stderr)
            try:
                for chunk in _chunks(upsert_records, upsert_batch_size):
                    _flush_upsert(chunk, host, scan_start_iso)
            except _ServerDown:
                print("sift: server unreachable, buffered records not saved.", file=sys.stderr)
        try:
            client.patch(f"/scan-runs/{run_id}", {"status": "interrupted"})
        except Exception:
            pass
        sys.exit(130)


def _make_record(
    *, host, drive, path, path_display, filename, ext, file_category,
    size_bytes, hash_val, mtime, scan_start_iso, source_os, skipped_reason,
    inode=None, device=None,
) -> dict:
    return {
        "host": host,
        "drive": drive,
        "path": path,
        "path_display": path_display,
        "filename": filename,
        "ext": ext,
        "file_category": file_category,
        "size_bytes": size_bytes,
        "hash": hash_val,
        "mtime": mtime,
        "last_checked": scan_start_iso,
        "source_os": source_os,
        "skipped_reason": skipped_reason,
        "last_seen_at": scan_start_iso,
        "inode": inode,
        "device": device,
    }


def _flush_upsert(records: list[dict], host: str, scan_start_iso: str) -> None:
    if not records:
        return
    _post_with_retry(lambda: client.post("/files", records), "upsert")


def _flush_seen(paths: list[dict], host: str, scan_start_iso: str) -> None:
    if not paths:
        return
    _post_with_retry(
        lambda: client.post("/files/seen", {
            "host": host,
            "last_seen_at": scan_start_iso,
            "paths": paths,
        }),
        "seen",
    )
