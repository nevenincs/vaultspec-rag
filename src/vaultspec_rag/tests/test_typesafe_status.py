"""Daemon enrollment on health and lifecycle presentation, without GPU startup."""

from __future__ import annotations

import json
from typing import cast

import pytest
from starlette.testclient import TestClient

from ..cli._cli_format import NOT_REPORTED
from ..cli._service_start import _start_success
from ..cli._status_labels import typesafe_label
from ..cli._status_render import _render_status_summary, _StatusSummaryRequest
from ..config._types import EnvVar
from ..operator_state._service import ServiceLifecycle
from ..server import ServerRouteRuntime, create_http_app
from ..service import ServiceRegistry

pytestmark = pytest.mark.unit


def test_health_reports_daemon_enrollment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EnvVar.TYPESAFE_API_KEY, "status-only-secret")
    app = create_http_app(
        ServerRouteRuntime(token="test", registry=ServiceRegistry(), port=8766),
        lifespan=None,
    )
    data = cast("dict[str, object]", TestClient(app).get("/health").json())
    features = cast("dict[str, object]", data["features"])
    snapshot = cast("dict[str, object]", features["typesafe"])
    assert snapshot["state"] == "pending"
    assert "status-only-secret" not in json.dumps(data)


@pytest.mark.parametrize("state", ["off", "pending", "active", "rejected", "cooldown"])
def test_start_and_status_render_same_daemon_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], state: str
) -> None:
    monkeypatch.setenv(EnvVar.TYPESAFE_API_KEY, "client-must-not-win")
    snapshot: dict[str, object] = {"state": state}
    health: dict[str, object] = {"features": {"typesafe": snapshot}}
    expected = f"Typesafe: {typesafe_label(snapshot)}"
    _start_success(
        False,
        status="started",
        human_title="Service started",
        human_lines=(),
        typesafe=snapshot,
    )
    assert expected in capsys.readouterr().out
    _render_status_summary(
        _StatusSummaryRequest(ServiceLifecycle.RUNNING, 8766, True, health, None)
    )
    assert expected in capsys.readouterr().out
    _start_success(
        True,
        status="already_running",
        human_title="Service already running",
        human_lines=(),
        typesafe=snapshot,
    )
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["data"]["typesafe"] == snapshot
    assert "client-must-not-win" not in json.dumps(envelope)


def test_missing_daemon_evidence_is_not_inferred_from_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(EnvVar.TYPESAFE_API_KEY, "client-only")
    assert typesafe_label(None) == NOT_REPORTED
    assert typesafe_label({}) == NOT_REPORTED
