"""Integration tests for service daemon lifecycle.

Exercises real subprocess spawning, real GPU model loading, and real
Qdrant operations.  No mocks, patches, stubs, or skips.

Closes TESTGAP-001 (_terminate_pid), TESTGAP-002 (_spawn_service),
TESTGAP-003 (service_start), TESTGAP-004 (service_stop happy path),
TESTGAP-005 (service_status running), TESTGAP-009 (multi-project MCP).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..._process_probe import pid_alive
from ...cli import app
from ...cli._process import _spawn_service, _terminate_pid
from ...cli._service_status import (
    _status_file,
    _write_service_status,
    read_service_status,
)
from .._ports import free_loopback_port
from ._helpers import (
    _poll_health,
    _service_env,
    _wait_for_exit,
)
from ._service_lifecycle_helpers import (
    _assert_interrupted_after_release,
    _assert_shutdown_log_order,
    _job_owns_full_pipeline,
    _signal_service_shutdown,
    _signalable_live_service,
    _wait_for_listeners_closed,
    _wait_for_persisted_job,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ...synthetic import CorpusManifest


runner = CliRunner()

pytestmark = [pytest.mark.integration]


async def _mcp_session_call(
    test_port: int,
    tool_name: str,
    arguments: dict[str, object],
) -> str:
    """Issue one real service request in the same one-call MCP session shape."""
    import httpx

    health = _poll_health(test_port)
    token = health["service_token"]
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        if tool_name == "reindex_vault":
            response = await client.post(
                f"http://127.0.0.1:{test_port}/reindex",
                headers=headers,
                json={"type": "vault", **arguments},
                timeout=30.0,
            )
            assert response.status_code == 200, f"reindex_vault failed: {response.text}"
            return response.text
        if tool_name == "search_vault":
            response = await client.post(
                f"http://127.0.0.1:{test_port}/search",
                headers=headers,
                json={"type": "vault", **arguments},
                timeout=30.0,
            )
            assert response.status_code == 200, f"search_vault failed: {response.text}"
            return json.dumps(response.json()["results"])
        if tool_name == "get_jobs":
            response = await client.get(
                f"http://127.0.0.1:{test_port}/jobs",
                headers=headers,
                params={"limit": int(str(arguments.get("limit", 50)))},
                timeout=30.0,
            )
            assert response.status_code == 200, f"get_jobs failed: {response.text}"
            return response.text
    raise ValueError(f"Unknown tool_name: {tool_name}")


def _index_isolation_projects(
    port: int,
    manifests: list[CorpusManifest],
    log_path: Path,
) -> None:
    """Index both real projects and include daemon output if either fails."""
    for manifest in manifests:
        try:
            response = json.loads(
                asyncio.run(
                    _mcp_session_call(
                        port,
                        "reindex_vault",
                        {"clean": True, "project_root": str(manifest.root)},
                    )
                )
            )
            assert response.get("ok") is True
            job_id = response.get("job_id")
            assert job_id is not None
            for _ in range(100):
                jobs_data = json.loads(
                    asyncio.run(_mcp_session_call(port, "get_jobs", {"limit": 50}))
                )
                jobs = jobs_data.get("jobs", [])
                matched = [job for job in jobs if job.get("id") == job_id]
                if matched and matched[0].get("phase") in {"done", "error", "failed"}:
                    break
                time.sleep(0.1)
        except BaseException:
            if log_path.exists():
                log_tail = log_path.read_text(encoding="utf-8")[-2000:]
                pytest.fail(
                    f"reindex_vault failed for {manifest.root}.\n"
                    f"Service log (last 2000 chars):\n{log_tail}"
                )
            raise


def _assert_isolation_search_results(
    port: int,
    manifests: list[CorpusManifest],
    unique_marker: str,
) -> None:
    """Prove the real marker is present only in the project that owns it."""
    text_0 = asyncio.run(
        _mcp_session_call(
            port,
            "search_vault",
            {
                "query": unique_marker,
                "top_k": 5,
                "project_root": str(manifests[0].root),
            },
        )
    )
    assert unique_marker in text_0 or "isolation-probe" in text_0, (
        "Unique marker not found in project-0 results"
    )
    text_1 = asyncio.run(
        _mcp_session_call(
            port,
            "search_vault",
            {
                "query": unique_marker,
                "top_k": 5,
                "project_root": str(manifests[1].root),
            },
        )
    )
    assert unique_marker not in text_1 and "isolation-probe" not in text_1, (
        f"project-0 marker leaked into project-1 results: {text_1[:500]}"
    )


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_start_health_stop(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Spawn service, verify health, terminate, verify exit."""
    with _service_env(tmp_path):
        port = free_loopback_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))

        health = _poll_health(port)

        assert "status" in health
        assert "cuda" in health
        assert "models_loaded" in health
        assert "reranker_loaded" in health
        assert "uptime_s" in health
        assert "project_count" in health
        assert health["status"] == "ready"
        assert health["reranker_loaded"] is True
        assert health["project_count"] == 0

        _terminate_pid(pid)
        assert _wait_for_exit(pid), f"PID {pid} did not exit after terminate"
        assert not pid_alive(pid)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
