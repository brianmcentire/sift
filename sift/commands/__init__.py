import sys
from sift.config import get_server_url


def print_server_info() -> None:
    """Print the active server URL to stderr, but only when output is a TTY."""
    if sys.stderr.isatty():
        print(f"sift server: {get_server_url()}", file=sys.stderr)
