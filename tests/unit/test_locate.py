"""Unit tests for sift locate."""

from types import SimpleNamespace


def _make_args(**overrides):
    defaults = dict(
        pattern="*.mp4",
        case_insensitive=False,
        host=None,
        all_hosts=False,
        limit=1000,
        all_results=False,
        long=False,
        count=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _setup(monkeypatch, entries=None):
    from sift.commands import locate as loc

    if entries is None:
        entries = []

    seen = {}

    def fake_get(path, params=None):
        seen["path"] = path
        seen["params"] = params or {}
        return entries

    monkeypatch.setattr(loc, "print_server_info", lambda: None)
    monkeypatch.setattr(loc, "get_cli_config", lambda: {})
    monkeypatch.setattr(loc, "local_hostname", lambda: "mac")
    monkeypatch.setattr(loc, "resolve_host", lambda h: h)
    monkeypatch.setattr(loc.client, "get", fake_get)
    monkeypatch.setenv("SIFT_HOST", "")

    return loc, seen


def test_default_search(monkeypatch, capsys):
    entries = [
        {"host": "mac", "path": "/mnt/user/media/video1.mp4",
         "path_display": "/mnt/user/media/video1.mp4", "drive": ""},
        {"host": "mac", "path": "/mnt/user/media/movies/film.mp4",
         "path_display": "/mnt/user/media/movies/film.mp4", "drive": ""},
    ]
    loc, seen = _setup(monkeypatch, entries)
    loc.cmd_locate(_make_args())
    out = capsys.readouterr()
    assert "/mnt/user/media/video1.mp4" in out.out
    assert "/mnt/user/media/movies/film.mp4" in out.out
    assert seen["params"]["name"] == "*.mp4"
    assert "host" in seen["params"]


def test_case_insensitive_uses_iname(monkeypatch, capsys):
    loc, seen = _setup(monkeypatch)
    loc.cmd_locate(_make_args(case_insensitive=True))
    capsys.readouterr()
    assert "iname" in seen["params"]
    assert "name" not in seen["params"]


def test_all_hosts_prefixes_output(monkeypatch, capsys):
    entries = [
        {"host": "unraid", "path": "/mnt/user/media/video1.mp4",
         "path_display": "/mnt/user/media/video1.mp4", "drive": ""},
        {"host": "brian-pc", "path": "/users/brian/videos/clip.mp4",
         "path_display": "/users/brian/videos/clip.mp4", "drive": "C"},
    ]
    loc, seen = _setup(monkeypatch, entries)
    loc.cmd_locate(_make_args(all_hosts=True))
    out = capsys.readouterr()
    assert "unraid:/mnt/user/media/video1.mp4" in out.out
    assert "brian-pc:C:/users/brian/videos/clip.mp4" in out.out
    assert "host" not in seen["params"]


def test_limit_zero_maps_to_million(monkeypatch, capsys):
    loc, seen = _setup(monkeypatch)
    loc.cmd_locate(_make_args(limit=0))
    capsys.readouterr()
    assert seen["params"]["limit"] == 1_000_000


def test_all_results_shorthand(monkeypatch, capsys):
    loc, seen = _setup(monkeypatch)
    loc.cmd_locate(_make_args(all_results=True))
    capsys.readouterr()
    assert seen["params"]["limit"] == 1_000_000


def test_count_only(monkeypatch, capsys):
    entries = [{"host": "mac", "path": "/a.mp4", "path_display": "/a.mp4", "drive": ""}] * 5
    loc, _ = _setup(monkeypatch, entries)
    loc.cmd_locate(_make_args(count=True))
    out = capsys.readouterr()
    assert out.out.strip() == "5"


def test_long_format(monkeypatch, capsys):
    entries = [
        {"host": "mac", "path": "/mnt/user/media/video1.mp4",
         "path_display": "/mnt/user/media/video1.mp4", "drive": "",
         "size_bytes": 1288490188, "mtime": 1710460800},
    ]
    loc, _ = _setup(monkeypatch, entries)
    loc.cmd_locate(_make_args(long=True))
    out = capsys.readouterr()
    assert "2024-03-15" in out.out
    assert "/mnt/user/media/video1.mp4" in out.out
    # Size should be formatted
    assert "G" in out.out or "M" in out.out


def test_truncation_footer(monkeypatch, capsys):
    entries = [
        {"host": "mac", "path": f"/file{i}.mp4", "path_display": f"/file{i}.mp4", "drive": ""}
        for i in range(100)
    ]
    loc, _ = _setup(monkeypatch, entries)
    loc.cmd_locate(_make_args(limit=100))
    out = capsys.readouterr()
    assert "showing 100 results" in out.err
    assert "--limit 0" in out.err
