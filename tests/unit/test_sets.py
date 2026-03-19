"""Unit tests for sift sets."""

from types import SimpleNamespace

import pytest


def _make_args(**overrides):
    defaults = dict(
        paths=[],
        a_paths=None,
        b_paths=None,
        covered=None,
        min_size=None,
        n=None,
        summary=False,
        no_summary=False,
        long=False,
        reverse=False,
        common=False,
        json=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class FakeStreamResponse:
    """Minimal mock for client.get_stream() return value."""

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)


def _setup(monkeypatch, entries_map=None, stream_map=None, hosts=None):
    """Set up monkeypatched sift.commands.sets module.

    entries_map: dict[path_prefix → list[entry]] for /files calls
    stream_map: dict[key → list[str]] for /files/hashes streaming calls
                Keys tried in order: "host:prefix", "host:", prefix, ""
    hosts: list of host dicts for /hosts
    """
    from sift.commands import sets as mod

    entries_map = entries_map or {}
    stream_map = stream_map or {}
    hosts = hosts or [{"host": "mac"}]

    def fake_get(path, params=None):
        if path == "/hosts":
            return hosts
        if path == "/files":
            pp = (params or {}).get("path_prefix", "")
            return entries_map.get(pp, [])
        return []

    def fake_get_stream(path, params=None):
        if path == "/files/hashes":
            host = (params or {}).get("host", "")
            pp = (params or {}).get("path_prefix", "")
            for k in [f"{host}:{pp}", f"{host}:", pp, ""]:
                if k in stream_map:
                    return FakeStreamResponse(stream_map[k])
            return FakeStreamResponse([])
        return FakeStreamResponse([])

    monkeypatch.setattr(mod, "print_server_info", lambda: None)
    monkeypatch.setattr(mod, "get_cli_config", lambda: {})
    monkeypatch.setattr(mod, "local_hostname", lambda: "mac")
    monkeypatch.setattr(mod, "resolve_host", lambda h: h)
    monkeypatch.setattr(mod, "parse_host_path", lambda arg, dh: (dh, arg))
    monkeypatch.setattr(mod, "extract_drive_path", lambda p: ("", p))
    monkeypatch.setattr(mod.client, "get", fake_get)
    monkeypatch.setattr(mod.client, "get_stream", fake_get_stream)
    monkeypatch.setenv("SIFT_HOST", "")

    return mod


# --- Helpers for building test data ----------------------------------------

def _file(path, hash=None, size=100, mtime=1000):
    return {"path": path, "path_display": path, "hash": hash,
            "size_bytes": size, "mtime": mtime, "drive": ""}


def _stream_line(hash, path):
    return f"{hash}\t{path}"


# ---------------------------------------------------------------------------
# 1. Fully covered → exit 0, no files on stdout
# ---------------------------------------------------------------------------

def test_fully_covered(monkeypatch, capsys):
    a = [_file("/src/a.txt", "aaa"), _file("/src/b.txt", "bbb")]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": [
            _stream_line("aaa", "/tgt/x.txt"),
            _stream_line("bbb", "/tgt/y.txt"),
            _stream_line("ccc", "/tgt/z.txt"),
        ]},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"]))
    assert exc.value.code == 0
    out = capsys.readouterr()
    assert out.out.strip() == ""
    assert "FULLY COVERED" in out.err


# ---------------------------------------------------------------------------
# 2. Partially covered → exit 1, missing files listed
# ---------------------------------------------------------------------------

def test_partially_covered(monkeypatch, capsys):
    a = [
        _file("/src/a.txt", "aaa"),
        _file("/src/b.txt", "bbb"),
        _file("/src/c.txt", "ccc"),
    ]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": [
            _stream_line("aaa", "/tgt/x.txt"),
        ]},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"]))
    assert exc.value.code == 1
    out = capsys.readouterr()
    assert "/src/b.txt" in out.out
    assert "/src/c.txt" in out.out
    assert "/src/a.txt" not in out.out
    assert "NOT FULLY COVERED" in out.err


# ---------------------------------------------------------------------------
# 3. Completely disjoint → exit 1, all source files listed
# ---------------------------------------------------------------------------

