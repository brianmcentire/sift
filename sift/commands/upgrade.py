"""sift upgrade — upgrade sift to the latest version from GitHub."""
from __future__ import annotations
import subprocess
import sys

from sift.commands import get_version

_INSTALL_URL = "git+https://github.com/brianmcentire/sift.git"


def _is_editable() -> bool:
    try:
        import importlib.metadata as _meta
        direct_url = _meta.distribution("sift").read_text("direct_url.json")
        return bool(direct_url and '"editable": true' in direct_url)
    except Exception:
        return False


def cmd_upgrade(args) -> None:
    print(f"Current version: {get_version()}")

    if getattr(sys, "frozen", False):
        print(
            "This is a standalone binary install — pip cannot upgrade it.\n"
            "To upgrade, rebuild with:  make dist-agent\n"
            "then copy the new binary to this machine."
        )
        return

    if _is_editable():
        print(
            "This is an editable (dev) install — use 'git pull' instead.\n"
            "sift upgrade is for pip-installed agents, not the dev machine."
        )
        return

    print("Fetching latest from GitHub...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", _INSTALL_URL],
        check=False,
    )
    if result.returncode == 0:
        print("Done. Restart sift to use the new version.")
    else:
        print("Upgrade failed.", file=sys.stderr)
        sys.exit(result.returncode)
