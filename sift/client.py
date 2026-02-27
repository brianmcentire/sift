"""Shared HTTP client with retry logic."""
from __future__ import annotations

import threading
import time
import traceback
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from sift.config import get_server_url


# ---------------------------------------------------------------------------
# Request instrumentation (enabled via enable_request_log())
# ---------------------------------------------------------------------------
_request_log_enabled = False
_request_log_lock = threading.Lock()
_request_log: list[dict] = []


def enable_request_log() -> None:
    global _request_log_enabled
    _request_log_enabled = True


def _log_request(method: str, path: str) -> None:
    if not _request_log_enabled:
        return
    # Capture a short caller summary (skip client.py frames)
    frames = traceback.extract_stack()
    callers = [
        f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno}:{f.name}"
        for f in frames[:-1]
        if "client.py" not in f.filename
    ][-3:]  # last 3 non-client frames
    entry = {
        "t": time.time(),
        "method": method,
        "path": path,
        "callers": " < ".join(reversed(callers)),
        "thread": threading.current_thread().name,
    }
    with _request_log_lock:
        _request_log.append(entry)


def dump_request_log() -> list[dict]:
    """Return and clear the request log."""
    with _request_log_lock:
        log = _request_log[:]
        _request_log.clear()
    return log


def _make_session() -> requests.Session:
    # No urllib3-level retries — scan.py's _post_with_retry handles retry/backoff,
    # and urllib3 retrying internally would silently multiply timeouts (5× per call).
    session = requests.Session()
    adapter = HTTPAdapter()
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
    _log_request("GET", path)
    resp = _get_session().get(api_url(path), params=params, timeout=(5, 30))
    resp.raise_for_status()
    return resp.json()


def post(path: str, data: Any, timeout: tuple = (5, 30)) -> Any:
    _log_request("POST", path)
    resp = _get_session().post(api_url(path), json=data, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def patch(path: str, data: Any) -> Any:
    _log_request("PATCH", path)
    resp = _get_session().patch(api_url(path), json=data, timeout=(5, 30))
    resp.raise_for_status()
    return resp.json()


def get_stream(path: str, params: dict | None = None) -> requests.Response:
    """Return a streaming Response. Caller should use as a context manager."""
    _log_request("GET(stream)", path)
    resp = _get_session().get(api_url(path), params=params, timeout=(5, 120), stream=True)
    resp.raise_for_status()
    return resp
