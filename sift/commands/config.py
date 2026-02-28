"""sift config — interactively configure sift settings."""
from __future__ import annotations
import ipaddress
import re
import socket
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_PORT = 8765
CONFIG_PATH = Path.home() / ".sift.config"


def _validate_host(host: str) -> str | None:
    """Return None if valid, or an error message if not."""
    host = host.strip()
    if not host:
        return "Host cannot be empty."
    # Reject if it looks like it already includes a port or scheme
    if "://" in host or ":" in host:
        return "Enter just the hostname or IP, without a port or scheme."
    # Valid: IP address
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    # Valid: plain hostname (no dots) or .local mDNS name
    if "." not in host:
        return None
    if re.fullmatch(r"[a-zA-Z0-9-]+\.local", host):
        return None
    return "FQDNs are not supported — enter a hostname (e.g. 'unraid'), IP, or 'hostname.local'."


def _prompt(label: str, current: str, default: str) -> str | None:
    """Prompt for a value, showing current or default in brackets. Returns None on cancel."""
    shown = current or default
    try:
        raw = input(f"{label} [{shown}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return raw or shown


def _read_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


def _write_config(cfg: dict) -> None:
    """Write config dict as TOML, preserving section order."""
    lines = []
    for section, values in cfg.items():
        if not isinstance(values, dict):
            continue
        lines.append(f"[{section}]")
        for key, val in values.items():
            if isinstance(val, bool):
                lines.append(f"{key} = {'true' if val else 'false'}")
            elif isinstance(val, str):
                lines.append(f'{key} = "{val}"')
            elif isinstance(val, list):
                items = ", ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in val)
                lines.append(f"{key} = [{items}]")
            else:
                lines.append(f"{key} = {val}")
        lines.append("")
    CONFIG_PATH.write_text("\n".join(lines).rstrip("\n") + "\n")


def cmd_config(args) -> None:
    cfg = _read_config()
    auto_hostname = socket.gethostname().split(".")[0]

    # --- Server URL ---
    current_url = cfg.get("server", {}).get("url", "")
    current_server_host = ""
    if current_url.startswith("http://"):
        current_server_host = current_url[len("http://"):].split(":")[0]

    server_host = _prompt("Server hostname or IP", current_server_host, "localhost")
    if server_host is None:
        return

    error = _validate_host(server_host)
    if error:
        print(f"Error: {error}")
        return

    url = f"http://{server_host}:{DEFAULT_PORT}"
    cfg.setdefault("server", {})["url"] = url

    # --- Hostname override ---
    current_host = cfg.get("cli", {}).get("host", "")
    host = _prompt("This host's name", current_host, auto_hostname)
    if host is None:
        return

    if host == auto_hostname:
        # Auto-detected — no need to store an override
        cfg.get("cli", {}).pop("host", None)
        cfg.get("agent", {}).pop("host", None)
    else:
        cfg.setdefault("cli", {})["host"] = host
        cfg.setdefault("agent", {})["host"] = host

    _write_config(cfg)

    print()
    print(f"Saved: {CONFIG_PATH}")
    print(f"  server = {url}")
    print(f"    host = {host}")
    if host == auto_hostname:
        print(f"           (auto-detected)")
