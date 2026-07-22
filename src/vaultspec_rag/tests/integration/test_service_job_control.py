"""Real-server coverage for typed service job-control transport operations."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import uvicorn
from starlette.applications import Starlette
from typer.testing import CliRunner

import vaultspec_rag.server as _server_state

from ...cli import app
from ...config import EnvVar, reset_config
from ...job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec
from ...jobs import get_job_manager
from ...jobs import reset as reset_jobs
from ...mcp._mcp import mcp
from ...mcp._tools import reindex_vault
from ...server._routes import ROUTES
from ...serviceclient import (
    _try_http_create_job,
    _try_http_delete_job,
    _try_http_get_job,
    _try_http_retry_job,
    _try_http_set_job_desired_state,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

runner = CliRunner()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _real_job_control_server(tmp_path: Path) -> Generator[int]:
    """Run the production route table over a real loopback HTTP socket."""
    status_dir = tmp_path / "status"
    port = _free_port()
    token = "real-job-control-token"
    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    prior_watch_enabled = os.environ.get(EnvVar.WATCH_ENABLED)
    prior_token = _server_state._SERVICE_TOKEN
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    stopped = True
    try:
        status_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.WATCH_ENABLED] = "false"
        reset_config()
        reset_jobs()
        _server_state._SERVICE_TOKEN = token
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

        server = uvicorn.Server(
            uvicorn.Config(
                Starlette(routes=ROUTES),
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
        _server_state._SERVICE_TOKEN = prior_token
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


def test_typed_job_control_transport_uses_real_http_methods_and_conflicts(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    (project_root / ".vault").mkdir(parents=True)

    with _real_job_control_server(tmp_path) as port:
        created = _try_http_create_job(
            "vault",
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
        job_id = cast("str", created_job["id"])
        revision = cast("int", created_job["revision"])
        assert created_job["state"] == "paused"

        detail = _try_http_get_job(job_id, port, timeout=5.0)
        assert detail is not None
        assert detail["ok"] is True
        detail_job = cast("dict[str, object]", detail["job"])
        assert detail_job["id"] == job_id
        assert detail_job["desired_state"] == "paused"

        force_rejected = _try_http_set_job_desired_state(
            job_id,
            "running",
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

        cancelled = _try_http_set_job_desired_state(
            job_id,
            "cancelled",
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


def test_human_cli_job_controls_resolve_unique_prefixes_before_exact_mutation(
    tmp_path: Path,
) -> None:
    first_id = "abcdef01-0000-4000-8000-000000000001"
    second_id = "abcdef02-0000-4000-8000-000000000002"

    with _real_job_control_server(tmp_path) as port:
        _seed_paused_job(tmp_path / "first", first_id)
        _seed_paused_job(tmp_path / "second", second_id)
        port_arg = str(port)

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

        deleted = runner.invoke(
            app,
            ["server", "job", "delete", "abcdef01", "--port", port_arg],
        )
        assert deleted.exit_code == 0, deleted.output
        assert "Outcome: job_deleted" in deleted.stdout


def test_json_cli_job_controls_use_full_ids_and_one_stable_outcome(
    tmp_path: Path,
) -> None:
    job_id = "12345678-0000-4000-8000-000000000001"

    with _real_job_control_server(tmp_path) as port:
        _seed_paused_job(tmp_path / "json", job_id)
        port_arg = str(port)

        exit_code, shown = _invoke_job_json(
            "show",
            job_id,
            "--port",
            port_arg,
        )
        assert exit_code == 0
        assert shown["ok"] is True
        shown_data = cast("dict[str, object]", shown["data"])
        shown_job = cast("dict[str, object]", shown_data["job"])
        assert shown_job["id"] == job_id

        exit_code, prefix_rejected = _invoke_job_json(
            "show",
            "12345678",
            "--port",
            port_arg,
        )
        assert exit_code == 1
        assert prefix_rejected["ok"] is False
        assert prefix_rejected["error"] == "job_not_found"

        exit_code, force_rejected = _invoke_job_json(
            "stop",
            job_id,
            "--port",
            port_arg,
            "--force",
        )
        assert exit_code == 1
        assert force_rejected["ok"] is False
        assert force_rejected["error"] == "force_termination_unavailable"

        exit_code, stopped = _invoke_job_json(
            "stop",
            job_id,
            "--port",
            port_arg,
        )
        assert exit_code == 0
        assert stopped["ok"] is True
        stopped_data = cast("dict[str, object]", stopped["data"])
        assert stopped_data["status"] == "job_cancelled"
        stopped_job = cast("dict[str, object]", stopped_data["job"])
        assert stopped_job["state"] == "cancelled"

        exit_code, replayed = _invoke_job_json(
            "stop",
            job_id,
            "--port",
            port_arg,
        )
        assert exit_code == 0
        assert replayed["ok"] is True
        replayed_data = cast("dict[str, object]", replayed["data"])
        assert replayed_data["status"] == "already_satisfied"

        exit_code, deleted = _invoke_job_json(
            "delete",
            job_id,
            "--port",
            port_arg,
        )
        assert exit_code == 0
        assert deleted["ok"] is True
        deleted_data = cast("dict[str, object]", deleted["data"])
        assert deleted_data["status"] == "job_deleted"

        exit_code, missing = _invoke_job_json(
            "delete",
            job_id,
            "--port",
            port_arg,
        )
        assert exit_code == 1
        assert missing["ok"] is False
        assert missing["error"] == "job_not_found"


def test_reindex_compatibility_keeps_mcp_incremental_refresh_only(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "mcp-refresh"
    (project_root / ".vault").mkdir(parents=True)

    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "search_vault",
        "search_codebase",
        "get_code_file",
        "reindex_vault",
        "reindex_codebase",
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
        if tool.name not in {"reindex_vault", "reindex_codebase"}:
            continue
        assert "clean" not in tool.inputSchema.get("properties", {})
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True

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
