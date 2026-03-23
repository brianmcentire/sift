"""sift mv — move files on disk and update paths in the sift datastore.

Avoids a full rescan after reorganizing files.  Moves happen on the local
filesystem first, then the datastore is updated so the next scan sees the
files at their new location without rehashing.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import Optional

from sift import client
from sift.classify import classify_file
from sift.commands import print_server_info, resolve_host
from sift.config import get_cli_config, get_server_url
from sift.normalize import (
    get_source_os,
    local_hostname,
    normalize_path_for_storage,
    normalize_query_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INT64_MAX = (1 << 63) - 1


def _safe_inode(stat_result: os.stat_result) -> Optional[int]:
    """Extract inode from stat, clamping Windows/edge cases to None."""
    ino = stat_result.st_ino
    if ino == 0 or ino > _INT64_MAX:
        return None
    return ino


def _safe_device(stat_result: os.stat_result) -> Optional[int]:
    dev = stat_result.st_dev
    if dev == 0:
        return None
    return dev


def _stat_new_file(path: str) -> tuple[Optional[int], Optional[int], bool]:
    """Stat a file and return (inode, device, inode_known).

    Returns (None, None, False) if stat fails.
    """
    try:
        sr = os.stat(path)
        return _safe_inode(sr), _safe_device(sr), True
    except OSError:
        return None, None, False


def _err(msg: str) -> None:
    print(f"sift mv: error: {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    print(f"sift mv: warning: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def cmd_mv(args) -> None:
    paths = args.paths
    if len(paths) < 2:
        _err("need at least a source and destination")
        sys.exit(2)

    sources_raw = paths[:-1]
    dest_raw = paths[-1]
    dry_run = args.dry_run
    db_only = args.db_only
    force = args.force

    print_server_info()
    cli_cfg = get_cli_config()
    _user_host = os.environ.get("SIFT_HOST") or cli_cfg.get("host")
    host = resolve_host(_user_host) if _user_host else local_hostname()
    source_os = get_source_os()

    # --- Server health check (before touching any files) ---
    if not dry_run:
        try:
            client.get("/hosts")
        except Exception:
            _err(f"cannot reach server at {get_server_url()}")
            sys.exit(1)

    # --- Resolve destination ---
    dest_real = os.path.realpath(os.path.expanduser(dest_raw))
    dest_is_dir = os.path.isdir(dest_real) if not db_only else None

    # If multiple sources, dest must be a directory (or --db-only)
    if len(sources_raw) > 1 and not db_only and not dest_is_dir:
        _err(f"target '{dest_raw}' is not a directory (multiple sources given)")
        sys.exit(2)

    # --- Build move plan ---
    # Each item: (src_real, dest_real_file, old_norm, new_norm)
    # where norms are (path, path_display, drive)
    plan: list[dict] = []  # list of MoveItem-ready dicts
    source_reals: list[tuple[str, str]] = []  # (src_real, dest_real) for filesystem moves

    for src_raw in sources_raw:
        src_real = os.path.realpath(os.path.expanduser(src_raw))

        # Determine the destination path for this source
        if not db_only:
            is_file = os.path.isfile(src_real)
            is_dir = os.path.isdir(src_real)
            if not is_file and not is_dir:
                _err(f"source does not exist: {src_raw}")
                continue
        else:
            # In --db-only mode, check the datastore
            is_file = True  # determined below per entry
            is_dir = False

        # Figure out where this source lands
        if not db_only and dest_is_dir:
            # mv src /dest/dir/ → /dest/dir/basename(src)
            file_dest_real = os.path.join(dest_real, os.path.basename(src_real))
        elif not db_only and len(sources_raw) == 1:
            # mv src dest → rename to dest
            file_dest_real = dest_real
        else:
            file_dest_real = dest_real

        # Normalize source for DB query
        src_norm = normalize_query_path(src_raw)

        if not db_only and is_dir:
            # Directory move: fetch all files under this path from datastore
            _build_dir_plan(plan, host, src_real, src_norm, file_dest_real, source_os)
            source_reals.append((src_real, file_dest_real))
        elif not db_only and is_file:
            # Single file
            _build_file_plan(plan, src_real, file_dest_real, source_os)
            source_reals.append((src_real, file_dest_real))
        elif db_only:
            # --db-only: could be file or directory, query datastore to find out
            _build_db_only_plan(plan, host, src_real, src_norm,
                                file_dest_real, dest_raw, source_os)

    if not plan:
        _err("nothing to move")
        sys.exit(1)

    # --- Dry run ---
    if dry_run:
        print(f"Would move {len(plan)} file(s) in datastore:", file=sys.stderr)
        for item in plan[:20]:
            print(f"  {item['old_path']} → {item['new_path']}", file=sys.stderr)
        if len(plan) > 20:
            print(f"  ... and {len(plan) - 20} more", file=sys.stderr)
        sys.exit(0)

    # --- Filesystem moves ---
    if not db_only:
        for src_real_path, dest_real_path in source_reals:
            try:
                # Ensure parent directory exists
                dest_parent = os.path.dirname(dest_real_path)
                if dest_parent and not os.path.exists(dest_parent):
                    os.makedirs(dest_parent, exist_ok=True)
                shutil.move(src_real_path, dest_real_path)
            except OSError as e:
                _err(f"filesystem move failed: {src_real_path} → {dest_real_path}: {e}")
                # Remove plan items for this source
                src_norm_lower = src_real_path.lower()
                plan = [p for p in plan
                        if not p.get("_src_real", "").lower().startswith(src_norm_lower)]
                continue

    if not plan:
        _err("all filesystem moves failed, nothing to update in datastore")
        sys.exit(1)

    # --- Stat new files for inode/device ---
    for item in plan:
        new_real = item.pop("_new_real", None)
        item.pop("_src_real", None)
        if new_real:
            inode, device, known = _stat_new_file(new_real)
            item["new_inode"] = inode
            item["new_device"] = device
            item["inode_known"] = known
            if not known:
                _warn(f"could not stat {new_real}, inode info will be stale")

    # --- Determine drives ---
    old_drives = {item.get("_old_drive", "") for item in plan}
    new_drives = {item.get("_new_drive", "") for item in plan}
    # Clean up internal keys
    for item in plan:
        item.pop("_old_drive", None)
        item.pop("_new_drive", None)

    old_drive = old_drives.pop() if len(old_drives) == 1 else ""
    new_drive = new_drives.pop() if len(new_drives) == 1 else ""

    # --- Call server ---
    request_body = {
        "host": host,
        "old_drive": old_drive,
        "new_drive": new_drive,
        "moves": plan,
        "force": force,
    }

    try:
        result = client.post("/files/move", request_body)
    except Exception as e:
        _warn(f"server update failed: {e}")
        _warn("files were moved on disk but the datastore was NOT updated")
        _warn("run 'sift scan' on the destination to re-index")
        sys.exit(1)

    moved = result.get("moved", 0)
    not_found = result.get("not_found", [])
    collisions = result.get("collisions", [])

    print(f"moved {moved} file(s) in datastore", file=sys.stderr)
    if not_found:
        _warn(f"{len(not_found)} path(s) not found in datastore (will be indexed on next scan)")
    if collisions:
        _warn(f"{len(collisions)} path(s) skipped due to collisions (use --force to overwrite)")
        for c in collisions[:5]:
            print(f"  collision: {c}", file=sys.stderr)
        if len(collisions) > 5:
            print(f"  ... and {len(collisions) - 5} more", file=sys.stderr)


# ---------------------------------------------------------------------------
# Plan builders
# ---------------------------------------------------------------------------


def _build_file_plan(
    plan: list[dict],
    src_real: str,
    dest_real: str,
    source_os: str,
) -> None:
    """Add a single file move to the plan."""
    old_path, old_path_display, old_drive = normalize_path_for_storage(src_real, source_os)
    new_path, new_path_display, new_drive = normalize_path_for_storage(dest_real, source_os)
    new_filename = os.path.basename(dest_real)
    new_ext, new_file_category = classify_file(new_filename)

    plan.append({
        "old_path": old_path,
        "new_path": new_path,
        "new_path_display": new_path_display,
        "new_filename": new_filename,
        "new_ext": new_ext,
        "new_file_category": new_file_category,
        "_old_drive": old_drive,
        "_new_drive": new_drive,
        "_src_real": src_real,
        "_new_real": dest_real,
    })


def _build_dir_plan(
    plan: list[dict],
    host: str,
    src_real: str,
    src_norm: str,
    dest_real: str,
    source_os: str,
) -> None:
    """Add all files under a directory to the plan."""
    entries = _fetch_files(host, src_norm)
    if not entries:
        _warn(f"no files found in datastore under {src_real}")
        return

    dest_real_stripped = dest_real.rstrip(os.sep)

    old_path_norm, _, old_drive = normalize_path_for_storage(src_real, source_os)
    new_path_norm, new_path_display_base, new_drive = normalize_path_for_storage(
        dest_real, source_os,
    )
    old_prefix = old_path_norm.rstrip("/")
    new_prefix = new_path_norm.rstrip("/")
    new_display_prefix = new_path_display_base.rstrip("/")

    for entry in entries:
        entry_path_display = entry.get("path_display", "")
        # /files lite mode returns path_display, not path; derive normalized path
        entry_path = entry_path_display.lower()

        # Compute suffix (the part after the old prefix)
        if entry_path.startswith(old_prefix + "/"):
            suffix = entry_path[len(old_prefix):]          # e.g. "/subdir/file.txt"
            display_suffix = entry_path_display[len(old_prefix):]  # preserve casing
        elif entry_path == old_prefix:
            suffix = ""
            display_suffix = ""
        else:
            continue

        new_path = new_prefix + suffix
        new_path_display = new_display_prefix + display_suffix if display_suffix else new_prefix

        # Compute new real filesystem path (for stat after move)
        # suffix is like "/subdir/file.txt" — join with dest_real
        new_real = os.path.join(dest_real_stripped, suffix.lstrip("/")) if suffix else dest_real

        new_filename = os.path.basename(new_path_display) or os.path.basename(new_path)
        new_ext, new_file_category = classify_file(new_filename)

        plan.append({
            "old_path": entry_path,
            "new_path": new_path,
            "new_path_display": new_path_display,
            "new_filename": new_filename,
            "new_ext": new_ext,
            "new_file_category": new_file_category,
            "_old_drive": old_drive,
            "_new_drive": new_drive,
            "_src_real": src_real,
            "_new_real": new_real,
        })

    print(f"  {len(entries)} file(s) under {src_real}", file=sys.stderr)


def _build_db_only_plan(
    plan: list[dict],
    host: str,
    src_real: str,
    src_norm: str,
    dest_real: str,
    dest_raw: str,
    source_os: str,
) -> None:
    """Build plan for --db-only mode by querying the datastore."""
    # Try as a single file first
    entries = _fetch_files(host, src_norm)

    if not entries:
        _err(f"no files found in datastore matching {src_real}")
        return

    # Check if it's a single exact file match or a directory prefix
    exact = [e for e in entries if e.get("path_display", "").lower() == src_norm]
    if len(exact) == 1 and len(entries) == 1:
        # Single file
        _build_file_plan(plan, src_real, dest_real, source_os)
    else:
        # Directory — treat as prefix match
        _build_dir_plan(plan, host, src_real, src_norm, dest_real, source_os)


def _fetch_files(host: str, path_prefix: str) -> list[dict]:
    """Fetch file entries from the datastore."""
    params = {
        "host": host,
        "path_prefix": path_prefix,
        "lite": "true",
        "limit": 1_000_000,
    }
    try:
        result = client.get("/files", params=params)
    except Exception:
        return []
    if isinstance(result, list):
        return result
    return []
