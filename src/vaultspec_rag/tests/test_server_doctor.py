"""Unit coverage for the ``server doctor`` readiness CLI verb.

Exercises the real Typer surface and asserts the verb renders the same bounded
snapshot the service-domain reporter (``api.get_readiness``) produces, in both
human and JSON modes. No mocks, patches, fakes, or skips. The CLI/route parity
(both adapters returning the identical snapshot) is asserted at the integration
tier in ``integration/test_server_doctor_route.py``.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from ..api import get_readiness
from ..cli import app

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def test_doctor_json_envelope_matches_readiness_snapshot() -> None:
    result = runner.invoke(app, ["server", "doctor", "--json"])
    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert envelope["command"] == "server doctor"
    # The verb is a thin adapter: its data IS the reporter's snapshot.
    assert envelope["data"] == get_readiness()
    assert envelope["ok"] == bool(envelope["data"]["ready"])


def test_doctor_json_snapshot_is_bounded_three_dimensions() -> None:
    result = runner.invoke(app, ["server", "doctor", "--json"])
    data = json.loads(result.stdout)["data"]
    names = [dep["name"] for dep in data["dependencies"]]
    assert names == ["torch", "models", "qdrant"]
    assert isinstance(data["ready"], bool)
    assert isinstance(data["server_mode"], bool)


def test_doctor_human_render_lists_each_dependency() -> None:
    result = runner.invoke(app, ["server", "doctor"])
    assert result.exit_code == 0
    assert "Service readiness" in result.output
    assert "Readiness:" in result.output
    for name in ("torch", "models", "qdrant"):
        assert name in result.output
