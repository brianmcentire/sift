"""Unit tests for sift diff and parse_host_path."""

from types import SimpleNamespace
import pytest


# ── _split_drive tests ─────────────────────────────────────────────────────


def test_extract_drive_path_windows():
    from sift.commands import extract_drive_path
    drive, path = extract_drive_path("d:/d/wedding")
    assert drive == "D"
    assert path == "/d/wedding"


def test_extract_drive_path_posix():
    from sift.commands import extract_drive_path
    drive, path = extract_drive_path("/mnt/user/photos")
    assert drive == ""
    assert path == "/mnt/user/photos"


def test_extract_drive_path_uppercase():
    from sift.commands import extract_drive_path
    drive, path = extract_drive_path("C:/Users/Brian")
    assert drive == "C"
    assert path == "/users/brian"


def test_extract_drive_path_backslashes():
    from sift.commands import extract_drive_path
    drive, path = extract_drive_path("D:\\Photos\\2024")
    assert drive == "D"
    assert path == "/photos/2024"


# ── parse_host_path tests ──────────────────────────────────────────────────


def test_parse_host_path_local_absolute(monkeypatch):
    from sift.commands import parse_host_path

    monkeypatch.setattr("sift.commands.resolve_host", lambda h: h)
    monkeypatch.setattr("sift.commands.normalize_query_path", lambda p: p.lower())

    host, path = parse_host_path("/mnt/user/media", "mac")
    assert host == "mac"
    assert path == "/mnt/user/media"


def test_parse_host_path_relative(monkeypatch):
    from sift.commands import parse_host_path

    monkeypatch.setattr("sift.commands.resolve_host", lambda h: h)
    monkeypatch.setattr("sift.commands.normalize_query_path", lambda p: "/resolved" + p)

    host, path = parse_host_path("./relative", "mac")
    assert host == "mac"
    assert path.endswith("relative") or "/resolved" in path


def test_parse_host_path_host_colon_path(monkeypatch):
    from sift.commands import parse_host_path

    monkeypatch.setattr("sift.commands.resolve_host", lambda h: h)
    monkeypatch.setattr("sift.commands.normalize_query_path", lambda p: p.lower())

    host, path = parse_host_path("brian-pc:/users/brian", "mac")
    assert host == "brian-pc"
    assert path == "/users/brian"


def test_parse_host_path_host_with_drive(monkeypatch):
    from sift.commands import parse_host_path

    monkeypatch.setattr("sift.commands.resolve_host", lambda h: h)

    host, path = parse_host_path("brian-pc:C:/Users/brian", "mac")
    assert host == "brian-pc"
    assert "c:/users/brian" == path


def test_parse_host_path_windows_drive_local(monkeypatch):
    from sift.commands import parse_host_path

    monkeypatch.setattr("sift.commands.resolve_host", lambda h: h)
    monkeypatch.setattr("sift.commands.normalize_query_path", lambda p: p.lower())

    host, path = parse_host_path("C:/Users/brian", "mac")
    assert host == "mac"


def test_parse_host_path_localhost(monkeypatch):
    from sift.commands import parse_host_path

    # resolve_host should convert 'localhost' to local hostname
    monkeypatch.setattr("sift.commands.resolve_host", lambda h: "mac" if h.lower() == "localhost" else h)
    monkeypatch.setattr("sift.commands.normalize_query_path", lambda p: p.lower())

    host, path = parse_host_path("localhost:/mnt/data", "mac")
    assert host == "mac"
    assert path == "/mnt/data"


def test_parse_host_path_backslashes(monkeypatch):
    from sift.commands import parse_host_path

    monkeypatch.setattr("sift.commands.resolve_host", lambda h: h)

    host, path = parse_host_path("Photoshop-PC:C:\\temp\\files", "mac")
    assert host == "Photoshop-PC"
    assert "c:/temp/files" == path


# ── cmd_diff tests ─────────────────────────────────────────────────────────


