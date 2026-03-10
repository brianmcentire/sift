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
        if path == "/aggregate-status":
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
        if path == "/aggregate-status":
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
        if path == "/aggregate-status":
            return []
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
        if path == "/aggregate-status":
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
        if path == "/aggregate-status":
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


def test_status_shows_stale_in_summary(monkeypatch, capsys):
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
        if path == "/aggregate-status":
            return [
                {"key": "hash_stats", "status": "stale",
                 "updated_at": "2026-03-09T13:39:55+00:00",
                 "note": "Queued for refresh after scan completion"},
                {"key": "directory_index", "status": "stale",
                 "updated_at": "2026-03-09T13:39:55+00:00",
                 "note": "Queued for refresh after scan completion"},
                {"key": "host_hash_stats:mac", "status": "fresh",
                 "updated_at": "2026-03-09T13:39:55+00:00", "note": None},
            ]
        raise AssertionError(path)

    monkeypatch.setattr(status_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(status_cmd, "print_config_hint", lambda: None)
    monkeypatch.setattr(status_cmd.client, "get", fake_get)

    args = SimpleNamespace(host=None, stats=False, verbose=False, showroots=False)
    status_cmd.cmd_status(args)
    out = capsys.readouterr().out
    assert "dup stats stale" in out
    # Not verbose — no detail section
    assert "stale aggregates" not in out


def test_status_shows_building_in_summary(monkeypatch, capsys):
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
        if path == "/aggregate-status":
            return [
                {"key": "hash_stats", "status": "building",
                 "updated_at": "2026-03-09T13:39:55+00:00", "note": None},
            ]
        raise AssertionError(path)

    monkeypatch.setattr(status_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(status_cmd, "print_config_hint", lambda: None)
    monkeypatch.setattr(status_cmd.client, "get", fake_get)

    args = SimpleNamespace(host=None, stats=False, verbose=False, showroots=False)
    status_cmd.cmd_status(args)
    out = capsys.readouterr().out
    assert "dup stats building" in out


def test_status_verbose_shows_stale_detail(monkeypatch, capsys):
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
        if path == "/aggregate-status":
            return [
                {"key": "hash_stats", "status": "stale",
                 "updated_at": "2026-03-09T13:39:55+00:00",
                 "note": "Queued for refresh after scan completion"},
                {"key": "directory_index", "status": "stale",
                 "updated_at": "2026-03-09T13:39:55+00:00",
                 "note": None},
            ]
        raise AssertionError(path)

    monkeypatch.setattr(status_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(status_cmd, "print_config_hint", lambda: None)
    monkeypatch.setattr(status_cmd.client, "get", fake_get)

    args = SimpleNamespace(host=None, stats=False, verbose=True, showroots=False)
    status_cmd.cmd_status(args)
    out = capsys.readouterr().out
    assert "stale aggregates" in out
    assert "hash_stats" in out
    assert "directory_index" in out
    assert "last refreshed" in out
    assert "(Queued for refresh after scan completion)" in out


def test_status_no_noise_when_fresh(monkeypatch, capsys):
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
        if path == "/aggregate-status":
            return [
                {"key": "hash_stats", "status": "fresh",
                 "updated_at": "2026-03-09T13:39:55+00:00", "note": None},
                {"key": "directory_index", "status": "fresh",
                 "updated_at": "2026-03-09T13:39:55+00:00", "note": None},
            ]
        raise AssertionError(path)

    monkeypatch.setattr(status_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(status_cmd, "print_config_hint", lambda: None)
    monkeypatch.setattr(status_cmd.client, "get", fake_get)

    args = SimpleNamespace(host=None, stats=False, verbose=False, showroots=False)
    status_cmd.cmd_status(args)
    out = capsys.readouterr().out
    assert "stale" not in out
    assert "building" not in out


def test_status_aggregate_endpoint_failure_silent(monkeypatch, capsys):
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
        if path == "/aggregate-status":
            raise ConnectionError("older server")
        raise AssertionError(path)

    monkeypatch.setattr(status_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(status_cmd, "print_config_hint", lambda: None)
    monkeypatch.setattr(status_cmd.client, "get", fake_get)

    args = SimpleNamespace(host=None, stats=False, verbose=False, showroots=False)
    status_cmd.cmd_status(args)
    out = capsys.readouterr().out
    # Should not crash and should not show staleness info
    assert "stale" not in out
    assert "mac" in out
