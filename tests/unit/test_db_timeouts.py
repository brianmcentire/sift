import threading
import time

import pytest

import server.db as db_module


class _FakeConn:
    def __init__(self):
        self.interrupted = False

    def interrupt(self):
        self.interrupted = True


def test_query_runtime_timeout_has_context():
    prev = db_module._DB_QUERY_TIMEOUT_SEC
    db_module._DB_QUERY_TIMEOUT_SEC = 0.01
    fake = _FakeConn()

    token = db_module.push_request_context("GET /stats/report/duplicates")
    try:
        with db_module.operation_context("report duplicates: top opportunities"):
            with pytest.raises(db_module.DBTimeoutError) as exc:
                db_module._run_with_query_timeout(
                    fake,
                    "SELECT 1",
                    lambda: (
                        time.sleep(0.02),
                        (_ for _ in ()).throw(RuntimeError("boom")),
                    ),
                )
        err = exc.value
        assert err.timeout_type == "query_runtime"
        assert err.endpoint == "GET /stats/report/duplicates"
        assert "top opportunities" in err.operation
        assert fake.interrupted is True
    finally:
        db_module.pop_request_context(token)
        db_module._DB_QUERY_TIMEOUT_SEC = prev


def test_lock_wait_timeout_has_context():
    prev = db_module._DB_LOCK_WAIT_TIMEOUT_SEC
    db_module._DB_LOCK_WAIT_TIMEOUT_SEC = 0.01

    release = threading.Event()

    def hold_lock():
        db_module._lock.acquire()
        try:
            release.wait(timeout=0.1)
        finally:
            db_module._lock.release()

    t = threading.Thread(target=hold_lock)
    t.start()
    time.sleep(0.01)

    token = db_module.push_request_context("GET /stats/report/inventory")
    try:
        with db_module.operation_context("report inventory: host totals"):
            with pytest.raises(db_module.DBTimeoutError) as exc:
                with db_module._acquire_lock("SELECT 1"):
                    pass
        err = exc.value
        assert err.timeout_type == "lock_wait"
        assert err.endpoint == "GET /stats/report/inventory"
        assert "host totals" in err.operation
    finally:
        db_module.pop_request_context(token)
        db_module._DB_LOCK_WAIT_TIMEOUT_SEC = prev
        release.set()
        t.join(timeout=0.2)
