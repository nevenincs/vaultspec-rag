"""``server restart`` composes stop and start into exactly one outcome."""

from __future__ import annotations

import json
from typing import cast

import pytest
from typer.testing import CliRunner

from ..cli import _service_restart, app

pytestmark = pytest.mark.unit


def _restart(
    monkeypatch: pytest.MonkeyPatch,
    steps: dict[str, dict[str, object]],
    released: object,
) -> tuple[int, list[dict[str, object]], list[str]]:
    ran: list[str] = []

    def run_verb(verb: str, _port: int | None) -> dict[str, object]:
        ran.append(verb)
        return steps[verb]

    def release_monitor(*_args: object) -> object:
        return released

    # The real steps start and stop the machine's GPU service, which a unit
    # test cannot; replacing them pins the envelope composition alone.
    monkeypatch.setattr(_service_restart, "_run_verb", run_verb)
    monkeypatch.setattr(_service_restart, "_try_http_admin", release_monitor)
    result = CliRunner().invoke(app, ["server", "restart", "--json", "--port", "1"])
    envelopes = [json.loads(line) for line in result.stdout.splitlines() if line]
    return result.exit_code, envelopes, ran


def test_a_restart_that_kept_the_monitor_reports_one_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, envelopes, ran = _restart(
        monkeypatch,
        {
            "stop": {"ok": True, "data": {"status": "stopped"}},
            "start": {
                "ok": True,
                "data": {"status": "started", "port": 1, "monitor_url": "link"},
            },
        },
        {"ok": True, "status": "handed_off"},
    )

    assert code == 0
    assert ran == ["stop", "start"]
    assert len(envelopes) == 1
    assert envelopes[0]["command"] == "service.restart"
    data = cast("dict[str, object]", envelopes[0]["data"])
    assert data["status"] == "restarted"
    assert data["monitor_kept"] is True


def test_a_failed_stop_never_starts_and_fails_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, envelopes, ran = _restart(
        monkeypatch,
        {"stop": {"ok": False, "message": "The service is still running."}},
        None,
    )

    assert code == 1
    assert ran == ["stop"]
    assert len(envelopes) == 1
    assert envelopes[0]["ok"] is False
    assert envelopes[0]["error"] == "restart_stop_failed"
    assert envelopes[0]["message"] == "The service is still running."


def test_a_stopped_service_is_started_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, envelopes, _ = _restart(
        monkeypatch,
        {
            "stop": {"ok": True, "data": {"status": "already_stopped"}},
            "start": {"ok": False, "message": "Models are missing."},
        },
        None,
    )

    assert code == 1
    assert envelopes[0]["error"] == "restart_start_failed"
    assert envelopes[0]["message"] == "Models are missing."