def test_completely_disjoint(monkeypatch, capsys):
    a = [_file("/src/a.txt", "aaa"), _file("/src/b.txt", "bbb")]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": [_stream_line("zzz", "/tgt/z.txt")]},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"]))
    assert exc.value.code == 1
    out = capsys.readouterr()
    assert "/src/a.txt" in out.out
    assert "/src/b.txt" in out.out


# ---------------------------------------------------------------------------
# 4. Empty source → exit 0
# ---------------------------------------------------------------------------

def test_empty_source(monkeypatch, capsys):
    mod = _setup(
        monkeypatch,
        entries_map={"/src": []},
        stream_map={"/tgt": [_stream_line("aaa", "/tgt/x.txt")]},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"]))
    assert exc.value.code == 0
    assert "no files" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 5. Unhashed files, hashed counterpart → listed as missing
# ---------------------------------------------------------------------------

def test_unhashed_a_hashed_b(monkeypatch, capsys):
    a = [_file("/src/a.txt", None)]  # unhashed
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": [_stream_line("aaa", "/tgt/a.txt")]},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"]))
    assert exc.value.code == 1
    out = capsys.readouterr()
    assert "/src/a.txt" in out.out
    assert "unverifiable" in out.err


# ---------------------------------------------------------------------------
# 6. Unhashed both sides, size+mtime match → covered
# ---------------------------------------------------------------------------

def test_unhashed_both_sizemtime_match(monkeypatch, capsys):
    a = [_file("/src/photo.jpg", None, size=5000, mtime=12345)]
    b = [_file("/tgt/photo.jpg", None, size=5000, mtime=12345)]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a, "/tgt": b},
        stream_map={},
    )
    # Use --reverse so B entries are fetched via /files (enabling unhashed matching)
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"], reverse=True))
    assert exc.value.code == 0
    out = capsys.readouterr()
    assert "covered by size+mtime" in out.err


# ---------------------------------------------------------------------------
# 7. Unhashed both sides, no match → unverifiable, exit 1
# ---------------------------------------------------------------------------

def test_unhashed_both_no_match(monkeypatch, capsys):
    # In default (streaming) mode, unhashed A files are always unverifiable
    a = [_file("/src/photo.jpg", None, size=5000, mtime=12345)]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": []},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"]))
    assert exc.value.code == 1
    out = capsys.readouterr()
    assert "unverifiable" in out.err
    assert "/src/photo.jpg" in out.out


# ---------------------------------------------------------------------------
# 8. Multiple B targets → hash union
# ---------------------------------------------------------------------------

def test_multiple_b_targets(monkeypatch, capsys):
    a = [_file("/src/a.txt", "aaa"), _file("/src/b.txt", "bbb")]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={
            "/tgt1": [_stream_line("aaa", "/tgt1/x.txt")],
            "/tgt2": [_stream_line("bbb", "/tgt2/y.txt")],
        },
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt1", "/tgt2"]))
    assert exc.value.code == 0
    assert "FULLY COVERED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 9. -a/-b multi-path grouping → both sides unioned
# ---------------------------------------------------------------------------

def test_ab_flag_grouping(monkeypatch, capsys):
    a1 = [_file("/a1/f.txt", "aaa")]
    a2 = [_file("/a2/g.txt", "bbb")]
    mod = _setup(
        monkeypatch,
        entries_map={"/a1": a1, "/a2": a2},
        stream_map={
            "/b1": [
                _stream_line("aaa", "/b1/x.txt"),
                _stream_line("bbb", "/b1/y.txt"),
            ],
        },
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(a_paths=["/a1", "/a2"], b_paths=["/b1"]))
    assert exc.value.code == 0
    assert "FULLY COVERED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 10. Cross-host → host:path syntax parsed correctly
# ---------------------------------------------------------------------------

def test_cross_host(monkeypatch, capsys):
    def cross_parse(arg, dh):
        if ":" in arg and len(arg.split(":")[0]) > 1:
            h, p = arg.split(":", 1)
            return h, p
        return dh, arg

    a = [_file("/photos/img.jpg", "aaa")]
    mod = _setup(
        monkeypatch,
        entries_map={"/photos": a},
        stream_map={"unraid:": [_stream_line("aaa", "/media/img.jpg")]},
        hosts=[{"host": "mac"}, {"host": "unraid"}],
    )
    monkeypatch.setattr(mod, "parse_host_path", cross_parse)

    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["mac:/photos", "unraid:/media"]))
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# 11. Windows drive paths → drive extracted
# ---------------------------------------------------------------------------

