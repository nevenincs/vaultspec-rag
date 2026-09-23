"""Status surfaces facing a service this client cannot read, or can.

A real loopback HTTP stub stands in for the service, so discovery, transport
and parsing all run for real; only the service's answers are chosen.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import threading
import typing

import pytest

from ..cli._preprocess import _running_service_preprocess_mode
from ..operator_state._features import TypesafeState
from ..operator_state._models import HealthReport, ServiceFeatures, TypesafeReport
from ..operator_state._service import HealthVerdict
from ._cli_helpers import (
    EnvVar,
    _write_service_status,
    app,
    reset_base_config,
    reset_rag_config,
    runner,
)
from ._http_stubs import QuietHandler
from ._scaffold import make_workspace

if typing.TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..config._types import PreprocessMode

pytestmark = [pytest.mark.unit]


@contextlib.contextmanager
def _service_answering(tmp_path: Path, routes: dict[str, object]) -> Generator[int]:
    """Serve *routes* on a loopback port recorded as this machine's service."""

    class Handler(QuietHandler):
        def do_GET(self) -> None:
            body = routes.get(self.path.split("?", 1)[0])
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body or {}).encode("utf-8"))

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    os.environ[EnvVar.STATUS_DIR] = str(status_dir)
    os.environ[EnvVar.QDRANT_STORAGE_DIR] = str(tmp_path / "qdrant" / "storage")
    reset_base_config()
    reset_rag_config()
    try:
        _write_service_status(pid=os.getpid(), port=server.server_port)
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
        os.environ.pop(EnvVar.STATUS_DIR, None)
        os.environ.pop(EnvVar.QDRANT_STORAGE_DIR, None)
        reset_base_config()
        reset_rag_config()


def test_an_older_service_is_reported_as_a_release_mismatch(tmp_path: Path) -> None:
    """A service whose state this client cannot read is named, not bypassed.

    Mutation check: falling back to the local store when the state does not
    parse reports the index as busy or empty instead, and fails the mismatch
    assertion; restoring the refusal passes.
    """
    root = make_workspace(tmp_path)
    older_state = {"index": {"storage_path": "x", "vault_count": 1}}
    older_health = {"status": "ready", "package_version": "0.0.1"}

    with _service_answering(
        tmp_path, {"/service-state": older_state, "/health": older_health}
    ):
        result = runner.invoke(app, ["--target", str(root), "status"])

    assert result.exit_code == 1, result.output
    assert "0.0.1" in result.output
    assert "busy" not in result.output


def _health_with_mode(mode: PreprocessMode) -> dict[str, object]:
    return HealthReport(
        status=HealthVerdict.READY,
        features=ServiceFeatures(
            typesafe=TypesafeReport(state=TypesafeState.OFF, model="systemone"),
            reranker_enabled=True,
            reranker_loaded=True,
            sparse_enabled=False,
            watcher_enabled=True,
            preprocess_mode=mode,
            storage_backend="server",
            embedding_model="embedder",
        ),
        models_loaded=True,
        project_count=0,
        pid=1,
        parent_pid=1,
        port=1,
        executable="python",
        prefix="/env",
        base_prefix="/base",
        uptime_s=1.0,
        schema_version=2,
        package_version="0.0.0",
        service_token="token",
        jobs={},
        qdrant={},
        quiesce={},
        backend_capabilities={},
        support_profile={},
    ).model_dump(mode="json")


def test_preprocess_status_reads_the_running_service_mode(tmp_path: Path) -> None:
    """Indexing runs in the service, so its switch decides whether hooks run.

    Mutation check: reading this shell's configured mode instead of the
    service's reports ``default`` here and fails the assertion; restoring the
    service read passes.
    """
    with _service_answering(tmp_path, {"/health": _health_with_mode("off")}):
        assert _running_service_preprocess_mode() == "off"


def test_an_unreadable_service_health_gives_no_mode(tmp_path: Path) -> None:
    partial = {"status": "ready", "features": {"preprocess_mode": "off"}}

    with _service_answering(tmp_path, {"/health": partial}):
        assert _running_service_preprocess_mode() is None


def test_preprocess_status_falls_back_when_no_service_answers(tmp_path: Path) -> None:
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    os.environ[EnvVar.STATUS_DIR] = str(status_dir)
    reset_base_config()
    reset_rag_config()
    try:
        assert _running_service_preprocess_mode() is None
    finally:
        os.environ.pop(EnvVar.STATUS_DIR, None)
        reset_base_config()
        reset_rag_config()


def test_health_never_reaches_the_installation_or_hardware_probes() -> None:
    """``/health`` stays a lightweight, ungated probe.

    Installation and hardware are read once, on ``/service-state``; a health
    poll paying for a driver round trip or a torch classification would make
    every liveness check expensive.

    Mutation check: building the installation report inside the health
    handler populates the installation cache and fails the first assertion;
    removing it passes.
    """
    from starlette.testclient import TestClient

    from .. import api
    from ..operator_state._hardware import read_hardware
    from ..server import ServerRouteRuntime, create_http_app
    from ..service import ServiceRegistry

    api.service_installation.cache_clear()
    read_hardware.cache_clear()
    app_ = create_http_app(
        ServerRouteRuntime(token="probe", registry=ServiceRegistry(), port=8766),
        lifespan=None,
    )

    assert TestClient(app_).get("/health").status_code == 200
    assert api.service_installation.cache_info().currsize == 0
    assert read_hardware.cache_info().currsize == 0
