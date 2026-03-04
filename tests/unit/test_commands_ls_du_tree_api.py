from types import SimpleNamespace


def test_ls_uses_tree_endpoints_not_legacy_ls(monkeypatch, capsys):
    from sift.commands import ls as ls_cmd

    calls: list[str] = []

    def fake_get(path, params=None):
        calls.append(path)
        if path == "/tree/children":
            return {
                "items": [
                    {
                        "segment": "docs",
                        "entry_type": "dir",
                        "segment_display": "docs",
                        "file_count": None,
                        "total_bytes": None,
                    },
                    {
                        "segment": "a.txt",
                        "entry_type": "file",
                        "segment_display": "a.txt",
                        "filename": "a.txt",
                        "size_bytes": 10,
                        "total_bytes": 10,
                        "hash": "a" * 64,
                        "mtime": 1,
                        "path_display": "/a.txt",
                    },
                ],
                "has_more": False,
                "next_cursor": None,
            }
        if path == "/tree/dup-metrics":
            return {
                "metrics": {
                    "docs": {
                        "dup_count": 2,
                        "dup_hash_count": 1,
                        "file_count": 3,
                        "total_bytes": 30,
                    },
                    "a.txt": {
                        "dup_count": 0,
                        "dup_hash_count": 0,
                        "file_count": 1,
                        "total_bytes": 10,
                    },
                }
            }
        raise AssertionError(f"unexpected endpoint {path}")

    monkeypatch.setattr(ls_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(ls_cmd, "get_cli_config", lambda: {})
    monkeypatch.setattr(ls_cmd, "local_hostname", lambda: "mac")
    monkeypatch.setattr(ls_cmd.client, "get", fake_get)

    args = SimpleNamespace(
        path="/",
        host="mac",
        all_hosts=False,
        full_hash=False,
        long=False,
        human=False,
        sort_size=False,
        sort_time=False,
        reverse=False,
        one_per_line=False,
        recursive=False,
        duplicates=False,
    )
    ls_cmd.cmd_ls(args)
    out = capsys.readouterr().out
    assert "/files/ls" not in calls
    assert "/tree/children" in calls
    assert "/tree/dup-metrics" in calls
    assert "docs/" in out
    assert "a.txt" in out


def test_du_uses_tree_endpoints_not_legacy_ls(monkeypatch, capsys):
    from sift.commands import du as du_cmd

    calls: list[str] = []

    def fake_get(path, params=None):
        calls.append(path)
        if path == "/tree/children":
            return {
                "items": [
                    {"segment": "docs", "entry_type": "dir", "segment_display": "docs"},
                    {
                        "segment": "a.txt",
                        "entry_type": "file",
                        "segment_display": "a.txt",
                        "total_bytes": 10,
                    },
                ],
                "has_more": False,
                "next_cursor": None,
            }
        if path == "/tree/dup-metrics":
            return {
                "metrics": {
                    "docs": {"dup_count": 1, "dup_hash_count": 1, "total_bytes": 40},
                    "a.txt": {"dup_count": 0, "dup_hash_count": 0, "total_bytes": 10},
                }
            }
        raise AssertionError(f"unexpected endpoint {path}")

    monkeypatch.setattr(du_cmd, "print_server_info", lambda: None)
    monkeypatch.setattr(du_cmd, "get_cli_config", lambda: {})
    monkeypatch.setattr(du_cmd, "local_hostname", lambda: "mac")
    monkeypatch.setattr(du_cmd.client, "get", fake_get)

    args = SimpleNamespace(
        path="/",
        host="mac",
        all_hosts=False,
        human=False,
        summarize=False,
        depth=1,
        sort="size",
        duplicates_only=False,
        by_category=False,
    )
    du_cmd.cmd_du(args)
    out = capsys.readouterr().out
    assert "/files/ls" not in calls
    assert "/tree/children" in calls
    assert "/tree/dup-metrics" in calls
    assert "total" in out
