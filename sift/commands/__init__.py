import sys
from sift.config import get_server_url


def print_server_info() -> None:
    """Print the active server URL to stderr, but only when output is a TTY."""
    if sys.stderr.isatty():
        print(f"sift server: {get_server_url()}", file=sys.stderr)


def get_version() -> str:
    try:
        from importlib.metadata import version
        return version("sift")
    except Exception:
        return "unknown"
