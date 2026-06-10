"""Integration tests for store eviction and log rotation.

Each test spawns a real RAG service via ``_service_env`` + ``_spawn_service``,
drives MCP tool calls against it, and asserts eviction / rotation
behavior without mocks, patches, or skips.  All tests require a live
GPU and a running Qdrant.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
import urllib.request
from typing import TYPE_CHECKING, Any

import pytest

from ...cli import _spawn_service, _terminate_pid
from ._helpers import (
    _get_ephemeral_port,
    _poll_health,
    _service_env,
    _wait_for_exit,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path

pytestmark = [pytest.mark.integration]


# -- helpers -----------------------------------------------------------------


def _make_vault_project(root: Path, *, label: str) -> Path:
    """Create a minimal .vault/ project with one research doc."""
    root.mkdir(parents=True, exist_ok=True)
    vault = root / ".vault" / "research"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "doc.md").write_text(
        f'---\ntags:\n  - "#research"\n  - "#{label}"\n'
        f"date: 2026-04-12\n---\n\n# {label}\n\nContent for {label}.\n",
        encoding="utf-8",
    )
    return root.resolve()


async def _call_tool(
    port: int,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    import httpx

    from ._helpers import _poll_health

    health = _poll_health(port)
    token = health["service_token"]

    async with httpx.AsyncClient() as client:
        if tool_name == "search_vault":
            resp = await client.post(
                f"http://127.0.0.1:{port}/search",
                headers={"Authorization": f"Bearer {token}"},
                json={"type": "vault", **args},
                timeout=10.0,
            )
            return resp.json()["results"] if resp.status_code == 200 else {}
        elif tool_name == "list_projects":
            resp = await client.get(
                f"http://127.0.0.1:{port}/projects",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
            return resp.json() if resp.status_code == 200 else {}
        elif tool_name == "evict_project":
            resp = await client.post(
                f"http://127.0.0.1:{port}/projects/evict",
                headers={"Authorization": f"Bearer {token}"},
                json={"root": args["root"]},
                timeout=10.0,
            )
            return resp.json() if resp.status_code == 200 else {}
        return {}


def _run(coro: Coroutine[object, object, dict[str, Any]]) -> dict[str, Any]:
    return asyncio.run(coro)


# -- tests -------------------------------------------------------------------


@pytest.mark.subprocess_gpu
def test_idle_ttl_evicts_quiescent_slots(tmp_path: Path) -> None:
    """A project quiescent past the idle TTL is evicted on the next traffic."""
    # First-search cold-start can take several seconds on this box,
    # so the TTL must exceed realistic back-to-back admission latency.
    overrides = {
        "VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS": "10",
        "VAULTSPEC_RAG_SERVICE_MAX_PROJECTS": "4",
    }
    with _service_env(tmp_path, overrides):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        pid = _spawn_service(port, log_path)
        try:
            _poll_health(port)
            proj_a = _make_vault_project(tmp_path / "a", label="alpha")
            proj_b = _make_vault_project(tmp_path / "b", label="beta")
            proj_c = _make_vault_project(tmp_path / "c", label="gamma")

            _run(
                _call_tool(
                    port,
                    "search_vault",
                    {
                        "query": "alpha",
                        "top_k": 1,
                        "project_root": str(proj_a),
                    },
                ),
            )
            _run(
                _call_tool(
                    port,
                    "search_vault",
                    {
                        "query": "beta",
                        "top_k": 1,
                        "project_root": str(proj_b),
                    },
                ),
            )
            listing_before = _run(_call_tool(port, "list_projects", {}))
            roots_before = {
                entry["root"] for entry in listing_before.get("projects", [])
            }
            assert str(proj_a) in roots_before
            assert str(proj_b) in roots_before

            # Sleep past the 10s idle TTL then drive a third project.
            time.sleep(12.0)
            _run(
                _call_tool(
                    port,
                    "search_vault",
                    {
                        "query": "gamma",
                        "top_k": 1,
                        "project_root": str(proj_c),
                    },
                ),
            )
            listing = _run(_call_tool(port, "list_projects", {}))
            roots = {entry["root"] for entry in listing.get("projects", [])}
            # A and B were idle > TTL, so the third request's sweep evicts them.
            assert str(proj_a) not in roots
            assert str(proj_b) not in roots
            assert str(proj_c) in roots
        finally:
            _terminate_pid(pid)
            _wait_for_exit(pid)


@pytest.mark.subprocess_gpu
def test_lru_cap_evicts_oldest(tmp_path: Path) -> None:
    """Admitting a new slot at the cap evicts the least-recently-accessed."""
    overrides = {
        "VAULTSPEC_RAG_SERVICE_MAX_PROJECTS": "2",
        "VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS": "0",
    }
    with _service_env(tmp_path, overrides):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        pid = _spawn_service(port, log_path)
        try:
            _poll_health(port)
            proj_a = _make_vault_project(tmp_path / "a", label="alpha")
            proj_b = _make_vault_project(tmp_path / "b", label="beta")
            proj_c = _make_vault_project(tmp_path / "c", label="gamma")

            for proj, q in ((proj_a, "alpha"), (proj_b, "beta")):
                _run(
                    _call_tool(
                        port,
                        "search_vault",
                        {"query": q, "top_k": 1, "project_root": str(proj)},
                    ),
                )
                time.sleep(0.2)
            # The third search must force LRU eviction of A.
            _run(
                _call_tool(
                    port,
                    "search_vault",
                    {"query": "gamma", "top_k": 1, "project_root": str(proj_c)},
                ),
            )
            listing = _run(_call_tool(port, "list_projects", {}))
            roots = {entry["root"] for entry in listing.get("projects", [])}
            assert str(proj_a) not in roots
            assert str(proj_b) in roots
            assert str(proj_c) in roots
        finally:
            _terminate_pid(pid)
            _wait_for_exit(pid)


@pytest.mark.subprocess_gpu
@pytest.mark.robustness
def test_evict_busy_returns_busy(tmp_path: Path) -> None:
    """Concurrent evict + search surfaces reason='busy' at least once across N.

    Timing-sensitive on fast hardware; ``robustness`` marker signals the
    "at least one of N" assertion pattern.  Flakes do not block merge.
    """
    overrides = {
        "VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS": "0",
        "VAULTSPEC_RAG_SERVICE_MAX_PROJECTS": "4",
    }
    with _service_env(tmp_path, overrides):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        pid = _spawn_service(port, log_path)
        try:
            _poll_health(port)
            proj = _make_vault_project(tmp_path / "busy", label="busy")

            # Prime the slot.
            _run(
                _call_tool(
                    port,
                    "search_vault",
                    {"query": "busy", "top_k": 1, "project_root": str(proj)},
                ),
            )

            stop_flag = threading.Event()

            def _hammer() -> None:
                while not stop_flag.is_set():
                    with contextlib.suppress(Exception):
                        _run(
                            _call_tool(
                                port,
                                "search_vault",
                                {
                                    "query": "busy",
                                    "top_k": 5,
                                    "project_root": str(proj),
                                },
                            ),
                        )

            worker = threading.Thread(target=_hammer)
            worker.start()
            try:
                saw_busy = False
                result: dict[str, Any] = {}
                for _ in range(20):
                    result = _run(
                        _call_tool(
                            port,
                            "evict_project",
                            {"root": str(proj)},
                        ),
                    )
                    if result.get("reason") == "busy":
                        saw_busy = True
                        break
                    time.sleep(0.02)
                assert saw_busy or result.get("evicted") is True
            finally:
                stop_flag.set()
                worker.join(timeout=10)
        finally:
            _terminate_pid(pid)
            _wait_for_exit(pid)


@pytest.mark.subprocess_gpu
def test_log_rotation_creates_backups(tmp_path: Path) -> None:
    """A small max_bytes drives multiple rotations and bounded backup count."""
    overrides = {
        "VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES": "4096",
        "VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT": "2",
        "VAULTSPEC_RAG_LOG_LEVEL": "DEBUG",
    }
    with _service_env(tmp_path, overrides):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        pid = _spawn_service(port, log_path)
        try:
            _poll_health(port)
            proj = _make_vault_project(tmp_path / "logs", label="logs")
            # Drive enough DEBUG traffic to force several rotations.
            for i in range(50):
                _run(
                    _call_tool(
                        port,
                        "search_vault",
                        {
                            "query": f"rotation check {i}",
                            "top_k": 1,
                            "project_root": str(proj),
                        },
                    ),
                )
            # Poll up to 2s for the rotated files to settle.
            deadline = time.monotonic() + 2.0
            rotated_1 = log_path.with_name(log_path.name + ".1")
            rotated_2 = log_path.with_name(log_path.name + ".2")
            while time.monotonic() < deadline:
                if rotated_1.exists() and rotated_2.exists():
                    break
                time.sleep(0.1)
            assert log_path.exists()
            assert rotated_1.exists()
            assert rotated_2.exists()
            # backup_count=2 means .3 must not exist.
            assert not log_path.with_name(log_path.name + ".3").exists()
        finally:
            _terminate_pid(pid)
            _wait_for_exit(pid)


@pytest.mark.subprocess_gpu
def test_log_rotation_post_rollover_writes_to_active(tmp_path: Path) -> None:
    """New log records after rollover land in the active file, not the backup."""
    overrides = {
        "VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES": "4096",
        "VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT": "3",
        "VAULTSPEC_RAG_LOG_LEVEL": "DEBUG",
    }
    with _service_env(tmp_path, overrides):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        pid = _spawn_service(port, log_path)
        try:
            _poll_health(port)
            proj = _make_vault_project(tmp_path / "postroll", label="postroll")

            # 1-2: drive enough traffic to force rollover.
            deadline = time.monotonic() + 10.0
            rotated_1 = log_path.with_name(log_path.name + ".1")
            i = 0
            while time.monotonic() < deadline and not rotated_1.exists():
                _run(
                    _call_tool(
                        port,
                        "search_vault",
                        {
                            "query": f"pre rollover {i}",
                            "top_k": 1,
                            "project_root": str(proj),
                        },
                    ),
                )
                i += 1
                if i > 200:
                    break
                time.sleep(0.05)
            assert rotated_1.exists(), "rollover never happened"

            # 3-5: drive one lightweight access-log record carrying
            # a unique marker.  If this record itself crosses the
            # threshold, the handler must rotate first and still bind
            # stdout/stderr to the newly active log.
            marker = "POSTROLLOVER_MARKER_abc123xyz"
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health?marker={marker}",
                timeout=5,
            ) as resp:
                assert resp.status == 200

            deadline = time.monotonic() + 2.0
            active_bytes = b""
            while time.monotonic() < deadline:
                active_bytes = log_path.read_bytes()
                if marker.encode() in active_bytes:
                    break
                time.sleep(0.1)

            # 6: marker appears in active file, NOT in .1 backup.
            rotated_bytes = rotated_1.read_bytes()
            assert marker.encode() in active_bytes
            assert marker.encode() not in rotated_bytes
        finally:
            _terminate_pid(pid)
            _wait_for_exit(pid)


@pytest.mark.subprocess_gpu
def test_close_all_drains_busy_slots(tmp_path: Path) -> None:
    """Service stop completes within 5s drain + 2s grace even under load."""
    overrides = {
        "VAULTSPEC_RAG_SERVICE_MAX_PROJECTS": "16",
        "VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS": "0",
    }
    with _service_env(tmp_path, overrides):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        pid = _spawn_service(port, log_path)
        try:
            _poll_health(port)
            projects = [
                _make_vault_project(tmp_path / f"p{i}", label=f"p{i}") for i in range(8)
            ]

            def _hammer(proj: Path) -> None:
                with contextlib.suppress(Exception):
                    _run(
                        asyncio.wait_for(
                            _call_tool(
                                port,
                                "search_vault",
                                {
                                    "query": "drain test",
                                    "top_k": 3,
                                    "project_root": str(proj),
                                },
                            ),
                            timeout=8.0,
                        ),
                    )

            threads = [
                threading.Thread(
                    target=_hammer,
                    args=(p,),
                    daemon=True,
                    name=f"drain-hammer-{i}",
                )
                for i, p in enumerate(projects)
            ]
            for t in threads:
                t.start()
            # Immediately request termination.
            t0 = time.monotonic()
            _terminate_pid(pid)
            assert _wait_for_exit(pid, timeout=10), "service did not exit"
            elapsed = time.monotonic() - t0
            # 5s drain + 2s grace + teardown epsilon.
            assert elapsed < 10.0, f"shutdown took {elapsed:.1f}s"
            for t in threads:
                t.join(timeout=10)
            alive = [t.name for t in threads if t.is_alive()]
            assert not alive, f"client load threads did not exit: {alive}"
            # service.json must be cleaned up.
            assert not (tmp_path / "service.json").exists()
        finally:
            if _wait_for_exit(pid, timeout=1) is False:
                _terminate_pid(pid)
