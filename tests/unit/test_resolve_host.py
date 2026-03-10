"""Tests for sift.commands.resolve_host()."""

from types import SimpleNamespace

import pytest


def test_resolve_host_case_insensitive_match(monkeypatch):
    from sift.commands import resolve_host
    from sift import client

    monkeypatch.setattr(
        client, "get", lambda path, **kw: [{"host": "Unraid"}, {"host": "MyMac"}]
    )
    assert resolve_host("unraid") == "Unraid"
    assert resolve_host("UNRAID") == "Unraid"
    assert resolve_host("mymac") == "MyMac"
    assert resolve_host("MYMAC") == "MyMac"


def test_resolve_host_exact_case_passthrough(monkeypatch):
    from sift.commands import resolve_host
    from sift import client

    monkeypatch.setattr(
        client, "get", lambda path, **kw: [{"host": "Unraid"}]
    )
    assert resolve_host("Unraid") == "Unraid"


def test_resolve_host_unknown_host_returns_input(monkeypatch):
    from sift.commands import resolve_host
    from sift import client

    monkeypatch.setattr(
        client, "get", lambda path, **kw: [{"host": "Unraid"}]
    )
    assert resolve_host("nonexistent") == "nonexistent"


def test_resolve_host_server_unreachable_returns_input(monkeypatch):
    from sift.commands import resolve_host
    from sift import client

    def fail(*args, **kwargs):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(client, "get", fail)
    assert resolve_host("MyHost") == "MyHost"


def test_resolve_host_localhost_maps_to_local_hostname(monkeypatch):
    import sift.commands as commands_mod
    from sift.commands import resolve_host
    from sift import client

    monkeypatch.setattr(commands_mod, "local_hostname", lambda: "mymachine")
    monkeypatch.setattr(
        client, "get", lambda path, **kw: [{"host": "mymachine"}]
    )
    assert resolve_host("localhost") == "mymachine"


def test_resolve_host_127_0_0_1_maps_to_local_hostname(monkeypatch):
    import sift.commands as commands_mod
    from sift.commands import resolve_host
    from sift import client

    monkeypatch.setattr(commands_mod, "local_hostname", lambda: "mymachine")
    monkeypatch.setattr(
        client, "get", lambda path, **kw: [{"host": "mymachine"}]
    )
    assert resolve_host("127.0.0.1") == "mymachine"


def test_resolve_host_localhost_with_canonical_case(monkeypatch):
    import sift.commands as commands_mod
    from sift.commands import resolve_host
    from sift import client

    monkeypatch.setattr(commands_mod, "local_hostname", lambda: "mymachine")
    monkeypatch.setattr(
        client, "get", lambda path, **kw: [{"host": "MyMachine"}]
    )
    # localhost → local_hostname() → "mymachine" → case match → "MyMachine"
    assert resolve_host("localhost") == "MyMachine"


def test_resolve_host_strips_whitespace(monkeypatch):
    from sift.commands import resolve_host
    from sift import client

    monkeypatch.setattr(
        client, "get", lambda path, **kw: [{"host": "Unraid"}]
    )
    assert resolve_host("  Unraid  ") == "Unraid"
    assert resolve_host("  unraid  ") == "Unraid"


def test_resolve_host_empty_hosts_returns_input(monkeypatch):
    from sift.commands import resolve_host
    from sift import client

    monkeypatch.setattr(client, "get", lambda path, **kw: [])
    assert resolve_host("Unraid") == "Unraid"
