"""
Integration test configuration.

Set SIFT_TEST_SERVER to run these tests against a live server, e.g.:
    SIFT_TEST_SERVER=http://192.168.1.200:8765 pytest -m integration

Tests are skipped automatically if SIFT_TEST_SERVER is not set.
"""
import os
import pytest
import requests


SIFT_TEST_SERVER = os.environ.get("SIFT_TEST_SERVER", "http://192.168.1.200:8765")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests that call the live Unraid server",
    )


@pytest.fixture(scope="session")
def live_client():
    """
    A thin wrapper around requests.Session pointed at the live server.
    Skips if the server is unreachable.
    """
    session = requests.Session()
    session.base_url = SIFT_TEST_SERVER

    # Connectivity check
    try:
        r = session.get(f"{SIFT_TEST_SERVER}/hosts", timeout=5)
        r.raise_for_status()
    except Exception as e:
        pytest.skip(f"Live server not reachable at {SIFT_TEST_SERVER}: {e}")

    return session


def get(session, path, **params):
    url = f"{session.base_url}{path}"
    r = session.get(url, params=params or None, timeout=30)
    r.raise_for_status()
    return r.json()