def _make_diff_args(**overrides):
    defaults = dict(dir1="/dir1", dir2="/dir2", recursive=False)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _setup_diff(monkeypatch, entries1=None, entries2=None):
    from sift.commands import diff as diff_mod

    if entries1 is None:
        entries1 = []
    if entries2 is None:
        entries2 = []

    call_count = {"n": 0}

    def fake_get(path, params=None):
        call_count["n"] += 1
        p = (params or {}).get("path", (params or {}).get("path_prefix", ""))
        if "/dir1" in p:
            return entries1
        return entries2

    monkeypatch.setattr(diff_mod, "print_server_info", lambda: None)
    monkeypatch.setattr(diff_mod, "get_cli_config", lambda: {})
    monkeypatch.setattr(diff_mod, "local_hostname", lambda: "mac")
    monkeypatch.setattr(diff_mod, "resolve_host", lambda h: h)
    monkeypatch.setattr(diff_mod, "parse_host_path", lambda arg, dh: (dh, arg.lower()))
    monkeypatch.setattr(diff_mod.client, "get", fake_get)
    monkeypatch.setenv("SIFT_HOST", "")

    return diff_mod


def test_only_in_dir1(monkeypatch, capsys):
    entries1 = [
        {"path": "/dir1/file1.txt", "path_display": "/dir1/file1.txt", "hash": "abc123", "drive": ""},
    ]
    diff_mod = _setup_diff(monkeypatch, entries1, [])
    with pytest.raises(SystemExit) as exc_info:
        diff_mod.cmd_diff(_make_diff_args())
    assert exc_info.value.code == 1
    out = capsys.readouterr()
    assert "Only in" in out.out
    assert "file1.txt" in out.out


def test_only_in_dir2(monkeypatch, capsys):
    entries2 = [
        {"path": "/dir2/file2.txt", "path_display": "/dir2/file2.txt", "hash": "def456", "drive": ""},
    ]
    diff_mod = _setup_diff(monkeypatch, [], entries2)
    with pytest.raises(SystemExit) as exc_info:
        diff_mod.cmd_diff(_make_diff_args())
    assert exc_info.value.code == 1
    out = capsys.readouterr()
    assert "Only in" in out.out
    assert "file2.txt" in out.out


def test_files_differ(monkeypatch, capsys):
    entries1 = [
        {"path": "/dir1/photo.jpg", "path_display": "/dir1/photo.jpg", "hash": "aaa111", "drive": ""},
    ]
    entries2 = [
        {"path": "/dir2/photo.jpg", "path_display": "/dir2/photo.jpg", "hash": "bbb222", "drive": ""},
    ]
    diff_mod = _setup_diff(monkeypatch, entries1, entries2)
    with pytest.raises(SystemExit) as exc_info:
        diff_mod.cmd_diff(_make_diff_args())
    assert exc_info.value.code == 1
    out = capsys.readouterr()
    assert "differ" in out.out


def test_identical_dirs_exit_0(monkeypatch, capsys):
    entries = [
        {"path": "/dir1/file.txt", "path_display": "/dir1/file.txt", "hash": "same123", "drive": ""},
    ]
    entries2 = [
        {"path": "/dir2/file.txt", "path_display": "/dir2/file.txt", "hash": "same123", "drive": ""},
    ]
    diff_mod = _setup_diff(monkeypatch, entries, entries2)
    with pytest.raises(SystemExit) as exc_info:
        diff_mod.cmd_diff(_make_diff_args())
    assert exc_info.value.code == 0
    out = capsys.readouterr()
    assert out.out.strip() == ""


def test_both_no_hash(monkeypatch, capsys):
    entries1 = [
        {"path": "/dir1/raw.cr2", "path_display": "/dir1/raw.cr2", "hash": None, "drive": ""},
    ]
    entries2 = [
        {"path": "/dir2/raw.cr2", "path_display": "/dir2/raw.cr2", "hash": None, "drive": ""},
    ]
    diff_mod = _setup_diff(monkeypatch, entries1, entries2)
    with pytest.raises(SystemExit) as exc_info:
        diff_mod.cmd_diff(_make_diff_args())
    assert exc_info.value.code == 1
    out = capsys.readouterr()
    assert "no-hash" in out.out


def test_one_hashed_one_not(monkeypatch, capsys):
    entries1 = [
        {"path": "/dir1/file.txt", "path_display": "/dir1/file.txt", "hash": "abc123", "drive": ""},
    ]
    entries2 = [
        {"path": "/dir2/file.txt", "path_display": "/dir2/file.txt", "hash": None, "drive": ""},
    ]
    diff_mod = _setup_diff(monkeypatch, entries1, entries2)
    with pytest.raises(SystemExit) as exc_info:
        diff_mod.cmd_diff(_make_diff_args())
    assert exc_info.value.code == 1
    out = capsys.readouterr()
    assert "differ" in out.out


