"""Tests for config validation in sift.config._validate."""
import pytest
from sift.config import _validate


class TestValidateServerUrl:
    def test_valid_http_url(self):
        _validate({"server": {"url": "http://localhost:8765"}, "agent": {}, "cli": {}})

    def test_valid_https_url(self):
        _validate({"server": {"url": "https://myhost:8765"}, "agent": {}, "cli": {}})

    def test_empty_url_passes(self):
        _validate({"server": {"url": ""}, "agent": {}, "cli": {}})

    def test_numeric_url_rejected(self):
        with pytest.raises(ValueError, match="server.url"):
            _validate({"server": {"url": 12345}, "agent": {}, "cli": {}})

    def test_bare_hostname_rejected(self):
        with pytest.raises(ValueError, match="server.url"):
            _validate({"server": {"url": "myhost:8765"}, "agent": {}, "cli": {}})

    def test_ftp_url_rejected(self):
        with pytest.raises(ValueError, match="server.url"):
            _validate({"server": {"url": "ftp://myhost"}, "agent": {}, "cli": {}})


class TestValidateAgentFields:
    def _base(self, **agent_overrides):
        agent = {"host": "", "roots": ["/"], "volatile_mtime_threshold_days": 30,
                 "upsert_batch_size": 500, "seen_batch_size": 5000, "chunk_size_mb": 8}
        agent.update(agent_overrides)
        return {"server": {"url": "http://localhost:8765"}, "agent": agent, "cli": {}}

    def test_valid_defaults_pass(self):
        _validate(self._base())

    def test_string_threshold_rejected(self):
        with pytest.raises(ValueError, match="volatile_mtime_threshold_days"):
            _validate(self._base(volatile_mtime_threshold_days="thirty"))

    def test_zero_threshold_rejected(self):
        with pytest.raises(ValueError, match="volatile_mtime_threshold_days"):
            _validate(self._base(volatile_mtime_threshold_days=0))

    def test_negative_batch_size_rejected(self):
        with pytest.raises(ValueError, match="upsert_batch_size"):
            _validate(self._base(upsert_batch_size=-1))

    def test_float_batch_size_rejected(self):
        with pytest.raises(ValueError, match="upsert_batch_size"):
            _validate(self._base(upsert_batch_size=500.5))

    def test_string_seen_batch_rejected(self):
        with pytest.raises(ValueError, match="seen_batch_size"):
            _validate(self._base(seen_batch_size="large"))

    def test_string_chunk_size_rejected(self):
        with pytest.raises(ValueError, match="chunk_size_mb"):
            _validate(self._base(chunk_size_mb="eight"))

    def test_float_chunk_size_accepted(self):
        _validate(self._base(chunk_size_mb=4.5))

    def test_numeric_host_rejected(self):
        with pytest.raises(ValueError, match="agent.host"):
            _validate(self._base(host=123))

    def test_roots_not_list_rejected(self):
        with pytest.raises(ValueError, match="agent.roots"):
            _validate(self._base(roots="/home"))

    def test_roots_with_non_string_rejected(self):
        with pytest.raises(ValueError, match="agent.roots"):
            _validate(self._base(roots=["/home", 42]))


class TestValidateCliHost:
    def test_numeric_cli_host_rejected(self):
        with pytest.raises(ValueError, match="cli.host"):
            _validate({"server": {"url": "http://localhost:8765"},
                        "agent": {}, "cli": {"host": 999}})

    def test_string_cli_host_passes(self):
        _validate({"server": {"url": "http://localhost:8765"},
                    "agent": {}, "cli": {"host": "myhost"}})


class TestValidateMultipleErrors:
    def test_collects_all_errors(self):
        with pytest.raises(ValueError) as exc_info:
            _validate({"server": {"url": 42}, "agent": {"upsert_batch_size": "big"}, "cli": {}})
        msg = str(exc_info.value)
        assert "server.url" in msg
        assert "upsert_batch_size" in msg
