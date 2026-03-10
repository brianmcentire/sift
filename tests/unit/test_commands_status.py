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


def test_status_host_filter_resolves_localhost(monkeypatch, capsys):
    from sift.commands import status as status_cmd

    monkeypatch.setattr(status_cmd, "local_hostname", lambda: "mymac")

    def fake_get(path, params=None):
        if path == "/hosts":
            return [
                {
                    "host": "mymac",
                    "last_scan_at": "2026-03-04T04:04:00+00:00",
                    "last_scan_root": "/users",
                    "total_files": 100,
                    "total_bytes": 1024,
                    "total_hashed": 100,
                }
            ]
        if path == "/scan-runs":
            return []
        raise AssertionError(path)

    monkeypatch.setattr(status_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(status_cmd, "print_config_hint", lambda: None)
    monkeypatch.setattr(status_cmd.client, "get", fake_get)

    args = SimpleNamespace(host="localhost", stats=False, verbose=False, showroots=False)
    status_cmd.cmd_status(args)
    out = capsys.readouterr().out
    assert "mymac" in out


def test_status_host_filter_is_case_insensitive(monkeypatch, capsys):
    from sift.commands import status as status_cmd

    def fake_get(path, params=None):
        if path == "/hosts":
            return [
                {
                    "host": "Unraid",
                    "last_scan_at": "2026-03-04T04:04:00+00:00",
                    "last_scan_root": "/mnt/user/media",
                    "total_files": 100,
                    "total_bytes": 1024,
                    "total_hashed": 100,
                }
            ]
        if path == "/scan-runs":
            assert params == {"limit": 50, "host": "Unraid"}
            return []
        if path == "/hosts/roots":
            assert params == {"host": "Unraid"}
            return []
        raise AssertionError(path)

    monkeypatch.setattr(status_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(status_cmd, "print_config_hint", lambda: None)
    monkeypatch.setattr(status_cmd.client, "get", fake_get)

    args = SimpleNamespace(host="unraid", stats=False, verbose=False, showroots=True)
    status_cmd.cmd_status(args)
    out = capsys.readouterr().out
    assert "Unraid" in out
