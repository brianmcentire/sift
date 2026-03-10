"""sift trim — remove inventory rows from the datastore."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

from sift import client
from sift.commands import print_server_info, resolve_host
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


def _normalize_root_for_trim(root_value: str) -> str:
    root = str(root_value or "").strip().replace("\\", "/")
    if len(root) >= 2 and root[1] == ":":
        root = root[2:]
    if not root:
        root = "/"
    if not root.startswith("/"):
        root = "/" + root
    root = root.lower().rstrip("/")
    return root or "/"


def _root_covers(ancestor: str, candidate: str) -> bool:
    if ancestor == candidate:
        return True
    if ancestor == "/":
        return candidate.startswith("/")
    return candidate.startswith(ancestor + "/")


def _latest_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt.date().isoformat()


def cmd_trim(args) -> None:
    print_server_info()
    cli_cfg = get_cli_config()

    _user_host = (
        getattr(args, "host", None)
        or os.environ.get("SIFT_HOST")
        or cli_cfg.get("host")
    )
    host = resolve_host(_user_host) if _user_host else local_hostname()
    user_provided_host = bool(getattr(args, "host", None))
    debug = getattr(args, "debug", False)
    recursive = getattr(args, "recursive", False)
    deleted_only = getattr(args, "deleted", False)
    unsafe_not_seen_since = getattr(args, "unsafe_delete_not_seen_since", None)
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

    if deleted_only and unsafe_not_seen_since:
        print(
            "sift: --deleted and --unsafe-delete-not-seen-since cannot be used together",
            file=sys.stderr,
        )
        sys.exit(2)

    unsafe_mode_latest = str(unsafe_not_seen_since).strip().lower() == "latest"
    unsafe_not_seen_before = None
    if unsafe_not_seen_since and not unsafe_mode_latest:
        try:
            parsed = datetime.strptime(str(unsafe_not_seen_since), "%Y%m%d")
            unsafe_not_seen_before = (
                parsed.replace(tzinfo=timezone.utc).date().isoformat()
            )
        except ValueError:
            print(
                "sift: --unsafe-delete-not-seen-since must be YYYYMMDD or 'latest'",
                file=sys.stderr,
            )
            sys.exit(2)

    scope_cutoffs: list[tuple[str, str | None]] = [
        (path_prefix, unsafe_not_seen_before)
    ]
    if unsafe_not_seen_since:
        # Unsafe age-based mode is always recursive.
        recursive = True
        roots: list[tuple[str, str | None]] = []
        if unsafe_mode_latest or not has_explicit_path:
            try:
                roots_resp = client.get("/hosts/roots", params={"host": host})
            except Exception as e:
                print(
                    f"sift: failed to resolve host roots for '{host}': {e}",
                    file=sys.stderr,
                )
                sys.exit(1)

            for r in roots_resp:
                if (r.get("host") or "") != host:
                    continue
                root_norm = _normalize_root_for_trim(r.get("root_path") or "")
                roots.append((root_norm, _latest_iso_date(r.get("latest_complete_at"))))

            if not roots:
                print(
                    f"sift: no complete scan roots found for host '{host}'. "
                    "Run a complete scan first or provide an explicit path.",
                    file=sys.stderr,
                )
                sys.exit(1)

        if unsafe_mode_latest:
            if not has_explicit_path:
                # Apply to all effective roots with their own latest complete date.
                by_root = {}
                for root_norm, latest_date in roots:
                    by_root[root_norm] = latest_date
                missing = [rp for rp, dt in by_root.items() if not dt]
                if missing:
                    print(
                        "sift: latest root scan timestamp missing for: "
                        + ", ".join(sorted(missing)),
                        file=sys.stderr,
                    )
                    sys.exit(1)
                scope_cutoffs = sorted((rp, dt) for rp, dt in by_root.items())
            else:
                # Explicit path: use covering root's latest date (most specific).
                covering = [
                    (rp, dt) for rp, dt in roots if _root_covers(rp, path_prefix)
                ]
                if not covering:
                    print(
                        f"sift: path {path_prefix} is not covered by any complete scan root for host '{host}'.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                covering.sort(key=lambda x: len(x[0]), reverse=True)
                selected_root, selected_date = covering[0]
                if not selected_date:
                    print(
                        f"sift: latest complete scan date missing for covering root {selected_root}.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                scope_cutoffs = [(path_prefix, selected_date)]
        else:
            if not has_explicit_path:
                unique_roots = sorted({rp for rp, _ in roots})
                scope_cutoffs = [(rp, unsafe_not_seen_before) for rp in unique_roots]
            else:
                scope_cutoffs = [(path_prefix, unsafe_not_seen_before)]

    scopes = [p for p, _ in scope_cutoffs]

    if debug:
        mode = (
            "unsafe-not-seen-since"
            if unsafe_not_seen_since
            else ("deleted" if deleted_only else "targeted")
        )
        _debug(f"[trim] mode={mode}")
        _debug(f"[trim] host={host}")
        _debug(f"[trim] path={path_prefix or '/'}")
        if len(scopes) > 1:
            _debug(f"[trim] scopes={scopes}")
        _debug(f"[trim] recursive={recursive}")
        _debug(f"[trim] patterns={patterns or '[]'}")
        if unsafe_not_seen_since:
            if unsafe_mode_latest:
                _debug("[trim] unsafe_not_seen_before=latest (per-root)")
            else:
                _debug(f"[trim] unsafe_not_seen_before={unsafe_not_seen_before}")
            _debug(f"[trim] scope_cutoffs={scope_cutoffs}")
        _debug(f"[trim] batch_size={batch_size}")

    def _base_payload(scope_path: str, cutoff_date: str | None) -> dict:
        return {
            "host": host,
            "path_prefix": scope_path,
            "recursive": recursive,
            "deleted_only": deleted_only,
            "patterns": patterns,
            "limit": batch_size,
            "count_only": True,
            "preview": False,
            "offset": 0,
            "unsafe_not_seen_before": cutoff_date,
        }

    scope_totals: list[tuple[str, str | None, int]] = []
    total = 0
    for scope_path, cutoff_date in scope_cutoffs:
        payload = _base_payload(scope_path, cutoff_date)
        try:
            count_resp = client.post("/trim", payload)
        except Exception as e:
            print(f"sift: trim count failed: {e}", file=sys.stderr)
            sys.exit(1)
        matched = int(count_resp.get("matched", 0))
        scope_totals.append((scope_path, cutoff_date, matched))
        total += matched

    if total == 0:
        print("No matching inventory entries to trim.", file=sys.stderr)
        if (
            user_provided_host
            and not has_explicit_path
            and not deleted_only
            and not unsafe_not_seen_since
        ):
            print(
                f"Hint: default scope is current directory ({path_prefix or '/'}). "
                f"For host-wide trim on '{host}', use: sift trim -r / --host {host}",
                file=sys.stderr,
            )
        return

    if debug:
        _debug(f"[trim] matched={total:,}")

    if dry_run:
        mode_label = (
            "unsafe-age-based"
            if unsafe_not_seen_since
            else ("deleted-only" if deleted_only else "targeted")
        )
        print(
            f"Dry run: {total:,} inventory entr{'y' if total == 1 else 'ies'}"
            f" would be trimmed ({mode_label}) on host '{host}'"
            f" under {('multiple roots' if len(scopes) > 1 else (scopes[0] or '/'))}.",
            file=sys.stderr,
        )
        if len(scopes) > 1:
            print("Roots in scope:", file=sys.stderr)
            for scope_path, cutoff_date, scope_count in scope_totals:
                cutoff_txt = f"  cutoff<{cutoff_date}" if cutoff_date else ""
                print(
                    f"  {scope_path}  ({scope_count:,}){cutoff_txt}",
                    file=sys.stderr,
                )
        if verbose:
            shown = 0
            for scope_path, cutoff_date, scope_total in scope_totals:
                scope_shown = 0
                page = 0
                while scope_shown < scope_total:
                    page += 1
                    payload = _base_payload(scope_path, cutoff_date)
                    payload["preview"] = True
                    payload["offset"] = scope_shown
                    try:
                        preview_resp = client.post("/trim", payload)
                    except Exception as e:
                        print(
                            f"sift: trim dry-run preview failed: {e}", file=sys.stderr
                        )
                        sys.exit(1)
                    paths = preview_resp.get("preview_paths", []) or []
                    if not paths:
                        break
                    if debug:
                        _debug(
                            f"[trim] preview_page={page} rows={len(paths)}"
                            f" offset={scope_shown} scope={scope_path}"
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
                    scope_shown += len(paths)
                    shown += len(paths)
            if debug:
                _debug(f"[trim] preview_shown={shown:,}/{total:,}")
        return

    if not getattr(args, "quiet", False):
        mode_label = (
            "unsafe-age-based"
            if unsafe_not_seen_since
            else ("deleted-only" if deleted_only else "targeted")
        )
        print(
            f"Trimming {total:,} inventory entr{'y' if total == 1 else 'ies'}"
            f" ({mode_label})...",
            file=sys.stderr,
        )
        if len(scopes) > 1:
            print("Roots in scope:", file=sys.stderr)
            for scope_path, cutoff_date, scope_count in scope_totals:
                cutoff_txt = f"  cutoff<{cutoff_date}" if cutoff_date else ""
                print(
                    f"  {scope_path}  ({scope_count:,}){cutoff_txt}",
                    file=sys.stderr,
                )

    start = time.time()
    deleted_total = 0
    batch_no = 0

    for scope_path, cutoff_date, scope_total in scope_totals:
        scope_deleted = 0
        while scope_deleted < scope_total:
            batch_no += 1
            payload = _base_payload(scope_path, cutoff_date)
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

            scope_deleted += deleted
            deleted_total += deleted

            if debug:
                _debug(
                    f"[trim] batch={batch_no} deleted={deleted:,} "
                    f"deleted_total={deleted_total:,} matched_now={matched_now:,} "
                    f"scope={scope_path}"
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
        f" from host '{host}' under "
        f"{('multiple roots' if len(scopes) > 1 else (scopes[0] or '/'))}"
        f" in {_fmt_duration(elapsed)}.",
        file=sys.stderr,
    )
