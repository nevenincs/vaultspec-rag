"""Guard tests for the ``server pause`` / ``server resume`` envelope contract.

These are guard tests, not positive coverage: the load-bearing properties are
that an already-satisfied request is a SUCCESS (exit 0 with an ``already_*``
status), and that a request which did NOT achieve the state - a pause the daemon
refused because a shutdown latched the gate open - is a FAILURE (exit 1), never a
false success a broker would read as done. Each is proven able to fail by the
branch it exercises: flip the expected exit code and the assertion reports it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from typer.testing import Result

from ..cli import _service_quiesce as quiesce
from ..cli import app

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def _stub_admin(
    monkeypatch: pytest.MonkeyPatch, envelope: dict[str, Any] | None
) -> None:
    """Stand in for the HTTP admin call so no service is required.

    Patched on the command module's bound name (the call site), and the port
    resolver is fixed so the reachable path is taken; a broken patch here would
    let the real transport run and the test would fail loudly rather than pass
    vacuously.
    """

    def _fake_admin(*_a: object, **_k: object) -> dict[str, Any] | None:
        return envelope

    monkeypatch.setattr(quiesce, "_default_service_port", lambda: 8766)
    monkeypatch.setattr(quiesce, "_try_http_admin", _fake_admin)


def _json(result: Result) -> dict[str, Any]:
    return json.loads(result.output)


def test_pause_change_is_success_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_admin(monkeypatch, {"ok": True, "status": "paused", "paused": True})
    result = runner.invoke(app, ["server", "pause", "--json"])
    assert result.exit_code == 0, result.output
    body = _json(result)
    assert body["ok"] is True
    assert body["data"]["status"] == "paused"


def test_pause_already_paused_is_idempotent_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Idempotent success: re-pausing a held service exits 0 with already_paused,
    # never a non-zero fault. Flip this to exit 1 and the guard fails.
    _stub_admin(monkeypatch, {"ok": True, "status": "already_paused", "paused": True})
    result = runner.invoke(app, ["server", "pause", "--json"])
    assert result.exit_code == 0, result.output
    assert _json(result)["data"]["status"] == "already_paused"


def test_resume_already_running_is_idempotent_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_admin(monkeypatch, {"ok": True, "status": "already_running", "paused": False})
    result = runner.invoke(app, ["server", "resume", "--json"])
    assert result.exit_code == 0, result.output
    assert _json(result)["data"]["status"] == "already_running"


def test_pause_that_did_not_hold_is_failure_exit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Load-bearing guard: the route reports ok=True but paused=False because a
    # shutdown latched the gate open, so the hold was NOT achieved. This MUST
    # exit non-zero, or a broker reads a still-running service as paused.
    _stub_admin(monkeypatch, {"ok": True, "status": "paused", "paused": False})
    result = runner.invoke(app, ["server", "pause", "--json"])
    assert result.exit_code == 1, result.output
    body = _json(result)
    assert body["ok"] is False
    assert body["error"] == "hold_not_achieved"


def test_resume_that_did_not_release_is_failure_exit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_admin(monkeypatch, {"ok": True, "status": "resumed", "paused": True})
    result = runner.invoke(app, ["server", "resume", "--json"])
    assert result.exit_code == 1, result.output
    assert _json(result)["error"] == "release_not_achieved"


def test_unreachable_service_is_failure_exit_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A None result means the daemon did not answer: there is no gate to hold,
    # so the request failed rather than being vacuously satisfied.
    _stub_admin(monkeypatch, None)
    result = runner.invoke(app, ["server", "pause", "--json"])
    assert result.exit_code == 1, result.output
    assert _json(result)["error"] == "service_unreachable"


def test_exactly_one_json_envelope_per_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The broker contract requires exactly one structured document on stdout on
    # every exit path; more than one line of JSON would break machine parsing.
    _stub_admin(monkeypatch, {"ok": True, "status": "paused", "paused": True})
    result = runner.invoke(app, ["server", "pause", "--json"])
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 1, result.output
    json.loads(lines[0])
