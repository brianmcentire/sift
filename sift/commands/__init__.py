import os
import sys
from sift.config import get_cli_config, get_server_url
from sift.normalize import local_hostname


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
