import os
import sys
from sift.config import get_cli_config, get_server_url
from sift.normalize import local_hostname, normalize_query_path


def extract_drive_path(raw_path: str) -> tuple[str, str]:
    """Detect a Windows drive letter in a user-supplied path and split it out.

    Returns (drive, normalized_posix_path) where drive is '' for POSIX paths.
    Examples:
      'D:/Users/Brian'  → ('D', '/users/brian')
      'C:\\temp'        → ('C', '/temp')
      '/mnt/data'       → ('', '/mnt/data')
      '.'               → ('', <cwd resolved by normalize_query_path>)
    """
    raw = raw_path.strip().replace("\\", "/")
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        drive = raw[0].upper()
        path = raw[2:].lower() or "/"
        if not path.startswith("/"):
            path = "/" + path
        return drive, path
    return "", normalize_query_path(raw_path)


def parse_host_path(arg: str, default_host: str) -> tuple[str, str]:
    """Parse 'host:/path', 'host:C:/path', or '/path' into (host, normalized_path).

    Rules:
    1. Starts with '/' or '.' → local path (default_host)
    2. Single alpha char before ':' → Windows drive letter, local path (default_host)
    3. Multi-char prefix before ':' where remainder starts with drive letter
       (e.g. host:C:/) → host + drive path
    4. Multi-char prefix before ':/' → host + path
    5. 'localhost' as host → resolves to local_hostname()
    """
    # Normalize backslashes to forward slashes for consistent parsing
    arg = arg.replace("\\", "/")

    # Rule 1: starts with / or . → local path
    if arg.startswith("/") or arg.startswith("."):
        return (resolve_host(default_host), normalize_query_path(arg))

    # Find first colon
    colon_idx = arg.find(":")
    if colon_idx < 0:
        # No colon at all — treat as local relative path
        return (resolve_host(default_host), normalize_query_path(arg))

    prefix = arg[:colon_idx]
    remainder = arg[colon_idx + 1:]

    # Rule 2: single alpha char before ':' → Windows drive letter (e.g. C:/Users)
    if len(prefix) == 1 and prefix.isalpha():
        return (resolve_host(default_host), normalize_query_path(arg))

    # Multi-char prefix → host:path
    host_part = prefix

    # Rule 3: remainder starts with drive letter (e.g. C:/ or C:)
    if len(remainder) >= 2 and remainder[0].isalpha() and remainder[1] == ":":
        # host:C:/path → path is the drive path portion
        path_part = remainder
    elif remainder.startswith("/"):
        # Rule 4: host:/path
        path_part = remainder
    else:
        # Ambiguous — treat entire arg as local path
        return (resolve_host(default_host), normalize_query_path(arg))

    # Rule 5: 'localhost' → local hostname
    resolved_host = resolve_host(host_part)
    # For Windows drive paths, normalize just converts \ to / and lowercases
    normalized = path_part.replace("\\", "/").lower()
    return (resolved_host, normalized)


def _effective_hostname() -> str:
    """Return the hostname sift will use: SIFT_HOST env > config > auto-detect."""
    return os.environ.get("SIFT_HOST") or get_cli_config().get("host") or local_hostname()


def resolve_host(user_input: str) -> str:
    """Resolve a user-supplied hostname to its canonical server-side spelling.

    Handles:
    - 'localhost' / '127.0.0.1' → local machine's short hostname
    - Case-insensitive match against /hosts for canonical spelling
    - Silent fallback to user_input if server is unreachable or host not found
    """
    normalized = user_input.strip()
    if normalized.lower() in ("localhost", "127.0.0.1"):
        normalized = local_hostname()

    try:
        from sift import client
        hosts = client.get("/hosts")
        canonical = next(
            (h["host"] for h in hosts if h["host"].lower() == normalized.lower()),
            None,
        )
        if canonical is not None:
            return canonical
    except Exception:
        pass

    return normalized


def print_server_info() -> None:
    """Print version, server URL, and client hostname to stderr (TTY only)."""
    if sys.stderr.isatty():
        print(f"sift {get_version()}", file=sys.stderr)
        print(f"  {_effective_hostname()} \u2192 {get_server_url()}", file=sys.stderr)


def print_config_hint() -> None:
    """Print a hint to run 'sift config' if no config file exists."""
    from pathlib import Path
    config_path = Path.home() / ".sift.config"
    if not config_path.exists():
        print("  hint: run 'sift config' to set your server address", file=sys.stderr)


def get_version() -> str:
    # Prefer pyproject.toml so editable installs always reflect the latest version
    try:
        import tomllib
        from pathlib import Path
        pyproject = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except Exception:
        pass
    try:
        from importlib.metadata import version
        return version("sift")
    except Exception:
        return "unknown"
