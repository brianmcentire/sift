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

    return cfg


# Module-level singleton — loaded once per process
_config: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_server_url() -> str:
    return get_config()["server"]["url"]


def get_agent_config() -> dict[str, Any]:
    return get_config()["agent"]


def get_cli_config() -> dict[str, Any]:
    return get_config()["cli"]
