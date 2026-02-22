"""Shared HTTP client with retry logic."""
from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from sift.config import get_server_url


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PATCH"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# Module-level singleton — reuses TCP connections across all requests in a process
_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _make_session()
    return _session


def api_url(path: str) -> str:
    """Construct full API URL from config server URL + path."""
    base = get_server_url().rstrip("/")
    return f"{base}{path}"


def get(path: str, params: dict | None = None) -> Any:
    resp = _get_session().get(api_url(path), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def post(path: str, data: Any, timeout: int = 60) -> Any:
    resp = _get_session().post(api_url(path), json=data, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def patch(path: str, data: Any) -> Any:
    resp = _get_session().patch(api_url(path), json=data, timeout=30)
    resp.raise_for_status()
    return resp.json()
