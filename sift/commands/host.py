"""sift host — manage host visibility and metadata."""

from __future__ import annotations

import sys

from sift import client
from sift.commands import print_config_hint, resolve_host


def cmd_host(args) -> None:
    action = getattr(args, "host_action", None)
    if action is None:
        print("usage: sift host {list,hide,unhide,label,describe} ...", file=sys.stderr)
        sys.exit(1)

    if action == "list":
        _cmd_list(args)
    elif action == "hide":
        _cmd_hide(args)
    elif action == "unhide":
        _cmd_unhide(args)
    elif action == "label":
        _cmd_label(args)
    elif action == "describe":
        _cmd_describe(args)
    else:
        print(f"sift host: unknown action '{action}'", file=sys.stderr)
        sys.exit(1)


def _get_hosts():
    try:
        return client.get("/hosts")
    except Exception as e:
        print(f"sift: cannot reach server: {e}", file=sys.stderr)
        print_config_hint()
        sys.exit(1)


def _patch_host(name: str, body: dict) -> None:
    canonical = resolve_host(name)
    try:
        client.patch(f"/hosts/{canonical}", body)
    except Exception as e:
        print(f"sift: error: {e}", file=sys.stderr)
        sys.exit(1)


def _fmt_dt(dt_str: str | None) -> str:
    if not dt_str:
        return "never"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return dt_str or "?"


def _cmd_list(args) -> None:
    hosts = _get_hosts()
    verbose = getattr(args, "verbose", False)

    if not hosts:
        print("No hosts in datastore.")
        return

    rows = []
    for h in hosts:
        status = "hidden" if h.get("hidden") else "visible"
        files = f"{h.get('total_files', 0):,}"
        last = _fmt_dt(h.get("last_scan_at"))
        label = h.get("label") or ""
        row = {
            "name": h["host"],
            "status": status,
            "files": files,
            "last_scan": last,
            "label": label,
        }
        if verbose:
            row["description"] = h.get("description") or ""
        rows.append(row)

    # Compute column widths
    headers = ["NAME", "STATUS", "FILES", "LAST SCAN", "LABEL"]
    keys = ["name", "status", "files", "last_scan", "label"]
    if verbose:
        headers.append("DESCRIPTION")
        keys.append("description")

    widths = [len(h) for h in headers]
    for r in rows:
        for i, k in enumerate(keys):
            widths[i] = max(widths[i], len(r[k]))

    # Print header
    header = "  ".join(headers[i].ljust(widths[i]) for i in range(len(headers)))
    sep = "  ".join("-" * widths[i] for i in range(len(headers)))
    print(header)
    print(sep)
    for r in rows:
        line = "  ".join(
            r[keys[i]].rjust(widths[i]) if keys[i] == "files" else r[keys[i]].ljust(widths[i])
            for i in range(len(headers))
        )
        print(line)


def _cmd_hide(args) -> None:
    _patch_host(args.name, {"hidden": True})
    print(f"Host '{args.name}' is now hidden from default views.")


def _cmd_unhide(args) -> None:
    _patch_host(args.name, {"hidden": False})
    print(f"Host '{args.name}' is now visible in default views.")


def _cmd_label(args) -> None:
    if args.value is not None:
        _patch_host(args.name, {"label": args.value})
        if args.value:
            print(f"Label set for '{args.name}': {args.value}")
        else:
            print(f"Label cleared for '{args.name}'.")
    else:
        hosts = _get_hosts()
        canonical = resolve_host(args.name)
        host = next((h for h in hosts if h["host"].lower() == canonical.lower()), None)
        if not host:
            print(f"sift: host '{args.name}' not found", file=sys.stderr)
            sys.exit(1)
        label = host.get("label") or ""
        if label:
            print(label)
        else:
            print(f"(no label set for '{host['host']}')")


def _cmd_describe(args) -> None:
    if args.value is not None:
        _patch_host(args.name, {"description": args.value})
        if args.value:
            print(f"Description set for '{args.name}'.")
        else:
            print(f"Description cleared for '{args.name}'.")
    else:
        hosts = _get_hosts()
        canonical = resolve_host(args.name)
        host = next((h for h in hosts if h["host"].lower() == canonical.lower()), None)
        if not host:
            print(f"sift: host '{args.name}' not found", file=sys.stderr)
            sys.exit(1)
        desc = host.get("description") or ""
        if desc:
            print(desc)
        else:
            print(f"(no description set for '{host['host']}')")
