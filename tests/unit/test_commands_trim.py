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
    def fake_get(path, params=None):
        if path == "/hosts":
            return [{"host": "mac"}]
        if path == "/hosts/roots":
            return [
                {
                    "host": "mac",
                    "drive": "",
                    "root_path": "/Users/Brian",
                    "latest_complete_at": "2026-03-09T00:00:00+00:00",
                }
            ]
        raise AssertionError(path)

    monkeypatch.setattr(trim_cmd.client, "get", fake_get)
    monkeypatch.setattr(trim_cmd.client, "post", fake_post)

    trim_cmd.cmd_trim(_args(unsafe_delete_not_seen_since="20260309", targets=[]))
    assert seen_payloads
    assert seen_payloads[0]["unsafe_not_seen_before"] == "2026-03-09"
    assert seen_payloads[0]["recursive"] is True
    assert seen_payloads[0]["path_prefix"] == "/users/brian"
    assert "No matching inventory entries" in capsys.readouterr().err


def test_trim_unsafe_date_requires_yyyymmdd(monkeypatch):
    from sift.commands import trim as trim_cmd

    monkeypatch.setattr(trim_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(trim_cmd, "get_cli_config", lambda: {})
    monkeypatch.setattr(trim_cmd.client, "get", lambda path, params=None: [{"host": "mac"}])

    with pytest.raises(SystemExit) as exc:
        trim_cmd.cmd_trim(_args(unsafe_delete_not_seen_since="2026-03-09"))
    assert exc.value.code == 2


def test_trim_unsafe_latest_uses_per_root_latest_dates(monkeypatch, capsys):
    from sift.commands import trim as trim_cmd

    calls = []

    def fake_get(path, params=None):
        if path == "/hosts":
            return [{"host": "mac"}]
        assert path == "/hosts/roots"
        assert params == {"host": "mac"}
        return [
            {
                "host": "mac",
                "drive": "",
                "root_path": "/Users/Brian",
                "latest_complete_at": "2026-03-09T22:11:00+00:00",
            },
            {
                "host": "mac",
                "drive": "",
                "root_path": "/Volumes/Archive",
                "latest_complete_at": "2026-03-08T11:00:00+00:00",
            },
        ]

    def fake_post(path, payload, timeout=None):
        del timeout
        assert path == "/trim"
        calls.append(payload.copy())
        return {"matched": 0, "deleted": 0, "preview_paths": []}

    monkeypatch.setattr(trim_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(trim_cmd, "get_cli_config", lambda: {})
    monkeypatch.setattr(trim_cmd.client, "get", fake_get)
    monkeypatch.setattr(trim_cmd.client, "post", fake_post)

    trim_cmd.cmd_trim(_args(unsafe_delete_not_seen_since="latest", targets=[]))
    got = [(p["path_prefix"], p["unsafe_not_seen_before"]) for p in calls]
    assert got == [
        ("/users/brian", "2026-03-09"),
        ("/volumes/archive", "2026-03-08"),
    ]
    assert "No matching inventory entries" in capsys.readouterr().err


def test_trim_unsafe_date_uses_all_effective_roots(monkeypatch, capsys):
    from sift.commands import trim as trim_cmd

    calls = []

    def fake_get(path, params=None):
        if path == "/hosts":
            return [{"host": "mac"}]
        assert path == "/hosts/roots"
        assert params == {"host": "mac"}
        return [
            {"host": "mac", "drive": "", "root_path": "/Users/Brian"},
            {"host": "mac", "drive": "", "root_path": "/Volumes/Archive"},
        ]

    def fake_post(path, payload, timeout=None):
        del timeout
        assert path == "/trim"
        calls.append(payload.copy())
        return {"matched": 0, "deleted": 0, "preview_paths": []}

    monkeypatch.setattr(trim_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(trim_cmd, "get_cli_config", lambda: {})
    monkeypatch.setattr(trim_cmd.client, "get", fake_get)
    monkeypatch.setattr(trim_cmd.client, "post", fake_post)

    trim_cmd.cmd_trim(_args(unsafe_delete_not_seen_since="20260309", targets=[]))
    got_paths = [p["path_prefix"] for p in calls]
    assert got_paths == ["/users/brian", "/volumes/archive"]
    err = capsys.readouterr().err
    assert "No matching inventory entries" in err


def test_trim_unsafe_date_respects_explicit_path(monkeypatch):
    from sift.commands import trim as trim_cmd

    seen_payloads = []

    def fake_post(path, payload, timeout=None):
        del timeout
        assert path == "/trim"
        seen_payloads.append(payload.copy())
        return {"matched": 0, "deleted": 0, "preview_paths": []}

    def fake_get(path, params=None):
        if path == "/hosts":
            return [{"host": "mac"}]
        raise AssertionError(f"unexpected get: {path}")

    monkeypatch.setattr(trim_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(trim_cmd, "get_cli_config", lambda: {})
    monkeypatch.setattr(trim_cmd.client, "get", fake_get)
    monkeypatch.setattr(trim_cmd.client, "post", fake_post)

    trim_cmd.cmd_trim(
        _args(
            unsafe_delete_not_seen_since="20260309",
            path="/Users/Brian/Downloads",
            targets=[],
            recursive=False,
        )
    )
    assert seen_payloads
    assert seen_payloads[0]["path_prefix"] == "/users/brian/downloads"
    assert seen_payloads[0]["recursive"] is True


def test_trim_unsafe_latest_explicit_path_uses_covering_root_date(monkeypatch):
    from sift.commands import trim as trim_cmd

    seen_payloads = []

    def fake_get(path, params=None):
        if path == "/hosts":
            return [{"host": "mac"}]
        assert path == "/hosts/roots"
        assert params == {"host": "mac"}
        return [
            {
                "host": "mac",
                "drive": "",
                "root_path": "/Users/Brian",
                "latest_complete_at": "2026-03-09T22:11:00+00:00",
            },
            {
                "host": "mac",
                "drive": "",
                "root_path": "/Volumes/Archive",
                "latest_complete_at": "2026-03-08T11:00:00+00:00",
            },
        ]

    def fake_post(path, payload, timeout=None):
        del timeout
        assert path == "/trim"
        seen_payloads.append(payload.copy())
        return {"matched": 0, "deleted": 0, "preview_paths": []}

    monkeypatch.setattr(trim_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(trim_cmd, "get_cli_config", lambda: {})
    monkeypatch.setattr(trim_cmd.client, "get", fake_get)
    monkeypatch.setattr(trim_cmd.client, "post", fake_post)

    trim_cmd.cmd_trim(
        _args(
            unsafe_delete_not_seen_since="latest",
            path="/Users/Brian/Downloads",
            targets=[],
            recursive=False,
        )
    )
    assert seen_payloads
    assert seen_payloads[0]["path_prefix"] == "/users/brian/downloads"
    assert seen_payloads[0]["unsafe_not_seen_before"] == "2026-03-09"
