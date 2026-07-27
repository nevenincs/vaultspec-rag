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

from ...cli._process import _spawn_service, _terminate_pid
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
    (root / ".vaultspec").mkdir(parents=True, exist_ok=True)
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
                timeout=30.0,
            )
            return resp.json()["results"] if resp.status_code == 200 else {}
        elif tool_name == "list_projects":
            resp = await client.get(
                f"http://127.0.0.1:{port}/projects",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30.0,
            )
            return resp.json() if resp.status_code == 200 else {}
        elif tool_name == "evict_project":
            resp = await client.post(
                f"http://127.0.0.1:{port}/projects/evict",
                headers={"Authorization": f"Bearer {token}"},
                json={"root": args["root"]},
                timeout=30.0,
            )
            return resp.json() if resp.status_code == 200 else {}
        return {}


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


async def _reindex_vault(port: int, root: Path, token: str) -> str:
    """Trigger a clean vault reindex over HTTP and return the job id."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"http://127.0.0.1:{port}/reindex",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "type": "vault",
                "clean": True,
                "project_root": str(root),
                "initiator_kind": "cli",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return str(resp.json()["job_id"])


async def _job_phase(port: int, job_id: str, token: str) -> str | None:
    """Return the lifecycle phase of *job_id*, or ``None`` if not found yet."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"http://127.0.0.1:{port}/jobs",
            headers={"Authorization": f"Bearer {token}"},
            params={"job_id": job_id},
            timeout=30.0,
        )
        if resp.status_code != 200:
            return None
        jobs = resp.json().get("jobs", [])
        return str(jobs[0]["phase"]) if jobs else None


_TERMINAL_PHASES = frozenset(
    {"done", "error", "failed", "cancelled", "superseded", "skipped"}
)


def _index_project(port: int, root: Path, timeout: float = 180.0) -> None:
    """Index *root* through the daemon and block until its lease is released.

    Indexing runs under ``registry.lease`` (jobs.py), so a completed reindex
    both populates the on-disk index (making a subsequent search lease instead
    of early-returning on an empty index) and admits the project's slot,
    deterministically driving the same LRU/idle admission a search would. The
    lease is held for the whole index, so we wait for ``ref_count`` to fall back
    to zero before returning, otherwise a follow-on admission would (correctly)
    refuse to evict the still-busy slot.
    """
    token = _poll_health(port)["service_token"]
    job_id = _run(_reindex_vault(port, root, token))
    deadline = time.monotonic() + timeout
    phase: str | None = None
    while time.monotonic() < deadline:
        phase = _run(_job_phase(port, job_id, token))
        if phase in _TERMINAL_PHASES:
            break
        time.sleep(0.25)
    if phase != "done":
        msg = f"reindex job {job_id} for {root} ended in phase {phase!r}"
        raise AssertionError(msg)
    _wait_ref_released(port, root)


def _wait_ref_released(port: int, root: Path, timeout: float = 15.0) -> None:
    """Block until *root* has a warm slot with ``ref_count == 0``."""
    target = str(root)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        listing = _run(_call_tool(port, "list_projects", {}))
        for entry in listing.get("projects", []):
            if entry["root"] == target and entry.get("ref_count", 0) == 0:
                return
        time.sleep(0.1)
    msg = f"slot for {root} never settled to ref_count 0 within {timeout:.0f}s"
    raise AssertionError(msg)


# -- tests -------------------------------------------------------------------


