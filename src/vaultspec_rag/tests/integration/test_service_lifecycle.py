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
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from vaultspec_rag.cli import (
    _is_pid_alive,
    _read_service_status,
    _spawn_service,
    _status_file,
    _terminate_pid,
    _write_service_status,
    app,
)

from ._helpers import (
    _get_ephemeral_port,
    _poll_health,
    _service_env,
    _wait_for_exit,
)

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


# -- Tests -------------------------------------------------------------------


@pytest.mark.subprocess_gpu
def test_start_health_stop(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Spawn service, verify health, terminate, verify exit."""
    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))

        health = _poll_health(port)

        assert "status" in health
        assert "cuda" in health
        assert "models_loaded" in health
        assert "uptime_s" in health
        assert "project_count" in health
        assert health["status"] == "ready"

        _terminate_pid(pid)
        assert _wait_for_exit(pid), f"PID {pid} did not exit after terminate"
        assert not _is_pid_alive(pid)


@pytest.mark.subprocess_gpu
def test_start_already_running(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Second start on the same port reports 'already in use'."""
    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _poll_health(port)

        result = runner.invoke(
            app,
            ["server", "service", "start", "--port", str(port)],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        assert "already in use" in (result.stdout or "").lower(), (
            f"Expected 'already in use' in output, got: {result.stdout!r}"
        )


@pytest.mark.subprocess_gpu
def test_stale_pid_recovery(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Service start recovers from a stale PID in the status file."""
    with _service_env(tmp_path):
        port = _get_ephemeral_port()

        # Write a stale status file with a dead PID
        status_path = tmp_path / "service.json"
        stale_data = {
            "pid": 99999,
            "port": port,
            "started_at": "2026-01-01T00:00:00+00:00",
        }
        status_path.write_text(json.dumps(stale_data), encoding="utf-8")

        # Register a defensive finalizer that reads the PID from the
        # status file at teardown time — guarantees cleanup even if
        # assertions below fail before we know the PID.
        def _cleanup_from_status() -> None:
            st = _read_service_status()
            if st is not None:
                _terminate_pid(int(st["pid"]))

        request.addfinalizer(_cleanup_from_status)

        result = runner.invoke(
            app,
            ["server", "service", "start", "--port", str(port)],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )

        # The command should have started a fresh service
        new_status = _read_service_status()
        assert new_status is not None, (
            f"Expected new status file after stale recovery, got None. "
            f"CLI output: {result.stdout!r}"
        )
        new_pid = int(new_status["pid"])
        assert new_pid != 99999
        assert _is_pid_alive(new_pid)

        health = _poll_health(port)
        assert health["status"] == "ready"


@pytest.mark.subprocess_gpu
def test_stop_when_not_running(tmp_path: Path) -> None:
    """Stopping when no service is running reports appropriately."""
    with _service_env(tmp_path):
        result = runner.invoke(
            app,
            ["server", "service", "stop"],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        output = (result.stdout or "").lower()
        assert "not running" in output or "no service status file" in output, (
            f"Expected stop message, got: {result.stdout!r}"
        )


@pytest.mark.subprocess_gpu
def test_stop_running_service(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    """Stop a running service via CLI and verify cleanup."""
    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _poll_health(port)

        _write_service_status(pid, port)

        runner.invoke(
            app,
            ["server", "service", "stop"],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )

        assert _wait_for_exit(pid), f"PID {pid} did not exit after stop"
        assert not _is_pid_alive(pid)
        assert not _status_file().exists(), "Status file should be removed after stop"


@pytest.mark.subprocess_gpu
def test_service_status_running(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """Status command shows running service details."""
    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"

        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _poll_health(port)

        _write_service_status(pid, port)

        result = runner.invoke(
            app,
            ["server", "service", "status"],
            env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
        )
        output = result.stdout or ""
        assert str(port) in output, f"Expected port {port} in output: {output!r}"
        assert "running" in output.lower(), f"Expected 'running' in output: {output!r}"


@pytest.mark.subprocess_gpu
def test_multi_project_search_isolation(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """Two projects indexed via MCP have isolated search results."""
    from vaultspec_rag.synthetic import build_multi_project_fixture

    with _service_env(tmp_path):
        port = _get_ephemeral_port()
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

        async def _mcp_call(
            test_port: int,
            tool_name: str,
            arguments: dict[str, object],
        ) -> str:
            """One MCP tool call per session (matches production pattern)."""
            from mcp.client.session import ClientSession
            from mcp.client.streamable_http import streamable_http_client
            from mcp.types import TextContent

            url = f"http://127.0.0.1:{test_port}/mcp"
            async with (
                streamable_http_client(url) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                assert not result.isError, f"{tool_name} failed: {result.content}"
                first = result.content[0]
                assert isinstance(first, TextContent)
                return first.text

        # Index both projects (one session per call)
        for m in manifests:
            try:
                asyncio.run(
                    _mcp_call(
                        port,
                        "reindex_vault",
                        {"clean": True, "project_root": str(m.root)},
                    ),
                )
            except BaseException:
                # Dump service log on failure for diagnosis
                if log_path.exists():
                    log_tail = log_path.read_text(encoding="utf-8")[-2000:]
                    pytest.fail(
                        f"reindex_vault failed for {m.root}.\n"
                        f"Service log (last 2000 chars):\n{log_tail}"
                    )
                raise

        # Search project-0 for the unique marker — must be found
        text_0 = asyncio.run(
            _mcp_call(
                port,
                "search_vault",
                {
                    "query": unique_marker,
                    "top_k": 5,
                    "project_root": str(manifests[0].root),
                },
            ),
        )
        assert unique_marker in text_0 or "isolation-probe" in text_0, (
            "Unique marker not found in project-0 results"
        )

        # Search project-1 for the same marker — must NOT appear
        text_1 = asyncio.run(
            _mcp_call(
                port,
                "search_vault",
                {
                    "query": unique_marker,
                    "top_k": 5,
                    "project_root": str(manifests[1].root),
                },
            ),
        )
        assert unique_marker not in text_1 and "isolation-probe" not in text_1, (
            f"project-0 marker leaked into project-1 results: {text_1[:500]}"
        )
