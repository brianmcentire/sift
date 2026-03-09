"""Tests for null-hash retry prefetch helper."""

from sift.commands.scan import _prefetch_null_hash_retry_paths


def test_prefetch_null_hash_retry_paths_filters_null_hash(monkeypatch):
    def fake_get(path, params=None):
        assert path == "/files"
        assert params is not None
        assert params["host"] == "mac"
        assert params["path_prefix"] == "/users/brian"
        return [
            {"path_display": "/Users/Brian/a.txt", "hash": None},
            {"path_display": "/Users/Brian/b.txt", "hash": "abcd"},
            {"path_display": "/Users/Brian/c.txt", "hash": None},
        ]

    monkeypatch.setattr("sift.commands.scan.client.get", fake_get)
    got = _prefetch_null_hash_retry_paths(
        host="mac",
        root_path="/users/brian",
        drive="",
        quiet=True,
    )
    assert got == {"/users/brian/a.txt", "/users/brian/c.txt"}


def test_prefetch_null_hash_retry_paths_skips_drive_scoped(capsys):
    got = _prefetch_null_hash_retry_paths(
        host="pc",
        root_path="/",
        drive="C",
        quiet=False,
    )
    assert got == set()
    err = capsys.readouterr().err
    assert "drive-scoped lookup is not available" in err