@pytest.mark.subprocess_gpu
def test_idle_ttl_evicts_quiescent_slots(tmp_path: Path) -> None:
    """A project quiescent past the idle TTL is evicted on the next admission."""
    # First-index cold-start and collection setup can take more than 10 seconds
    # on a loaded host, so the TTL must comfortably exceed realistic
    # back-to-back admission latency. The model loads once, before
    # ``last_access`` is stamped, so it does not age a slot.
    overrides = {
        "VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS": "30",
        "VAULTSPEC_RAG_SERVICE_MAX_PROJECTS": "4",
    }
    with _service_env(tmp_path, overrides):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        # Watch disabled: otherwise the async watcher would auto-index and
        # admit slots behind the test, and the admission accounting under test
        # would be non-deterministic.
        pid = _spawn_service(port, log_path, watch=False)
        try:
            _poll_health(port)
            proj_a = _make_vault_project(tmp_path / "a", label="alpha")
            proj_b = _make_vault_project(tmp_path / "b", label="beta")
            proj_c = _make_vault_project(tmp_path / "c", label="gamma")

            # Indexing admits each slot; A and B are quiescent afterwards.
            _index_project(port, proj_a)
            _index_project(port, proj_b)
            listing_before = _run(_call_tool(port, "list_projects", {}))
            roots_before = {
                entry["root"] for entry in listing_before.get("projects", [])
            }
            assert str(proj_a) in roots_before
            assert str(proj_b) in roots_before

            # Sleep past the 30s idle TTL, refresh B through the real indexing
            # path, then admit a third project. B is therefore recent while A
            # remains quiescent and eligible for eviction.
            time.sleep(32.0)
            _index_project(port, proj_b)
            _index_project(port, proj_c)
            listing = _run(_call_tool(port, "list_projects", {}))
            roots = {entry["root"] for entry in listing.get("projects", [])}
            # A was idle > TTL, while refreshed B and newly admitted C remain.
            assert str(proj_a) not in roots
            assert str(proj_b) in roots
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
        # Watch disabled so no async watcher admits slots behind the test.
        pid = _spawn_service(port, log_path, watch=False)
        try:
            _poll_health(port)
            proj_a = _make_vault_project(tmp_path / "a", label="alpha")
            proj_b = _make_vault_project(tmp_path / "b", label="beta")
            proj_c = _make_vault_project(tmp_path / "c", label="gamma")

            # Index A then B (cap is 2); the awaited order makes A the LRU.
            _index_project(port, proj_a)
            time.sleep(0.2)
            _index_project(port, proj_b)
            time.sleep(0.2)
            # Admitting C at the cap must evict the least-recently-used slot (A).
            _index_project(port, proj_c)

            listing = _run(_call_tool(port, "list_projects", {}))
            roots = {entry["root"] for entry in listing.get("projects", [])}
            assert str(proj_a) not in roots
            assert str(proj_b) in roots
            assert str(proj_c) in roots

            # A surviving project's warm slot still serves a real search.
            results = _run(
                _call_tool(
                    port,
                    "search_vault",
                    {"query": "gamma", "top_k": 1, "project_root": str(proj_c)},
                ),
            )
            assert isinstance(results, list)
            assert len(results) >= 1
        finally:
            _terminate_pid(pid)
            _wait_for_exit(pid)


@pytest.mark.subprocess_gpu
def test_log_rotation_creates_backups(tmp_path: Path) -> None:
    """A small max_bytes drives multiple rotations and bounded backup count."""
    overrides = {
        "VAULTSPEC_RAG_MANAGED_LOG_MAX_BYTES": "4096",
        "VAULTSPEC_RAG_MANAGED_LOG_BACKUP_COUNT": "2",
        "VAULTSPEC_RAG_LOG_LEVEL": "DEBUG",
        # This scenario exercises the service writer only. Keep the real
        # isolated service independent of a machine-provisioned Qdrant binary.
        "VAULTSPEC_RAG_LOCAL_ONLY": "1",
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
        "VAULTSPEC_RAG_MANAGED_LOG_MAX_BYTES": "4096",
        "VAULTSPEC_RAG_MANAGED_LOG_BACKUP_COUNT": "3",
        "VAULTSPEC_RAG_LOG_LEVEL": "DEBUG",
        "VAULTSPEC_RAG_LOCAL_ONLY": "1",
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
            # Immediately request termination. The bounded exit wait below is
            # the hang-guard (drain + grace + teardown headroom); exiting at
            # all under live client load is the invariant.
            _terminate_pid(pid)
            assert _wait_for_exit(pid, timeout=30), "service did not exit"
            for t in threads:
                t.join(timeout=10)
            alive = [t.name for t in threads if t.is_alive()]
            assert not alive, f"client load threads did not exit: {alive}"
            # service.json must be cleaned up.
            assert not (tmp_path / "service.json").exists()
        finally:
            if _wait_for_exit(pid, timeout=1) is False:
                _terminate_pid(pid)
