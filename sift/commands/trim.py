"""sift trim — remove inventory rows from the datastore."""

from __future__ import annotations

import os
import sys
import time

from sift import client
from sift.commands import print_server_info
from sift.config import get_cli_config
from sift.normalize import local_hostname, normalize_query_path


def _fmt_duration(seconds: float) -> str:
    s = int(seconds)
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _is_glob_token(token: str) -> bool:
    return any(ch in token for ch in ("*", "?"))


def _resolve_path_and_patterns(args) -> tuple[str, list[str]]:
    path_token = None
    patterns: list[str] = []

    for token in getattr(args, "targets", []) or []:
        if _is_glob_token(token):
            patterns.append(token)
            continue
        if path_token is None:
            path_token = token
        else:
            raise ValueError(
                "multiple non-pattern targets provided; use one path plus optional patterns"
            )

    # Optional explicit path argument can override inferred path token.
    explicit_path = getattr(args, "path", None)
    if explicit_path:
        if path_token is not None and path_token != explicit_path:
            raise ValueError("path provided twice (positional and --path)")
        path_token = explicit_path

    if path_token is None:
        path_token = "."

    return normalize_query_path(path_token), patterns


def _debug(msg: str) -> None:
    print(f"  {msg}", file=sys.stderr)


def cmd_trim(args) -> None:
    print_server_info()
    cli_cfg = get_cli_config()

    host = (
        getattr(args, "host", None)
        or os.environ.get("SIFT_HOST")
        or cli_cfg.get("host")
        or local_hostname()
    )
    user_provided_host = bool(getattr(args, "host", None))
    debug = getattr(args, "debug", False)
    recursive = getattr(args, "recursive", False)
    deleted_only = getattr(args, "deleted", False)
    batch_size = getattr(args, "batch_size", 5000)
    dry_run = getattr(args, "dry_run", False)
    verbose = getattr(args, "verbose", False)

    targets = getattr(args, "targets", []) or []
    has_explicit_path = bool(getattr(args, "path", None)) or any(
        not _is_glob_token(t) for t in targets
    )

    try:
        path_prefix, patterns = _resolve_path_and_patterns(args)
    except ValueError as e:
        print(f"sift: {e}", file=sys.stderr)
        sys.exit(2)

    # Convenience default for datastore hygiene mode:
    # `sift trim --deleted` => recursive trim from root for local/selected host.
    if deleted_only and not has_explicit_path:
        path_prefix = normalize_query_path("/")
        recursive = True

    if debug:
        mode = "deleted" if deleted_only else "targeted"
        _debug(f"[trim] mode={mode}")
        _debug(f"[trim] host={host}")
        _debug(f"[trim] path={path_prefix or '/'}")
        _debug(f"[trim] recursive={recursive}")
        _debug(f"[trim] patterns={patterns or '[]'}")
        _debug(f"[trim] batch_size={batch_size}")

    payload = {
        "host": host,
        "path_prefix": path_prefix,
        "recursive": recursive,
        "deleted_only": deleted_only,
        "patterns": patterns,
        "limit": batch_size,
        "count_only": True,
        "preview": False,
        "offset": 0,
    }

    try:
        count_resp = client.post("/trim", payload)
    except Exception as e:
        print(f"sift: trim count failed: {e}", file=sys.stderr)
        sys.exit(1)

    total = int(count_resp.get("matched", 0))
    if total == 0:
        print("No matching inventory entries to trim.", file=sys.stderr)
        if user_provided_host and not has_explicit_path and not deleted_only:
            print(
                f"Hint: default scope is current directory ({path_prefix or '/'}). "
                f"For host-wide trim on '{host}', use: sift trim -r / --host {host}",
                file=sys.stderr,
            )
        return

    if debug:
        _debug(f"[trim] matched={total:,}")

    if dry_run:
        mode_label = "deleted-only" if deleted_only else "targeted"
        print(
            f"Dry run: {total:,} inventory entr{'y' if total == 1 else 'ies'}"
            f" would be trimmed ({mode_label}) on host '{host}' under {path_prefix or '/'}.",
            file=sys.stderr,
        )
        if verbose:
            shown = 0
            page = 0
            while shown < total:
                page += 1
                payload["preview"] = True
                payload["offset"] = shown
                try:
                    preview_resp = client.post("/trim", payload)
                except Exception as e:
                    print(f"sift: trim dry-run preview failed: {e}", file=sys.stderr)
                    sys.exit(1)
                paths = preview_resp.get("preview_paths", []) or []
                if not paths:
                    break
                if debug:
                    _debug(
                        f"[trim] preview_page={page} rows={len(paths)} offset={shown}"
                    )
                for p in paths:
                    try:
                        print(p)
                    except BrokenPipeError:
                        try:
                            sys.stdout.close()
                        except Exception:
                            pass
                        return
                shown += len(paths)
            if debug:
                _debug(f"[trim] preview_shown={shown:,}/{total:,}")
        return

    if not getattr(args, "quiet", False):
        mode_label = "deleted-only" if deleted_only else "targeted"
        print(
            f"Trimming {total:,} inventory entr{'y' if total == 1 else 'ies'}"
            f" ({mode_label})...",
            file=sys.stderr,
        )

    start = time.time()
    deleted_total = 0
    batch_no = 0

    while deleted_total < total:
        batch_no += 1
        payload["count_only"] = False

        try:
            resp = client.post("/trim", payload, timeout=(5, 120))
        except Exception as e:
            print(f"\nsift: trim failed: {e}", file=sys.stderr)
            sys.exit(1)

        deleted = int(resp.get("deleted", 0))
        matched_now = int(resp.get("matched", 0))

        if deleted <= 0:
            # Safety break: if the match set changed underneath us, stop cleanly.
            break

        deleted_total += deleted

        if debug:
            _debug(
                f"[trim] batch={batch_no} deleted={deleted:,} "
                f"deleted_total={deleted_total:,} matched_now={matched_now:,}"
            )

        if not getattr(args, "quiet", False):
            elapsed = max(time.time() - start, 0.001)
            rate = deleted_total / elapsed
            sys.stderr.write(
                f"\rTrimmed {deleted_total:,}/{total:,} "
                f"| {rate:,.0f} rows/s "
                f"| {_fmt_duration(elapsed)} elapsed"
            )
            sys.stderr.flush()

    if not getattr(args, "quiet", False):
        sys.stderr.write("\n")
        sys.stderr.flush()

    elapsed = time.time() - start
    print(
        f"Trim complete: {deleted_total:,} deleted"
        f" from host '{host}' under {path_prefix or '/'}"
        f" in {_fmt_duration(elapsed)}.",
        file=sys.stderr,
    )
