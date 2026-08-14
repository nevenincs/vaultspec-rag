"""One job resource crossed over HTTP, typed transport, and the CLI.

The operator reaches a job through three surfaces, and the contract that
matters is that they agree on the same exact identity: a prefix is not a
job id, a stale revision is a conflict on one request and an
already-satisfied replay on the next, and a non-terminal job refuses
deletion whichever surface asks.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest
import uvicorn
from typer.testing import CliRunner

from ... import jobs
from ...cli import app
from ...config._settings import reset_config
from ...config._types import EnvVar
from ...job_models import DesiredJobState, JobSource
from ...registry import get_registry
from ...server import ServerRouteRuntime, create_http_app
from ...serviceclient._transport import (
    _try_http_create_job,
    _try_http_delete_job,
    _try_http_get_job,
    _try_http_set_job_desired_state,
)
from .._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = pytest.mark.integration

_CLI_RUNNER = CliRunner()


@contextmanager
def _real_job_control_server(tmp_path: Path) -> Generator[int]:
    """Serve the production route table over a real loopback socket."""
    status_dir = tmp_path / "http-status"
    port = free_loopback_port()
    token = "service-job-control-e2e-token"
    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    prior_watch_enabled = os.environ.get(EnvVar.WATCH_ENABLED)
    live_server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    stopped = True
    try:
        status_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.WATCH_ENABLED] = "false"
        reset_config()
        jobs.reset()
        (status_dir / "service.json").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "port": port,
                    "service_token": token,
                }
            ),
            encoding="utf-8",
        )
        live_server = uvicorn.Server(
            uvicorn.Config(
                create_http_app(
                    ServerRouteRuntime(
                        token=token,
                        registry=get_registry(),
                        port=port,
                    ),
                    lifespan=None,
                ),
                host="127.0.0.1",
                port=port,
                log_config=None,
                access_log=False,
                lifespan="off",
            )
        )
        thread = threading.Thread(target=live_server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5.0
        while not live_server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert live_server.started
        yield port
    finally:
        if live_server is not None:
            live_server.should_exit = True
        if thread is not None:
            thread.join(timeout=5.0)
            stopped = not thread.is_alive()
        jobs.reset()
        if prior_status_dir is None:
            os.environ.pop(EnvVar.STATUS_DIR, None)
        else:
            os.environ[EnvVar.STATUS_DIR] = prior_status_dir
        if prior_watch_enabled is None:
            os.environ.pop(EnvVar.WATCH_ENABLED, None)
        else:
            os.environ[EnvVar.WATCH_ENABLED] = prior_watch_enabled
        reset_config()
        assert stopped


def _invoke_job_json(*args: str) -> tuple[int, dict[str, object]]:
    result = _CLI_RUNNER.invoke(app, ["server", "job", *args, "--json"])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, result.stdout
    payload = json.loads(lines[0])
    assert isinstance(payload, dict)
    return result.exit_code, cast("dict[str, object]", payload)


def _create_operator_matrix_job(port: int, project_root: Path) -> tuple[str, int]:
    """Create one paused job for the cross-surface operator matrix."""
    created = _try_http_create_job(
        JobSource.VAULT,
        str(project_root),
        port,
        start_paused=True,
        idempotency_key="e2e-operator-matrix",
        timeout=5.0,
    )
    assert created is not None
    assert created["code"] == "job_created"
    created_job = cast("dict[str, object]", created["job"])
    return cast("str", created_job["id"]), cast("int", created_job["revision"])


def _assert_operator_matrix_lookup(port: int, job_id: str) -> None:
    """Assert typed and CLI lookup agree on exact-ID semantics."""
    detail = _try_http_get_job(job_id, port, timeout=5.0)
    assert detail is not None
    assert detail["ok"] is True
    detail_job = cast("dict[str, object]", detail["job"])
    assert detail_job["id"] == job_id
    exit_code, shown = _invoke_job_json("show", job_id, "--port", str(port))
    assert exit_code == 0
    assert shown["ok"] is True
    exit_code, prefix_rejected = _invoke_job_json(
        "show", job_id[:8], "--port", str(port)
    )
    assert exit_code == 1
    assert prefix_rejected["error"] == "job_not_found"


def _assert_operator_matrix_conflicts(port: int, job_id: str, revision: int) -> None:
    """Assert revision replay, active-delete, and force-stop outcomes."""
    stale = _try_http_set_job_desired_state(
        job_id,
        DesiredJobState.RUNNING,
        port,
        expected_revision=revision + 100,
        timeout=5.0,
    )
    assert stale is not None
    assert stale["ok"] is False
    assert stale["error"] == "revision_conflict"
    replay = _try_http_set_job_desired_state(
        job_id,
        DesiredJobState.PAUSED,
        port,
        expected_revision=revision + 100,
        timeout=5.0,
    )
    assert replay is not None
    assert replay["ok"] is True
    assert replay["code"] == "already_satisfied"
    active_delete = _try_http_delete_job(job_id, port, timeout=5.0)
    assert active_delete is not None
    assert active_delete["ok"] is False
    assert active_delete["error"] == "job_not_terminal"
    exit_code, force_rejected = _invoke_job_json(
        "stop", job_id, "--port", str(port), "--force"
    )
    assert exit_code == 1
    assert force_rejected["error"] == "force_termination_unavailable"


def _complete_operator_matrix(port: int, job_id: str) -> None:
    """Cancel through the CLI and delete through typed transport."""
    exit_code, stopped = _invoke_job_json("stop", job_id, "--port", str(port))
    assert exit_code == 0
    assert stopped["ok"] is True
    stopped_data = cast("dict[str, object]", stopped["data"])
    assert stopped_data["status"] == "job_cancelled"
    deleted = _try_http_delete_job(job_id, port, timeout=5.0)
    assert deleted is not None
    assert deleted["ok"] is True
    assert deleted["code"] == "job_deleted"


def test_http_transport_and_cli_outcome_matrix_uses_exact_job_ids(
    tmp_path: Path,
) -> None:
    """Cross HTTP, typed transport, and CLI with one exact job resource."""
    project_root = tmp_path / "operator-matrix"
    (project_root / ".vault").mkdir(parents=True)
    with _real_job_control_server(tmp_path) as port:
        job_id, revision = _create_operator_matrix_job(port, project_root)
        _assert_operator_matrix_lookup(port, job_id)
        _assert_operator_matrix_conflicts(port, job_id, revision)
        _complete_operator_matrix(port, job_id)
