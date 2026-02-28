"""Tests for sift.commands.__init__ — effective hostname and config hint."""
from unittest.mock import patch

import pytest


class TestEffectiveHostname:
    """_effective_hostname resolves: SIFT_HOST env > config host > auto-detect."""

    def test_auto_detect_when_nothing_set(self):
        from sift.commands import _effective_hostname

        with patch.dict("os.environ", {}, clear=True), \
             patch("sift.commands.get_cli_config", return_value={"host": ""}), \
             patch("sift.commands.local_hostname", return_value="mypc"):
            assert _effective_hostname() == "mypc"

    def test_config_overrides_auto_detect(self):
        from sift.commands import _effective_hostname

        with patch.dict("os.environ", {}, clear=True), \
             patch("sift.commands.get_cli_config", return_value={"host": "configured-host"}), \
             patch("sift.commands.local_hostname", return_value="mypc"):
            assert _effective_hostname() == "configured-host"

    def test_env_overrides_config(self):
        from sift.commands import _effective_hostname

        with patch.dict("os.environ", {"SIFT_HOST": "env-host"}), \
             patch("sift.commands.get_cli_config", return_value={"host": "configured-host"}), \
             patch("sift.commands.local_hostname", return_value="mypc"):
            assert _effective_hostname() == "env-host"

    def test_env_overrides_auto_detect(self):
        from sift.commands import _effective_hostname

        with patch.dict("os.environ", {"SIFT_HOST": "env-host"}), \
             patch("sift.commands.get_cli_config", return_value={"host": ""}), \
             patch("sift.commands.local_hostname", return_value="mypc"):
            assert _effective_hostname() == "env-host"

    def test_empty_config_falls_through(self):
        from sift.commands import _effective_hostname

        with patch.dict("os.environ", {}, clear=True), \
             patch("sift.commands.get_cli_config", return_value={}), \
             patch("sift.commands.local_hostname", return_value="fallback"):
            assert _effective_hostname() == "fallback"


class TestPrintConfigHint:
    """print_config_hint only prints when no config file exists."""

    def test_no_hint_when_config_exists(self, capsys, tmp_path):
        from sift.commands import print_config_hint

        config_file = tmp_path / ".sift.config"
        config_file.write_text("")
        with patch("pathlib.Path.home", return_value=tmp_path):
            print_config_hint()
        assert capsys.readouterr().err == ""

    def test_hint_when_no_config(self, capsys, tmp_path):
        from sift.commands import print_config_hint

        with patch("pathlib.Path.home", return_value=tmp_path):
            print_config_hint()
        assert "sift config" in capsys.readouterr().err