def test_cross_host_display(monkeypatch, capsys):
    from sift.commands import diff as diff_mod

    entries1 = [
        {"path": "/mnt/photos/cat.jpg", "path_display": "/mnt/photos/cat.jpg", "hash": "aaa", "drive": ""},
    ]
    entries2 = [
        {"path": "/users/brian/photos/cat.jpg", "path_display": "/users/brian/photos/cat.jpg", "hash": "bbb", "drive": ""},
    ]

    call_count = {"n": 0}

    def fake_get(path, params=None):
        call_count["n"] += 1
        p = (params or {}).get("path", (params or {}).get("path_prefix", ""))
        if "mnt" in p:
            return entries1
        return entries2

    monkeypatch.setattr(diff_mod, "print_server_info", lambda: None)
    monkeypatch.setattr(diff_mod, "get_cli_config", lambda: {})
    monkeypatch.setattr(diff_mod, "local_hostname", lambda: "mac")
    monkeypatch.setattr(diff_mod, "resolve_host", lambda h: h)
    monkeypatch.setattr(diff_mod.client, "get", fake_get)
    monkeypatch.setenv("SIFT_HOST", "")

    # Override parse_host_path to return different hosts
    def fake_parse(arg, dh):
        if "unraid" in arg:
            return ("unraid", "/mnt/photos")
        return ("brian-pc", "/users/brian/photos")

    monkeypatch.setattr(diff_mod, "parse_host_path", fake_parse)

    with pytest.raises(SystemExit) as exc_info:
        diff_mod.cmd_diff(_make_diff_args(dir1="unraid:/mnt/photos", dir2="brian-pc:/users/brian/photos"))
    assert exc_info.value.code == 1
    out = capsys.readouterr()
    assert "unraid:" in out.out or "brian-pc:" in out.out


def test_windows_drive_passed_to_api(monkeypatch, capsys):
    """drive= must be sent as a separate param, not embedded in path."""
    from sift.commands import diff as diff_mod

    seen = {}

    def fake_get(path, params=None):
        seen.setdefault("calls", []).append(dict(params or {}))
        return []

    monkeypatch.setattr(diff_mod, "print_server_info", lambda: None)
    monkeypatch.setattr(diff_mod, "get_cli_config", lambda: {})
    monkeypatch.setattr(diff_mod, "local_hostname", lambda: "mac")
    monkeypatch.setattr(diff_mod, "resolve_host", lambda h: h)
    monkeypatch.setattr(diff_mod.client, "get", fake_get)
    monkeypatch.setenv("SIFT_HOST", "")

    # parse_host_path returns drive-prefixed path for Windows host
    monkeypatch.setattr(
        diff_mod, "parse_host_path",
        lambda arg, dh: ("win-pc", "d:/photos") if "win" in arg else ("mac", "/backup/photos")
    )

    with pytest.raises(SystemExit):
        diff_mod.cmd_diff(_make_diff_args(dir1="win-pc:D:/photos", dir2="/backup/photos"))

    win_call = next(c for c in seen["calls"] if c.get("host") == "win-pc")
    assert win_call.get("drive") == "D"
    assert win_call.get("path") == "/photos"  # drive stripped from path


def test_dir_entries_included_in_comparison(monkeypatch, capsys):
    """Depth-1 dir entries (no path field) should appear in comparison."""
    from sift.commands import diff as diff_mod

    # dir1 has a subdir that dir2 lacks
    entries1 = [
        {"entry_type": "dir", "segment": "vacation", "segment_display": "Vacation",
         "path": None, "hash": None},
    ]
    entries2 = []

    def fake_get(path, params=None):
        p = (params or {}).get("path", "")
        if "/dir1" in p:
            return entries1
        return entries2

    monkeypatch.setattr(diff_mod, "print_server_info", lambda: None)
    monkeypatch.setattr(diff_mod, "get_cli_config", lambda: {})
    monkeypatch.setattr(diff_mod, "local_hostname", lambda: "mac")
    monkeypatch.setattr(diff_mod, "resolve_host", lambda h: h)
    monkeypatch.setattr(diff_mod, "parse_host_path", lambda arg, dh: (dh, arg.lower()))
    monkeypatch.setattr(diff_mod.client, "get", fake_get)
    monkeypatch.setenv("SIFT_HOST", "")

    with pytest.raises(SystemExit) as exc_info:
        diff_mod.cmd_diff(_make_diff_args())
    assert exc_info.value.code == 1
    out = capsys.readouterr()
    assert "Only in" in out.out
    assert "vacation" in out.out
