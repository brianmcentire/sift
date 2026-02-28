import os
import sys
from sift.config import get_cli_config, get_server_url
from sift.normalize import local_hostname


def _effective_hostname() -> str:
    """Return the hostname sift will use: SIFT_HOST env > config > auto-detect."""
    return os.environ.get("SIFT_HOST") or get_cli_config().get("host") or local_hostname()


def print_server_info() -> None:
    """Print version, server URL, and client hostname to stderr (TTY only)."""
    if sys.stderr.isatty():
        print(f"sift {get_version()}", file=sys.stderr)
        print(f"  {_effective_hostname()} \u2192 {get_server_url()}", file=sys.stderr)


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
