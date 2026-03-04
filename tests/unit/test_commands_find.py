from types import SimpleNamespace


def test_find_uses_configured_limit(monkeypatch, capsys):
    from sift.commands import find as find_cmd

    seen = {}

    def fake_get(path, params=None):
        seen["path"] = path
        seen["params"] = params or {}
        return []

    monkeypatch.setattr(find_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(find_cmd, "get_cli_config", lambda: {})
    monkeypatch.setattr(find_cmd, "local_hostname", lambda: "mac")
    monkeypatch.setattr(find_cmd.client, "get", fake_get)

    args = SimpleNamespace(
        path="/",
        host="mac",
        all_hosts=False,
        ext=None,
        category=None,
        hash=None,
        duplicates=False,
        name=None,
        iname=None,
        size=None,
        mtime=None,
        ls=False,
        limit=123,
        lite=False,
        with_other_hosts=False,
    )
    find_cmd.cmd_find(args)
    _ = capsys.readouterr()
    assert seen["path"] == "/files"
    assert seen["params"]["limit"] == 123
    assert seen["params"].get("lite") == "true"


def test_find_can_request_lite_mode(monkeypatch, capsys):
    from sift.commands import find as find_cmd

    seen = {}

    def fake_get(path, params=None):
        seen["params"] = params or {}
        return []

    monkeypatch.setattr(find_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(find_cmd, "get_cli_config", lambda: {})
    monkeypatch.setattr(find_cmd, "local_hostname", lambda: "mac")
    monkeypatch.setattr(find_cmd.client, "get", fake_get)

    args = SimpleNamespace(
        path="/",
        host="mac",
        all_hosts=False,
        ext=None,
        category=None,
        hash=None,
        duplicates=True,
        name=None,
        iname=None,
        size=None,
        mtime=None,
        ls=False,
        limit=50,
        lite=True,
        with_other_hosts=False,
    )
    find_cmd.cmd_find(args)
    _ = capsys.readouterr()
    assert seen["params"].get("has_duplicates") == "true"
    assert seen["params"].get("lite") == "true"


def test_find_with_other_hosts_disables_lite(monkeypatch, capsys):
    from sift.commands import find as find_cmd

    seen = {}

    def fake_get(path, params=None):
        seen["params"] = params or {}
        return []

    monkeypatch.setattr(find_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(find_cmd, "get_cli_config", lambda: {})
    monkeypatch.setattr(find_cmd, "local_hostname", lambda: "mac")
    monkeypatch.setattr(find_cmd.client, "get", fake_get)

    args = SimpleNamespace(
        path="/",
        host="mac",
        all_hosts=False,
        ext=None,
        category=None,
        hash=None,
        duplicates=False,
        name=None,
        iname=None,
        size=None,
        mtime=None,
        ls=False,
        limit=50,
        lite=False,
        with_other_hosts=True,
    )
    find_cmd.cmd_find(args)
    _ = capsys.readouterr()
    assert "lite" not in seen["params"]
