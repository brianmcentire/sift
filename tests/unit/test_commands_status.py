from types import SimpleNamespace


def test_status_showroots_prints_effective_roots(monkeypatch, capsys):
    from sift.commands import status as status_cmd

    def fake_get(path, params=None):
        if path == "/hosts":
            return [
                {
                    "host": "mac",
                    "last_scan_at": "2026-03-09T01:00:00+00:00",
                    "last_scan_root": "/users",
                    "total_files": 10,
                    "total_bytes": 1000,
                    "total_hashed": 9,
                }
            ]
        if path == "/scan-runs":
            return []
        if path == "/hosts/roots":
            assert params is None
            return [
                {
                    "host": "mac",
                    "drive": "",
                    "root_path": "/Users",
                    "latest_complete_at": "2026-03-09T02:00:00+00:00",
                }
            ]
        raise AssertionError(path)

    monkeypatch.setattr(status_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(status_cmd, "print_config_hint", lambda: None)
    monkeypatch.setattr(status_cmd.client, "get", fake_get)

    args = SimpleNamespace(host=None, stats=False, verbose=False, showroots=True)
    status_cmd.cmd_status(args)
    out = capsys.readouterr().out
    assert "effective complete roots" in out
    assert "/Users" in out
    assert "2026-03-09 02:00 UTC" in out


def test_status_showroots_passes_host_filter(monkeypatch, capsys):
    from sift.commands import status as status_cmd

    def fake_get(path, params=None):
        if path == "/hosts":
            return []
        if path == "/scan-runs":
            return []
        if path == "/hosts/roots":
            assert params == {"host": "Unraid"}
            return []
        raise AssertionError(path)

    monkeypatch.setattr(status_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(status_cmd, "print_config_hint", lambda: None)
    monkeypatch.setattr(status_cmd.client, "get", fake_get)

    args = SimpleNamespace(host="Unraid", stats=False, verbose=False, showroots=True)
    status_cmd.cmd_status(args)
    out = capsys.readouterr().out
    assert "effective complete roots: none" in out


def test_status_host_filter_does_not_imply_verbose(monkeypatch, capsys):
    from sift.commands import status as status_cmd

    def fake_get(path, params=None):
        if path == "/hosts":
            return [
                {
                    "host": "mac",
                    "last_scan_at": "2026-03-09T01:00:00+00:00",
                    "last_scan_root": "/users",
                    "total_files": 10,
                    "total_bytes": 1000,
                    "total_hashed": 9,
                }
            ]
        if path == "/scan-runs":
            return [
                {
                    "id": 1,
                    "host": "mac",
                    "root_path": "/users",
                    "root_path_display": "/Users",
                    "status": "complete",
                    "started_at": "2026-03-09T01:00:00+00:00",
                }
            ]
        if path == "/hosts/roots":
            return []
        raise AssertionError(path)

    monkeypatch.setattr(status_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(status_cmd, "print_config_hint", lambda: None)
    monkeypatch.setattr(status_cmd.client, "get", fake_get)

    args = SimpleNamespace(host="mac", stats=False, verbose=False, showroots=False)
    status_cmd.cmd_status(args)
    out = capsys.readouterr().out
    assert "recent scans" not in out