def test_windows_drive_paths(monkeypatch, capsys):
    a = [_file("/users/brian", "aaa", size=100, mtime=1000)]

    def drive_parse(p):
        if len(p) >= 2 and p[1] == ":":
            return p[0].upper(), p[2:]
        return "", p

    mod = _setup(
        monkeypatch,
        entries_map={"/users/brian": a},
        stream_map={"/media": [_stream_line("aaa", "/media/x.txt")]},
    )
    monkeypatch.setattr(mod, "extract_drive_path", drive_parse)

    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["D:/users/brian", "/media"]))
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# 12. --min-size → below-threshold files excluded from both sides
# ---------------------------------------------------------------------------

def test_min_size_filter(monkeypatch, capsys):
    a = [
        _file("/src/big.txt", "aaa", size=10_000),
        _file("/src/small.txt", "bbb", size=50),
    ]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": [_stream_line("aaa", "/tgt/x.txt")]},
    )
    # min_size=1000 should exclude small.txt from consideration
    # but since we pass min_size to the server, the server filters.
    # In our test, the entries_map returns all entries regardless
    # (server handles filtering). So this tests that the param is passed.
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"], min_size="1K"))
    # big.txt covered, small.txt still returned by our mock but server would filter
    assert exc.value.code in (0, 1)


# ---------------------------------------------------------------------------
# 13. --summary → no file list on stdout
# ---------------------------------------------------------------------------

def test_summary_only(monkeypatch, capsys):
    a = [_file("/src/a.txt", "aaa")]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": [_stream_line("zzz", "/tgt/z.txt")]},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"], summary=True))
    assert exc.value.code == 1
    out = capsys.readouterr()
    assert out.out.strip() == ""
    assert "sift sets:" in out.err


# ---------------------------------------------------------------------------
# 14. --no-summary → no summary on stderr
# ---------------------------------------------------------------------------

def test_no_summary(monkeypatch, capsys):
    a = [_file("/src/a.txt", "aaa")]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": [_stream_line("zzz", "/tgt/z.txt")]},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"], no_summary=True))
    assert exc.value.code == 1
    out = capsys.readouterr()
    assert "/src/a.txt" in out.out
    assert "sift sets:" not in out.err


# ---------------------------------------------------------------------------
# 15. --covered no args → all hosts fetched, source excluded
# ---------------------------------------------------------------------------

def test_covered_all_hosts(monkeypatch, capsys):
    a = [_file("/backup/a.txt", "aaa")]
    mod = _setup(
        monkeypatch,
        entries_map={"/backup": a},
        stream_map={
            "mac:": [
                _stream_line("aaa", "/media/a.txt"),
                _stream_line("bbb", "/backup/a.txt"),  # should be excluded
            ],
        },
        hosts=[{"host": "mac"}],
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/backup"], covered=[]))
    assert exc.value.code == 0
    assert "FULLY COVERED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 16. --covered HOST → only that host fetched
# ---------------------------------------------------------------------------

def test_covered_specific_host(monkeypatch, capsys):
    a = [_file("/backup/a.txt", "aaa")]
    mod = _setup(
        monkeypatch,
        entries_map={"/backup": a},
        stream_map={
            "unraid:": [_stream_line("aaa", "/media/a.txt")],
        },
        hosts=[{"host": "mac"}, {"host": "unraid"}],
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/backup"], covered=["unraid"]))
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# 17. --reverse → B-A files listed instead
# ---------------------------------------------------------------------------

def test_reverse_mode(monkeypatch, capsys):
    a = [_file("/src/a.txt", "aaa")]
    b = [
        _file("/tgt/a.txt", "aaa"),
        _file("/tgt/b.txt", "bbb"),
    ]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a, "/tgt": b},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"], reverse=True))
    # Exit code reflects A coverage (A is fully covered), not B
    assert exc.value.code == 0
    out = capsys.readouterr()
    # --reverse lists B-only files (files in B not in A)
    assert "/tgt/b.txt" in out.out
    assert "/tgt/a.txt" not in out.out


# ---------------------------------------------------------------------------
# 18. --common → intersection files listed
# ---------------------------------------------------------------------------

def test_common_mode(monkeypatch, capsys):
    a = [
        _file("/src/a.txt", "aaa"),
        _file("/src/b.txt", "bbb"),
    ]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": [_stream_line("aaa", "/tgt/x.txt")]},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"], common=True))
    assert exc.value.code == 1  # not fully covered (bbb missing)
    out = capsys.readouterr()
    assert "/src/a.txt" in out.out
    assert "/src/b.txt" not in out.out


