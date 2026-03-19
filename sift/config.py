"""Load ~/.sift.config (TOML) with env-var overrides."""
from __future__ import annotations
import os
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]  # Python < 3.11 backport
from pathlib import Path
from typing import Any

_DEFAULT: dict[str, Any] = {
    "server": {
        "url": "http://localhost:8765",
    },
    "agent": {
        "host": "",
        "roots": ["/"],
        "volatile_mtime_threshold_days": 30,
        "upsert_batch_size": 500,
        "seen_batch_size": 5000,
        "chunk_size_mb": 8,
    },
    "cli": {
        "host": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config() -> dict[str, Any]:
    cfg = dict(_DEFAULT)
    for section in cfg:
        cfg[section] = dict(cfg[section])

    # Config file resolution order:
    #   1. SIFT_CONFIG_PATH env var (used in Docker to point into /data)
    #   2. ~/.sift.config (default for local installs)
    config_path = Path(os.environ["SIFT_CONFIG_PATH"]) if "SIFT_CONFIG_PATH" in os.environ else Path.home() / ".sift.config"
    if config_path.exists():
        with open(config_path, "rb") as f:
            user_cfg = tomllib.load(f)
        cfg = _deep_merge(cfg, user_cfg)

    # Env var overrides
    if url := os.environ.get("SIFT_SERVER"):
        cfg["server"]["url"] = url
    if db_path := os.environ.get("SIFT_DB_PATH"):
        cfg["_db_path"] = db_path

    # Normalize server.url: prepend http:// if no scheme, append default port
    url = cfg.get("server", {}).get("url", "")
    if url and "://" not in url:
        url = "http://" + url
    if url:
        # If URL has no port (e.g. http://localhost), append default :8765
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.port is None and parsed.hostname:
            url = f"{parsed.scheme}://{parsed.hostname}:8765"
        cfg["server"]["url"] = url

    _validate(cfg)
    return cfg


def _validate(cfg: dict[str, Any]) -> None:
    """Validate critical config fields so typos surface early."""
    errors: list[str] = []

    # server.url
    url = cfg.get("server", {}).get("url", "")
    if url and (not isinstance(url, str) or not url.startswith(("http://", "https://"))):
        errors.append(f"server.url must be a string starting with http:// or https://, got {url!r}")

    # agent section
    agent = cfg.get("agent", {})
    _check_positive_number(errors, agent, "volatile_mtime_threshold_days")
    _check_positive_int(errors, agent, "upsert_batch_size")
    _check_positive_int(errors, agent, "seen_batch_size")
    _check_positive_number(errors, agent, "chunk_size_mb")

    if "host" in agent and not isinstance(agent["host"], str):
        errors.append(f"agent.host must be a string, got {type(agent['host']).__name__}")

    if "roots" in agent:
        roots = agent["roots"]
        if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots):
            errors.append(f"agent.roots must be a list of strings, got {roots!r}")

    # cli.host
    cli_host = cfg.get("cli", {}).get("host", "")
    if cli_host and not isinstance(cli_host, str):
        errors.append(f"cli.host must be a string, got {type(cli_host).__name__}")

    if errors:
        raise ValueError("Invalid sift config:\n  " + "\n  ".join(errors))


def _check_positive_number(errors: list[str], section: dict, key: str) -> None:
    if key in section and (not isinstance(section[key], (int, float)) or section[key] <= 0):
        errors.append(f"agent.{key} must be a positive number, got {section[key]!r}")


def _check_positive_int(errors: list[str], section: dict, key: str) -> None:
    if key in section and (not isinstance(section[key], int) or section[key] <= 0):
        errors.append(f"agent.{key} must be a positive integer, got {section[key]!r}")


# Module-level singleton — loaded once per process
_config: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_server_url() -> str:
    url = get_config()["server"]["url"]
    if url and "://" not in url:
        url = "http://" + url
    return url


def get_agent_config() -> dict[str, Any]:
    return get_config()["agent"]


def get_cli_config() -> dict[str, Any]:
    return get_config()["cli"]