@pytest.mark.timeout(600)
def test_daemon_restart_restores_queued_work_and_preserves_paused_intent(
    tmp_path: Path,
    required_host_provisioned_qdrant_source: tuple[Path, Path],
) -> None:
    """Two real daemon lives retain exact durable queued and paused intent."""
    from ...job_manager.manager import JobManager
    from ...job_models import (
        DesiredJobState,
        JobInitiator,
        JobMode,
        JobOperation,
        JobSource,
        JobSpec,
        JobState,
    )
    from ...service_quiesce import ServiceQuiesceController
    from ...synthetic import build_synthetic_vault

    queued_root = tmp_path / "queued-vault"
    paused_root = tmp_path / "paused-vault"
    build_synthetic_vault(queued_root, n_docs=24, seed=2201)
    paused_root.mkdir()
    state_path = tmp_path / "jobs-state.json"
    seed_manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        state_path=state_path,
    )
    queued = seed_manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            str(queued_root.resolve()),
            JobMode.INCREMENTAL,
        ),
        JobInitiator("integration", "restart queued probe", str(queued_root)),
    )
    paused = seed_manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.VAULT,
            str(paused_root.resolve()),
            JobMode.INCREMENTAL,
        ),
        JobInitiator("integration", "restart paused probe", str(paused_root)),
        start_paused=True,
    )
    assert queued.job is not None
    assert paused.job is not None
    queued_id = queued.job.id
    paused_id = paused.job.id

    with _signalable_live_service(tmp_path, required_host_provisioned_qdrant_source):
        completed = _wait_for_persisted_job(
            state_path,
            queued_id,
            lambda job: job.state is JobState.SUCCEEDED,
            "restored queued intent did not execute",
        )
        dormant = _wait_for_persisted_job(
            state_path,
            paused_id,
            lambda job: job.state is JobState.PAUSED,
            "paused intent was not retained",
        )
        assert completed.attempt.number == 1
        assert completed.desired_state is DesiredJobState.RUNNING
        assert dormant.attempt.number == 1
        assert dormant.desired_state is DesiredJobState.PAUSED
        assert dormant.runtime.task_active is False
        assert dormant.runtime.worker_active is False

    stopped_paused = _wait_for_persisted_job(
        state_path,
        paused_id,
        lambda job: job.state is JobState.PAUSED,
        "clean shutdown did not preserve paused intent",
    )
    assert stopped_paused.desired_state is DesiredJobState.PAUSED

    with _signalable_live_service(tmp_path, required_host_provisioned_qdrant_source):
        restored_paused = _wait_for_persisted_job(
            state_path,
            paused_id,
            lambda job: job.state is JobState.PAUSED,
            "second daemon life did not restore paused intent",
        )
        restored_completed = _wait_for_persisted_job(
            state_path,
            queued_id,
            lambda job: job.state is JobState.SUCCEEDED,
            "completed queued work was lost on the second daemon life",
        )
        assert restored_paused.id == paused_id
        assert restored_paused.attempt.number == 1
        assert restored_paused.desired_state is DesiredJobState.PAUSED
        assert restored_paused.runtime.task_active is False
        assert restored_completed.id == queued_id
        assert restored_completed.attempt.number == 1

    output = (tmp_path / "service.log").read_text(encoding="utf-8", errors="replace")
    assert all(
        marker in output
        for marker in (
            "Canonical job manager ready: bound=2 dispatched=1",
            "Canonical job manager ready: bound=1 dispatched=0",
        )
    )