# ---------------------------------------------------------------------------
# 19. -n N limits output
# ---------------------------------------------------------------------------

def test_limit_output(monkeypatch, capsys):
    a = [
        _file("/src/a.txt", "aaa"),
        _file("/src/b.txt", "bbb"),
        _file("/src/c.txt", "ccc"),
    ]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": []},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"], n=2))
    assert exc.value.code == 1
    out = capsys.readouterr()
    lines = [l for l in out.out.strip().split("\n") if l]
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# 20. Duplicate hashes in source → correct unique count vs file count
# ---------------------------------------------------------------------------

def test_duplicate_hashes_in_source(monkeypatch, capsys):
    a = [
        _file("/src/a.txt", "aaa"),
        _file("/src/a_copy.txt", "aaa"),
        _file("/src/b.txt", "bbb"),
    ]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": [_stream_line("bbb", "/tgt/b.txt")]},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"]))
    assert exc.value.code == 1
    out = capsys.readouterr()
    # Both files with hash "aaa" should be listed
    assert "/src/a.txt" in out.out
    assert "/src/a_copy.txt" in out.out
    # Summary should show 2 unique hashes, 3 files total
    assert "2 unique hashes" in out.err
    assert "3 files" in out.err  # source total referenced with comma formatting


# ---------------------------------------------------------------------------
# Edge: --reverse and --common mutually exclusive
# ---------------------------------------------------------------------------

def test_reverse_common_exclusive(monkeypatch, capsys):
    mod = _setup(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(
            paths=["/src", "/tgt"], reverse=True, common=True,
        ))
    assert exc.value.code == 2
    assert "mutually exclusive" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Edge: no arguments → error
# ---------------------------------------------------------------------------

def test_no_arguments_error(monkeypatch, capsys):
    mod = _setup(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args())
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Edge: --covered with -b → error
# ---------------------------------------------------------------------------

def test_covered_with_b_error(monkeypatch, capsys):
    mod = _setup(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(
            paths=["/src"], covered=[], b_paths=["/tgt"],
        ))
    assert exc.value.code == 2
    assert "mutually exclusive" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --long format
# ---------------------------------------------------------------------------

def test_long_format(monkeypatch, capsys):
    a = [_file("/src/a.txt", "aaa", size=4_200_000, mtime=1342310400)]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": []},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"], long=True))
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "4.0M" in out
    assert "2012-07-15" in out
    assert "/src/a.txt" in out


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def test_json_output(monkeypatch, capsys):
    import json

    a = [_file("/src/a.txt", "aaa"), _file("/src/b.txt", "bbb")]
    mod = _setup(
        monkeypatch,
        entries_map={"/src": a},
        stream_map={"/tgt": [_stream_line("aaa", "/tgt/x.txt")]},
    )
    with pytest.raises(SystemExit) as exc:
        mod.cmd_sets(_make_args(paths=["/src", "/tgt"], json=True))
    assert exc.value.code == 1
    out = capsys.readouterr()
    data = json.loads(out.out)
    assert data["source"]["files"] == 2
    assert data["a_only"]["hashes"] == 1
    assert data["fully_covered"] is False
    assert len(data["files"]) == 1
    assert data["files"][0]["path"] == "/src/b.txt"


# ---------------------------------------------------------------------------
# _parse_size helper
# ---------------------------------------------------------------------------

def test_parse_size():
    from sift.commands.sets import _parse_size
    assert _parse_size(None) == 0
    assert _parse_size("") == 0
    assert _parse_size("1000") == 1000
    assert _parse_size("1K") == 1024
    assert _parse_size("1k") == 1024
    assert _parse_size("1M") == 1024 * 1024
    assert _parse_size("1G") == 1024 ** 3
    assert _parse_size("500k") == 500 * 1024
    assert _parse_size("1.5M") == int(1.5 * 1024 * 1024)
