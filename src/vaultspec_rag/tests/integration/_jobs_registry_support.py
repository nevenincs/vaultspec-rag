"""Tests for the in-flight activity registry (#142).

Two layers, no mocks/skips/monkeypatch:

- Unit-style: drive ``_jobs.record_start`` / ``record_finish`` / ``snapshot``
  directly to assert the record schema, the bounded ring-buffer behaviour, and
  thread-safety under real concurrent writers.
- Integration (GPU): call the real ``reindex_vault`` / ``reindex_codebase``
  MCP tools against a real indexed workspace (reusing the session-scoped
  ``embedding_model`` fixture and the global-registry pattern from
  ``test_watcher_control.py``) and assert a finished ``trigger="tool"`` entry
  lands in the snapshot.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, cast

import pytest

from ... import jobs as _jobs
from ... import server
from ...serviceclient._discovery import _default_service_port
from ...serviceclient._transport import _try_http_admin

if TYPE_CHECKING:
    from collections.abc import Iterator

# Match the real service-job deadline used by storage survey integration. This
# is deliberately separate from the 30-second timeout for one admin HTTP call.
_JOB_COMPLETION_TIMEOUT_SECONDS = 120.0
_JOB_POLL_INTERVAL_SECONDS = 0.1
_TERMINAL_JOB_PHASES = frozenset({"done", "error", "failed"})


@pytest.fixture
def _clean_jobs(  # pyright: ignore[reportUnusedFunction]
) -> Iterator[None]:
    """Reset the registry before/after each test and stop any watcher.

    The reindex tools start a filesystem watcher via ``_ensure_watcher``
    as a side effect; stop them on teardown so the GPU integration tests
    do not leak watcher tasks across the session (mirrors
    ``test_watcher_control.py``).
    """
    _jobs.reset()
    yield
    server._stop_all_watchers()
    _jobs.reset()


async def wait_for_terminal_job(
    job_id: str,
    *,
    timeout: float = _JOB_COMPLETION_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Wait within the established real service-job completion budget."""
    deadline = time.monotonic() + timeout
    last_response: dict[str, object] = {}
    last_job: dict[str, object] | None = None
    port = _default_service_port()
    assert port is not None, f"service port unavailable while waiting for job {job_id}"

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(
                f"job {job_id} did not reach a terminal phase within {timeout:g}s; "
                f"last_job={last_job!r}; last_response={last_response!r}"
            )

        response = await asyncio.to_thread(
            _try_http_admin,
            "get_jobs",
            {"job_id": job_id},
            port,
            timeout=remaining,
        )
        last_response = response or {}
        raw_jobs = last_response.get("jobs", [])
        jobs = cast("list[dict[str, object]]", raw_jobs)
        last_job = next((job for job in jobs if job.get("id") == job_id), None)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(
                f"job {job_id} did not reach a terminal phase within {timeout:g}s; "
                f"last_job={last_job!r}; last_response={last_response!r}"
            )
        if last_job is not None and last_job.get("phase") in _TERMINAL_JOB_PHASES:
            return last_job

        await asyncio.sleep(min(_JOB_POLL_INTERVAL_SECONDS, remaining))


def _assert_runtime_context(raw: object) -> dict[str, object]:
    assert isinstance(raw, dict)
    runtime = cast("dict[str, object]", raw)
    assert isinstance(runtime["pid"], int)
    assert isinstance(runtime["parent_pid"], int)
    assert isinstance(runtime["user"], str)
    assert isinstance(runtime["executable"], str)
    assert isinstance(runtime["prefix"], str)
    assert isinstance(runtime["base_prefix"], str)
    return runtime


def _assert_resource_snapshot(raw: object) -> dict[str, object]:
    assert isinstance(raw, dict)
    resources = cast("dict[str, object]", raw)
    assert isinstance(resources["rss_mb"], float)
    assert isinstance(resources["cuda_allocated_mb"], float)
    assert isinstance(resources["cuda_reserved_mb"], float)
    return resources


def assert_running_job_snapshot(entry: dict[str, object], job_id: str) -> None:
    assert entry["id"] == job_id
    assert entry["source"] == "vault"
    assert entry["trigger"] == "tool"
    assert entry["phase"] == "running"
    assert isinstance(entry["started_at"], float)
    assert entry["finished_at"] is None
    assert entry["result"] is None
    _assert_runtime_context(entry["runtime"])
    resources = _assert_resources(entry)
    _assert_resource_snapshot(resources["started"])
    assert resources["finished"] is None


def assert_done_job_snapshot(entry: dict[str, object], job_id: str) -> None:
    assert entry["id"] == job_id
    assert entry["phase"] == "done"
    finished_at = entry["finished_at"]
    started_at = entry["started_at"]
    assert isinstance(finished_at, float)
    assert isinstance(started_at, float)
    assert finished_at >= started_at
    assert entry["result"] == "+1 /0 -0 (5ms)"
    assert isinstance(_assert_resources(entry)["finished"], dict)


def _assert_resources(entry: dict[str, object]) -> dict[str, object]:
    resources = entry["resources"]
    assert isinstance(resources, dict)
    return cast("dict[str, object]", resources)


# --------------------------------------------------------------------------- #
# Unit-style: schema, bounding, concurrency                                   #
# --------------------------------------------------------------------------- #
