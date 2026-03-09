from types import SimpleNamespace

import pytest


def _args(**overrides):
    base = {
        "host": "mac",
        "debug": False,
        "recursive": True,
        "deleted": False,
        "batch_size": 5000,
        "dry_run": False,
        "verbose": False,
        "targets": ["/"],
        "path": None,
        "quiet": True,
        "unsafe_delete_not_seen_since": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_trim_unsafe_date_payload(monkeypatch, capsys):
    from sift.commands import trim as trim_cmd

    seen_payloads = []

    def fake_post(path, payload, timeout=None):
        del timeout
        assert path == "/trim"
        seen_payloads.append(payload)
        return {"matched": 0, "deleted": 0, "preview_paths": []}

    monkeypatch.setattr(trim_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(trim_cmd, "get_cli_config", lambda: {})
    monkeypatch.setattr(trim_cmd.client, "post", fake_post)

    trim_cmd.cmd_trim(_args(unsafe_delete_not_seen_since="20260309"))
    assert seen_payloads
    assert seen_payloads[0]["unsafe_not_seen_before"] == "2026-03-09"
    assert "No matching inventory entries" in capsys.readouterr().err


def test_trim_unsafe_date_requires_yyyymmdd(monkeypatch):
    from sift.commands import trim as trim_cmd

    monkeypatch.setattr(trim_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(trim_cmd, "get_cli_config", lambda: {})

    with pytest.raises(SystemExit) as exc:
        trim_cmd.cmd_trim(_args(unsafe_delete_not_seen_since="2026-03-09"))
    assert exc.value.code == 2
