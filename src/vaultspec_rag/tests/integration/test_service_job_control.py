"""Real-server coverage for typed service job-control transport operations."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest
import uvicorn
from typer.testing import CliRunner

from ...cli import app
from ...config._settings import reset_config
from ...config._types import EnvVar
from ...job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
)
from ...jobs import get_job_manager
from ...jobs import reset as reset_jobs
from ...mcp._mcp import mcp
from ...mcp._tools import reindex_vault
from ...server import ServerRouteRuntime, create_http_app
from ...service import ServiceRegistry
from ...serviceclient._compat import SERVICE_VERSION_FIELD, local_package_version
from ...serviceclient._transport import (
    _try_http_create_job,
    _try_http_delete_job,
    _try_http_get_job,
    _try_http_retry_job,
    _try_http_set_job_desired_state,
)
from .._ports import free_loopback_port
from .._scaffold import make_workspace

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

runner = CliRunner()

pytestmark = [pytest.mark.unit]


@contextmanager
def _real_job_control_server(tmp_path: Path) -> Generator[int]:
    """Run the production route table over a real loopback HTTP socket."""
    status_dir = tmp_path / "status"
    port = free_loopback_port()
    token = "real-job-control-token"
    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    prior_watch_enabled = os.environ.get(EnvVar.WATCH_ENABLED)
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    stopped = True
    try:
        status_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.WATCH_ENABLED] = "false"
        reset_config()
        reset_jobs()
        (status_dir / "service.json").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "port": port,
                    "service_token": token,
                    # A real daemon stamps its release here, and a client
                    # refuses a data-plane call to one that does not. Omitting
                    # it would model a service this fixture never stands up.
                    SERVICE_VERSION_FIELD: local_package_version(),
                }
            ),
            encoding="utf-8",
        )

        server = uvicorn.Server(
            uvicorn.Config(
                create_http_app(
                    ServerRouteRuntime(
                        token=token,
                        registry=ServiceRegistry(),
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
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield port
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5.0)
            stopped = not thread.is_alive()
        reset_jobs()
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


def _seed_paused_job(project_root: Path, job_id: str) -> dict[str, object]:
    (project_root / ".vault").mkdir(parents=True)
    outcome = get_job_manager().create(
        JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.VAULT,
            project_root=str(project_root),
            mode=JobMode.INCREMENTAL,
        ),
        JobInitiator(
            kind="cli",
            command="test_seed_job_control",
            project_root=str(project_root),
        ),
        start_paused=True,
        job_id=job_id,
    )
    assert outcome.code == "job_created"
    assert outcome.job is not None
    return outcome.job.to_dict()


def _invoke_job_json(*args: str) -> tuple[int, dict[str, object]]:
    result = runner.invoke(app, ["server", "job", *args, "--json"])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, result.stdout
    payload = json.loads(lines[0])
    assert isinstance(payload, dict)
    return result.exit_code, cast("dict[str, object]", payload)


def _create_paused_transport_job(port: int, project_root: Path) -> tuple[str, int]:
    """Create one paused job through the typed transport."""
    created = _try_http_create_job(
        JobSource.VAULT,
        str(project_root),
        port,
        start_paused=True,
        idempotency_key="real-transport-lifecycle",
        timeout=5.0,
    )
    assert created is not None
    assert created["ok"] is True
    assert created["status"] == "accepted"
    assert created["code"] == "job_created"
    created_job = cast("dict[str, object]", created["job"])
    assert created_job["state"] == "paused"
    return cast("str", created_job["id"]), cast("int", created_job["revision"])


def _assert_transport_conflicts(port: int, job_id: str) -> None:
    """Assert exact lookup plus force and active-delete conflicts."""
    detail = _try_http_get_job(job_id, port, timeout=5.0)
    assert detail is not None
    assert detail["ok"] is True
    detail_job = cast("dict[str, object]", detail["job"])
    assert detail_job["id"] == job_id
    assert detail_job["desired_state"] == "paused"
    force_rejected = _try_http_set_job_desired_state(
        job_id,
        DesiredJobState.RUNNING,
        port,
        mode="force",
        timeout=5.0,
    )
    assert force_rejected is not None
    assert force_rejected["ok"] is False
    assert force_rejected["status"] == "error"
    assert force_rejected["error"] == "force_termination_unavailable"
    delete_rejected = _try_http_delete_job(job_id, port, timeout=5.0)
    assert delete_rejected is not None
    assert delete_rejected["ok"] is False
    assert delete_rejected["error"] == "job_not_terminal"


def _complete_transport_lifecycle(
    port: int,
    job_id: str,
    revision: int,
) -> None:
    """Cancel, retry, delete, and verify absence through typed transport."""
    cancelled = _try_http_set_job_desired_state(
        job_id,
        DesiredJobState.CANCELLED,
        port,
        expected_revision=revision,
        timeout=5.0,
    )
    assert cancelled is not None
    assert cancelled["ok"] is True
    cancelled_job = cast("dict[str, object]", cancelled["job"])
    assert cancelled_job["state"] == "cancelled"
    get_job_manager().begin_shutdown()
    retried = _try_http_retry_job(job_id, port, timeout=5.0)
    assert retried is not None
    assert retried["ok"] is True
    assert retried["status"] == "accepted"
    assert retried["code"] == "job_retry_created"
    retried_job = cast("dict[str, object]", retried["job"])
    assert retried_job["parent_job_id"] == job_id
    assert retried_job["id"] != job_id
    deleted = _try_http_delete_job(job_id, port, timeout=5.0)
    assert deleted is not None
    assert deleted["ok"] is True
    assert deleted["code"] == "job_deleted"
    missing = _try_http_get_job(job_id, port, timeout=5.0)
    assert missing is not None
    assert missing["ok"] is False
    assert missing["error"] == "job_not_found"


def test_typed_job_control_transport_uses_real_http_methods_and_conflicts(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    (project_root / ".vault").mkdir(parents=True)

    with _real_job_control_server(tmp_path) as port:
        job_id, revision = _create_paused_transport_job(port, project_root)
        _assert_transport_conflicts(port, job_id)
        _complete_transport_lifecycle(port, job_id, revision)


def _assert_human_lookup(port_arg: str, first_id: str) -> None:
    """Assert unique prefixes resolve and ambiguous prefixes are rejected."""
    shown = runner.invoke(
        app,
        ["server", "job", "show", "abcdef01", "--port", port_arg],
    )
    assert shown.exit_code == 0, shown.output
    assert f"Job {first_id}" in shown.stdout
    assert "Status: paused" in shown.stdout
    ambiguous = runner.invoke(
        app,
        ["server", "job", "show", "abcdef", "--port", port_arg],
    )
    assert ambiguous.exit_code == 2
    assert "Code: ambiguous_job_id" in ambiguous.stdout


def _exercise_human_lifecycle(port_arg: str, first_id: str) -> None:
    """Exercise the human pause, resume, stop, retry, and delete surfaces."""
    paused = runner.invoke(
        app,
        ["server", "job", "pause", "abcdef01", "--port", port_arg],
    )
    assert paused.exit_code == 0, paused.output
    assert "Outcome: already_satisfied" in paused.stdout
    get_job_manager().begin_shutdown()
    resumed = runner.invoke(
        app,
        ["server", "job", "resume", "abcdef01", "--port", port_arg],
    )
    assert resumed.exit_code == 0, resumed.output
    assert f"Job: {first_id}" in resumed.stdout
    assert "Desired state: running" in resumed.stdout
    stopped = runner.invoke(
        app,
        ["server", "job", "stop", "abcdef01", "--port", port_arg],
    )
    assert stopped.exit_code == 0, stopped.output
    assert "State: cancelled" in stopped.stdout
    retried = runner.invoke(
        app,
        ["server", "job", "retry", "abcdef01", "--port", port_arg],
    )
    assert retried.exit_code == 0, retried.output
    assert "Outcome: job_retry_created" in retried.stdout
    linked_retries = [
        snapshot
        for snapshot in get_job_manager().list_jobs()
        if snapshot.attempt.parent_job_id == first_id
    ]
    assert len(linked_retries) == 1
    assert linked_retries[0].id != first_id
    deleted = runner.invoke(
        app,
        ["server", "job", "delete", "abcdef01", "--port", port_arg],
    )
    assert deleted.exit_code == 0, deleted.output
    assert "Outcome: job_deleted" in deleted.stdout


def test_human_cli_job_controls_resolve_unique_prefixes_before_exact_mutation(
    tmp_path: Path,
) -> None:
    first_id = "abcdef01-0000-4000-8000-000000000001"
    second_id = "abcdef02-0000-4000-8000-000000000002"

    with _real_job_control_server(tmp_path) as port:
        _seed_paused_job(tmp_path / "first", first_id)
        _seed_paused_job(tmp_path / "second", second_id)
        port_arg = str(port)
        _assert_human_lookup(port_arg, first_id)
        _exercise_human_lifecycle(port_arg, first_id)


def _assert_json_lookup(port_arg: str, job_id: str) -> None:
    """Assert JSON lookup requires an exact canonical ID."""
    exit_code, shown = _invoke_job_json("show", job_id, "--port", port_arg)
    assert exit_code == 0
    assert shown["ok"] is True
    shown_data = cast("dict[str, object]", shown["data"])
    shown_job = cast("dict[str, object]", shown_data["job"])
    assert shown_job["id"] == job_id
    exit_code, prefix_rejected = _invoke_job_json(
        "show", "12345678", "--port", port_arg
    )
    assert exit_code == 1
    assert prefix_rejected["ok"] is False
    assert prefix_rejected["error"] == "job_not_found"


def _assert_json_stop_lifecycle(port_arg: str, job_id: str) -> None:
    """Assert force refusal, cancellation, and idempotent replay envelopes."""
    exit_code, force_rejected = _invoke_job_json(
        "stop", job_id, "--port", port_arg, "--force"
    )
    assert exit_code == 1
    assert force_rejected["ok"] is False
    assert force_rejected["error"] == "force_termination_unavailable"
    exit_code, stopped = _invoke_job_json("stop", job_id, "--port", port_arg)
    assert exit_code == 0
    assert stopped["ok"] is True
    stopped_data = cast("dict[str, object]", stopped["data"])
    assert stopped_data["status"] == "job_cancelled"
    stopped_job = cast("dict[str, object]", stopped_data["job"])
    assert stopped_job["state"] == "cancelled"
    exit_code, replayed = _invoke_job_json("stop", job_id, "--port", port_arg)
    assert exit_code == 0
    assert replayed["ok"] is True
    replayed_data = cast("dict[str, object]", replayed["data"])
    assert replayed_data["status"] == "already_satisfied"


def _assert_json_delete_lifecycle(port_arg: str, job_id: str) -> None:
    """Assert terminal deletion and its stable missing replay."""
    exit_code, deleted = _invoke_job_json("delete", job_id, "--port", port_arg)
    assert exit_code == 0
    assert deleted["ok"] is True
    deleted_data = cast("dict[str, object]", deleted["data"])
    assert deleted_data["status"] == "job_deleted"
    exit_code, missing = _invoke_job_json("delete", job_id, "--port", port_arg)
    assert exit_code == 1
    assert missing["ok"] is False
    assert missing["error"] == "job_not_found"


def test_json_cli_job_controls_use_full_ids_and_one_stable_outcome(
    tmp_path: Path,
) -> None:
    job_id = "12345678-0000-4000-8000-000000000001"

    with _real_job_control_server(tmp_path) as port:
        _seed_paused_job(tmp_path / "json", job_id)
        port_arg = str(port)
        _assert_json_lookup(port_arg, job_id)
        _assert_json_stop_lifecycle(port_arg, job_id)
        _assert_json_delete_lifecycle(port_arg, job_id)


def test_reindex_compatibility_keeps_mcp_refresh_distinct_from_clean(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "mcp-refresh"
    project_root.mkdir()
    make_workspace(project_root)

    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "search_vault",
        "search_codebase",
        "search_documents",
        "search_combined",
        "get_code_file",
        "reindex_vault",
        "reindex_codebase",
        "reindex_documents",
        "reindex_all",
        "get_index_status",
        "clean_documents",
        "clean_all",
    }
    assert {
        "show_job",
        "pause_job",
        "resume_job",
        "stop_job",
        "retry_job",
        "delete_job",
        "get_jobs",
    }.isdisjoint(tool.name for tool in tools)
    for tool in tools:
        if tool.name not in {
            "reindex_vault",
            "reindex_codebase",
            "reindex_documents",
            "reindex_all",
        }:
            continue
        assert "clean" not in tool.input_schema.get("properties", {})
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True

    with _real_job_control_server(tmp_path):
        get_job_manager().begin_shutdown()
        response = asyncio.run(reindex_vault(project_root=str(project_root)))

        assert response["ok"] is True
        assert response["status"] == "queued"
        assert isinstance(response["job_id"], str)
        outcome = cast("dict[str, object]", response["outcome"])
        assert outcome["code"] == "job_created"
        job = cast("dict[str, object]", outcome["job"])
        spec = cast("dict[str, object]", job["spec"])
        initiator = cast("dict[str, object]", job["initiator"])
        assert spec == {
            "operation": "index",
            "source": "vault",
            "project_root": str(project_root),
            "mode": "incremental",
        }
        assert initiator["kind"] == "mcp"
        assert job["id"] == response["job_id"]
