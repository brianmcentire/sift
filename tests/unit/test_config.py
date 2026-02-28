"""Tests for sift.commands.config — interactive configuration."""
from unittest.mock import patch
import pytest

from sift.commands.config import _validate_host, _prompt


class TestValidateHost:
    """Host validation for sift config."""

    def test_plain_hostname(self):
        assert _validate_host("unraid") is None

    def test_ip_address(self):
        assert _validate_host("192.168.1.200") is None

    def test_local_mdns(self):
        assert _validate_host("myserver.local") is None

    def test_rejects_empty(self):
        assert _validate_host("") is not None

    def test_rejects_scheme(self):
        err = _validate_host("http://myserver")
        assert err is not None
        assert "scheme" in err.lower() or "port" in err.lower()

    def test_rejects_port(self):
        err = _validate_host("myserver:8765")
        assert err is not None

    def test_rejects_fqdn(self):
        err = _validate_host("server.example.com")
        assert err is not None
        assert "FQDN" in err


class TestPrompt:
    """_prompt shows current or default in brackets, returns on Enter."""

    def test_user_enters_value(self):
        with patch("builtins.input", return_value="192.168.1.100"):
            result = _prompt("Server", "", "localhost")
        assert result == "192.168.1.100"

    def test_enter_uses_current(self):
        with patch("builtins.input", return_value=""):
            result = _prompt("Server", "existing-host", "localhost")
        assert result == "existing-host"

    def test_enter_uses_default_when_no_current(self):
        with patch("builtins.input", return_value=""):
            result = _prompt("Server", "", "localhost")
        assert result == "localhost"

    def test_ctrl_c_returns_none(self):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = _prompt("Server", "", "localhost")
        assert result is None

    def test_eof_returns_none(self):
        with patch("builtins.input", side_effect=EOFError):
            result = _prompt("Server", "", "localhost")
        assert result is None


class TestCmdConfig:
    """cmd_config writes config file with server URL and optional hostname."""

    def test_fresh_config_defaults(self, tmp_path):
        from sift.commands import config as config_mod

        config_file = tmp_path / ".sift.config"
        inputs = iter(["myserver", ""])  # server host, accept auto hostname

        with patch.object(config_mod, "CONFIG_PATH", config_file), \
             patch("builtins.input", lambda prompt: next(inputs)), \
             patch("socket.gethostname", return_value="DESKTOP-ABC"):
            config_mod.cmd_config(None)

        content = config_file.read_text()
        assert "http://myserver:8765" in content
        # Auto-detected hostname should NOT be stored
        assert "DESKTOP-ABC" not in content

    def test_custom_hostname_stored(self, tmp_path):
        from sift.commands import config as config_mod

        config_file = tmp_path / ".sift.config"
        inputs = iter(["myserver", "my-custom-pc"])

        with patch.object(config_mod, "CONFIG_PATH", config_file), \
             patch("builtins.input", lambda prompt: next(inputs)), \
             patch("socket.gethostname", return_value="DESKTOP-ABC"):
            config_mod.cmd_config(None)

        content = config_file.read_text()
        assert "http://myserver:8765" in content
        assert "my-custom-pc" in content

    def test_existing_config_preserved_on_enter(self, tmp_path):
        from sift.commands import config as config_mod

        config_file = tmp_path / ".sift.config"
        config_file.write_text('[server]\nurl = "http://oldserver:8765"\n')
        inputs = iter(["", ""])  # accept both defaults

        with patch.object(config_mod, "CONFIG_PATH", config_file), \
             patch("builtins.input", lambda prompt: next(inputs)), \
             patch("socket.gethostname", return_value="DESKTOP-ABC"):
            config_mod.cmd_config(None)

        content = config_file.read_text()
        assert "http://oldserver:8765" in content

    def test_cancel_on_server_prompt(self, tmp_path):
        from sift.commands import config as config_mod

        config_file = tmp_path / ".sift.config"

        with patch.object(config_mod, "CONFIG_PATH", config_file), \
             patch("builtins.input", side_effect=KeyboardInterrupt), \
             patch("socket.gethostname", return_value="DESKTOP-ABC"):
            config_mod.cmd_config(None)

        assert not config_file.exists()