@pytest.mark.integration
@pytest.mark.subprocess_gpu
@pytest.mark.timeout(600)
def test_shutdown_interrupts_only_after_worker_release_then_reopens_store(
    tmp_path: Path,
    required_host_provisioned_qdrant_source: tuple[Path, Path],
) -> None:
    """Graceful daemon stop releases every owner before store teardown."""
    import httpx

    from ...job_models import JobState

    root = tmp_path / "live-code"
    source_dir = root / "src"
    source_dir.mkdir(parents=True)
    (root / ".vault").mkdir()
    for ordinal in range(512):
        (source_dir / f"shutdown_probe_{ordinal:04d}.py").write_text(
            f"def shutdown_probe_{ordinal:04d}() -> str:\n"
            f"    return 'worker release probe {ordinal:04d}'\n",
            encoding="utf-8",
        )

    state_path = tmp_path / "jobs-state.json"
    with _signalable_live_service(
        tmp_path,
        required_host_provisioned_qdrant_source,
    ) as (port, shutdown_pid):
        health = _poll_health(port)
        service_pid = int(health["pid"])
        status = read_service_status()
        assert status is not None
        qdrant_pid = int(status["qdrant_pid"])
        qdrant_port = int(status["qdrant_port"])
        response = httpx.post(
            f"http://127.0.0.1:{port}/reindex",
            headers={"Authorization": f"Bearer {health['service_token']}"},
            json={
                "type": "code",
                "clean": False,
                "project_root": str(root),
            },
            timeout=30.0,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["ok"] is True
        job_id = str(payload["job_id"])

        live = _wait_for_persisted_job(
            state_path,
            job_id,
            _job_owns_full_pipeline,
            "real code attempt never published complete worker ownership",
        )
        assert live.resources.started is not None
        assert live.resources.finished is None

        _signal_service_shutdown(shutdown_pid)
        interrupted = _wait_for_persisted_job(
            state_path,
            job_id,
            lambda job: job.state is JobState.INTERRUPTED,
            "shutdown-signalled attempt did not become interrupted",
        )
        _assert_interrupted_after_release(interrupted)

        assert _wait_for_exit(service_pid, timeout=90.0)
        assert _wait_for_exit(qdrant_pid, timeout=30.0)
        assert _wait_for_listeners_closed(port, qdrant_port, timeout=30.0)

    output = (tmp_path / "service.log").read_text(encoding="utf-8", errors="replace")
    _assert_shutdown_log_order(output, job_id=job_id, qdrant_pid=qdrant_pid)

    with _signalable_live_service(
        tmp_path,
        required_host_provisioned_qdrant_source,
    ) as (restart_port, _shutdown_pid):
        restarted_health = _poll_health(restart_port)
        restarted_status = read_service_status()
        assert restarted_status is not None
        assert int(restarted_status["qdrant_pid"]) != qdrant_pid
        restored = _wait_for_persisted_job(
            state_path,
            job_id,
            lambda job: job.state is JobState.INTERRUPTED,
            "interrupted result was not retained after daemon restart",
        )
        assert restored.runtime.task_active is False
        search = httpx.post(
            f"http://127.0.0.1:{restart_port}/search",
            headers={"Authorization": f"Bearer {restarted_health['service_token']}"},
            json={
                "type": "code",
                "query": "worker release probe",
                "top_k": 1,
                "project_root": str(root),
            },
            timeout=30.0,
        )
        assert search.status_code == 200, search.text


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_start_already_running(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Second start on the same port reports 'already in use'."""
    with _service_env(tmp_path):
        port = free_loopback_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _poll_health(port)

        result = runner.invoke(
            app,
            ["server", "start", "--port", str(port)],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        assert "already running" in (result.stdout or "").lower(), (
            f"Expected 'already running' in output, got: {result.stdout!r}"
        )


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_stale_pid_recovery(tmp_path: Path) -> None:
    """Service start recovers from a stale PID in the status file."""
    with _service_env(tmp_path):
        port = free_loopback_port()

        # Write a stale status file with a dead PID
        status_path = tmp_path / "service.json"
        stale_data = {
            "pid": 99999,
            "port": port,
            "started_at": "2026-01-01T00:00:00+00:00",
        }
        status_path.write_text(json.dumps(stale_data), encoding="utf-8")

        try:
            result2 = runner.invoke(
                app,
                ["server", "start", "--port", str(port)],
                env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
            )

            # The command should have started a fresh service
            new_status = read_service_status()
            assert new_status is not None, (
                f"Expected new status file after stale recovery, got None. "
                f"CLI output: {result2.stdout!r}"
            )
            new_pid = int(new_status["pid"])
            assert new_pid != 99999
            assert pid_alive(new_pid)

            health = _poll_health(port)
            assert health["status"] == "ready"
        finally:
            status = read_service_status()
            if status is not None:
                pid = int(status["pid"])
                _terminate_pid(pid)
                _wait_for_exit(pid)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_stop_when_not_running(tmp_path: Path) -> None:
    """Stopping when no service is running reports appropriately."""
    with _service_env(tmp_path):
        result = runner.invoke(
            app,
            ["server", "stop"],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        output = (result.stdout or "").lower()
        assert "not running" in output or "no service status file" in output, (
            f"Expected stop message, got: {result.stdout!r}"
        )


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_stop_running_service(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Stop a running service via CLI and verify cleanup."""
    with _service_env(tmp_path):
        port = free_loopback_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _poll_health(port)

        _write_service_status(pid, port)

        runner.invoke(
            app,
            ["server", "stop"],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )

        assert _wait_for_exit(pid), f"PID {pid} did not exit after stop"
        assert not pid_alive(pid)
        assert not _status_file().exists(), "Status file should be removed after stop"


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_stop_running_service_by_port_without_status_file(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """``server stop --port`` stops a running daemon with no status file (F7).

    The status file is keyed per status dir and can diverge from (or be missing
    for) the running instance, so a non-default-port service was unstoppable by
    the verb. With ``--port`` the daemon's own /health identity resolves the
    serving pid and stop succeeds without ever reading the status file.
    """
    with _service_env(tmp_path):
        port = free_loopback_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        health = _poll_health(port)
        serving_pid = int(health["pid"])

        # The daemon now publishes before the parent. Remove that authoritative
        # file to recreate the case where discovery is absent even though the
        # daemon is genuinely running.
        _status_file().unlink()
        assert not _status_file().exists()

        result = runner.invoke(
            app,
            ["server", "stop", "--port", str(port)],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        assert "no such option" not in (result.stdout or "").lower()
        assert _wait_for_exit(serving_pid), (
            f"serving PID {serving_pid} did not exit after stop --port"
        )
        assert not pid_alive(serving_pid)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_service_status_running(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """Status command shows running service details."""
    with _service_env(tmp_path):
        port = free_loopback_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        # Write service.json BEFORE the daemon finishes starting, mirroring
        # the production `service start` ordering (spawn -> write -> wait).
        # The daemon's initial heartbeat tick (fired after model load, inside
        # the lifespan) then finds the file and writes ``last_heartbeat``,
        # so status reports "running" rather than "crashed (heartbeat stale)".
        _write_service_status(pid, port)
        health = _poll_health(port)
        serving_pid = int(health["pid"])
        assert serving_pid > 0

        # Poll status until the daemon's heartbeat lands (the initial tick
        # races with model load); the loop heartbeat interval is 15s, so allow
        # margin. This asserts the steady-state "running", not a startup blip.
        deadline = time.monotonic() + 30.0
        output = ""
        while time.monotonic() < deadline:
            result2 = runner.invoke(
                app,
                ["server", "status"],
                env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
            )
            output = result2.stdout or ""
            if "running" in output.lower():
                break
            time.sleep(1.0)
        assert str(port) in output, f"Expected port {port} in output: {output!r}"
        assert "running" in output.lower(), f"Expected 'running' in output: {output!r}"

        json_result = runner.invoke(
            app,
            ["server", "status", "--json"],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        assert json_result.exit_code == 0
        payload = json.loads(json_result.stdout)
        data = payload["data"]
        assert data["state"] == "running"
        assert data["pid"] == serving_pid
        assert data["pid"] != pid or data["health"].get("parent_pid") == pid
        operational = data["operational"]
        assert operational["jobs"]["available"] is True
        assert "next_action" in operational


@pytest.mark.integration
@pytest.mark.subprocess_gpu
def test_multi_project_search_isolation(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """Two projects indexed via MCP have isolated search results."""
    from ...synthetic import build_multi_project_fixture

    with _service_env(tmp_path):
        port = free_loopback_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _poll_health(port)

        manifests = build_multi_project_fixture(
            tmp_path / "projects",
            n_projects=2,
            docs_per_project=6,
            seed=42,
        )

        # Inject a unique marker into project-0 only so we can
        # distinguish its search results from project-1.
        unique_marker = "XYZZY_ISOLATION_MARKER_PROJECT_ZERO"
        marker_doc = manifests[0].root / ".vault" / "adr" / "isolation-probe.md"
        marker_doc.write_text(
            '---\ntags:\n  - "#adr"\n  - "#isolation"\n'
            "date: 2026-01-01\nrelated:\n  []\n---\n\n"
            f"# isolation probe\n\n{unique_marker}\n",
            encoding="utf-8",
        )

        _index_isolation_projects(port, manifests, log_path)
        _assert_isolation_search_results(port, manifests, unique_marker)
