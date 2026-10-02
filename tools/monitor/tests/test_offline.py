"""Offline proof must refuse a network policy that still permits a connection."""

from __future__ import annotations

import socket

import pytest

from tools.monitor import offline

pytestmark = pytest.mark.unit


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
