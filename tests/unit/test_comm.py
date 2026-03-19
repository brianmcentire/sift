"""Unit tests for sift comm."""

from types import SimpleNamespace
from unittest.mock import patch
import pytest


def _make_comm_args(**overrides):
    defaults = dict(
        dir1="/dir1", dir2="/dir2", recursive=False, depth=None,
        hashes=False, suppress_1=False, suppress_2=False, suppress_3=False,
        yes=False, human=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _setup_comm(monkeypatch, entries1=None, entries2=None):
    from sift.commands import comm as comm_mod

    if entries1 is None:
        entries1 = []
    if entries2 is None:
        entries2 = []

    def fake_get(path, params=None):
        p = (params or {}).get("path", (params or {}).get("path_prefix", ""))
        if "/dir1" in p:
            return entries1
        return entries2

    monkeypatch.setattr(comm_mod, "print_server_info", lambda: None)
    monkeypatch.setattr(comm_mod, "get_cli_config", lambda: {})
    monkeypatch.setattr(comm_mod, "local_hostname", lambda: "mac")
    monkeypatch.setattr(comm_mod, "resolve_host", lambda h: h)
    monkeypatch.setattr(comm_mod, "parse_host_path", lambda arg, dh: (dh, arg.lower()))
    monkeypatch.setattr(comm_mod.client, "get", fake_get)
    monkeypatch.setenv("SIFT_HOST", "")

    return comm_mod


def test_three_column_output(monkeypatch, capsys):
    entries1 = [
        {"path": "/dir1/only1.txt", "hash": "aaa", "drive": ""},
        {"path": "/dir1/shared.txt", "hash": "bbb", "drive": ""},
    ]
    entries2 = [
        {"path": "/dir2/only2.txt", "hash": "ccc", "drive": ""},
        {"path": "/dir2/shared.txt", "hash": "bbb", "drive": ""},
    ]
    comm_mod = _setup_comm(monkeypatch, entries1, entries2)
    comm_mod.cmd_comm(_make_comm_args(yes=True))
    out = capsys.readouterr().out
    lines = out.strip().split("\n")
    # only1.txt should be in column 1 (no tab prefix)
    assert any(l == "only1.txt" for l in lines)
    # only2.txt should be in column 2 (one tab)
    assert any(l == "\tonly2.txt" for l in lines)
    # shared.txt should be in column 3 (two tabs)
    assert any(l == "\t\tshared.txt" for l in lines)


def test_suppress_column_1(monkeypatch, capsys):
    entries1 = [{"path": "/dir1/only1.txt", "hash": "aaa", "drive": ""}]
    entries2 = [{"path": "/dir2/only2.txt", "hash": "bbb", "drive": ""}]
    comm_mod = _setup_comm(monkeypatch, entries1, entries2)
    comm_mod.cmd_comm(_make_comm_args(suppress_1=True, yes=True))
    out = capsys.readouterr().out
    assert "only1.txt" not in out
    assert "only2.txt" in out


def test_suppress_column_2(monkeypatch, capsys):
    entries1 = [{"path": "/dir1/only1.txt", "hash": "aaa", "drive": ""}]
    entries2 = [{"path": "/dir2/only2.txt", "hash": "bbb", "drive": ""}]
    comm_mod = _setup_comm(monkeypatch, entries1, entries2)
    comm_mod.cmd_comm(_make_comm_args(suppress_2=True, yes=True))
    out = capsys.readouterr().out
    assert "only1.txt" in out
    assert "only2.txt" not in out


def test_suppress_column_3(monkeypatch, capsys):
    entries1 = [{"path": "/dir1/shared.txt", "hash": "aaa", "drive": ""}]
    entries2 = [{"path": "/dir2/shared.txt", "hash": "aaa", "drive": ""}]
    comm_mod = _setup_comm(monkeypatch, entries1, entries2)
    comm_mod.cmd_comm(_make_comm_args(suppress_3=True, yes=True))
    out = capsys.readouterr().out
    assert out.strip() == ""


def test_common_file_differs(monkeypatch, capsys):
    entries1 = [{"path": "/dir1/file.txt", "hash": "aaa", "drive": ""}]
    entries2 = [{"path": "/dir2/file.txt", "hash": "bbb", "drive": ""}]
    comm_mod = _setup_comm(monkeypatch, entries1, entries2)
    comm_mod.cmd_comm(_make_comm_args(yes=True))
    out = capsys.readouterr().out
    assert "[differs]" in out


def test_common_file_no_hash(monkeypatch, capsys):
    entries1 = [{"path": "/dir1/file.txt", "hash": None, "drive": ""}]
    entries2 = [{"path": "/dir2/file.txt", "hash": None, "drive": ""}]
    comm_mod = _setup_comm(monkeypatch, entries1, entries2)
    comm_mod.cmd_comm(_make_comm_args(yes=True))
    out = capsys.readouterr().out
    assert "[no-hash]" in out


def test_hashes_mode(monkeypatch, capsys):
    entries1 = [
        {"path": "/dir1/report.pdf", "hash": "a1b2c3d4e5f6a7b8", "drive": ""},
    ]
    entries2 = [
        {"path": "/dir2/notes.txt", "hash": "e5f6a7b8c9d0e1f2", "drive": ""},
    ]
    comm_mod = _setup_comm(monkeypatch, entries1, entries2)
    comm_mod.cmd_comm(_make_comm_args(hashes=True, yes=True))
    out = capsys.readouterr().out
    # Column 1: hash only in dir1
    assert "a1b2c3d4" in out
    assert "report.pdf" in out
    # Column 2: hash only in dir2
    assert "e5f6a7b8" in out
    assert "notes.txt" in out


def test_hashes_extra_copies(monkeypatch, capsys):
    entries1 = [
        {"path": "/dir1/file1.txt", "hash": "aabbccdd11223344", "drive": ""},
        {"path": "/dir1/file2.txt", "hash": "aabbccdd11223344", "drive": ""},
        {"path": "/dir1/file3.txt", "hash": "aabbccdd11223344", "drive": ""},
    ]
    comm_mod = _setup_comm(monkeypatch, entries1, [])
    comm_mod.cmd_comm(_make_comm_args(hashes=True, yes=True))
    out = capsys.readouterr().out
    assert "+2 extra copies" in out


def test_large_output_warning(monkeypatch, capsys):
    # Generate enough unique files to exceed 1000 lines
    entries1 = [
        {"path": f"/dir1/file{i}.txt", "hash": f"hash{i:08d}aabbccdd", "drive": ""}
        for i in range(600)
    ]
    entries2 = [
        {"path": f"/dir2/other{i}.txt", "hash": f"other{i:08d}aabbccdd", "drive": ""}
        for i in range(600)
    ]
    comm_mod = _setup_comm(monkeypatch, entries1, entries2)

    # Mock stdout.isatty to return True, and input to return 'n'
    import io
    monkeypatch.setattr("sys.stdout", type("FakeTTY", (io.StringIO,), {"isatty": lambda self: True})())
    monkeypatch.setattr("builtins.input", lambda: "n")

    with pytest.raises(SystemExit) as exc_info:
        comm_mod.cmd_comm(_make_comm_args())
    assert exc_info.value.code == 0
    err = capsys.readouterr().err
    assert "Warning:" in err
    assert "lines of output" in err


def test_yes_suppresses_warning(monkeypatch, capsys):
    entries1 = [
        {"path": f"/dir1/file{i}.txt", "hash": f"hash{i:04d}", "drive": ""}
        for i in range(600)
    ]
    entries2 = [
        {"path": f"/dir2/file{i}.txt", "hash": f"otherhash{i:04d}", "drive": ""}
        for i in range(600)
    ]
    comm_mod = _setup_comm(monkeypatch, entries1, entries2)
    comm_mod.cmd_comm(_make_comm_args(yes=True))
    err = capsys.readouterr().err
    assert "Warning:" not in err
