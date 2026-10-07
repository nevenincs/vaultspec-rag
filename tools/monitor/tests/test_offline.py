"""Offline proof must refuse a network policy that still permits a connection."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

import pytest

from tools.monitor import offline

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_missing_network_denial_cannot_produce_offline_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bypassing denial refusal failed; exact restoration passed (exits 1/0)."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        monkeypatch.setattr(offline, "CONTROL_HOST", "127.0.0.1")
        monkeypatch.setattr(offline, "CONTROL_PORT", listener.getsockname()[1])
        assert offline.external_connection()
        with pytest.raises(RuntimeError, match="external TCP still connects"):
            offline.require_denial()
    assert not offline.external_connection()
    offline.require_denial()


@pytest.mark.unit
def test_a_host_without_a_denied_directory_is_told_how_to_provision_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The Windows proof never falls back to a path nothing denies.

    Mutation proof: returning the configured path without the directory check
    failed the missing-directory case; restoring the check passed.
    """
    remedy = "--provision-denied-directory"
    monkeypatch.delenv(offline.DENIED_DIRECTORY, raising=False)
    with pytest.raises(RuntimeError, match=remedy):
        offline.denied_directory()
    monkeypatch.setenv(offline.DENIED_DIRECTORY, str(tmp_path / "absent"))
    with pytest.raises(RuntimeError, match=remedy):
        offline.denied_directory()
    monkeypatch.setenv(offline.DENIED_DIRECTORY, "relative")
    with pytest.raises(RuntimeError, match=remedy):
        offline.denied_directory()
    monkeypatch.setenv(offline.DENIED_DIRECTORY, str(tmp_path))
    assert offline.denied_directory() == tmp_path
