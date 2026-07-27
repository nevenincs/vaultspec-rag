"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from vaultspec_rag import jobs as _managed_jobs
from vaultspec_rag._job_errors import JobError, JobErrorKind, remediation
from vaultspec_rag.cli import app
from vaultspec_rag.job_control import RunControlToken
from vaultspec_rag.job_manager._control import AttemptTerminal
from vaultspec_rag.job_models import (
    DesiredJobState,
    IndexResilienceSnapshot,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)

from ._service_jobs_support import _canonical_resilience_server, runner

if TYPE_CHECKING:
    from pathlib import Path


async def _seed_terminal_resilience_job(
    project_root: Path,
    *,
    outcome_name: str,
    error_kind: JobErrorKind | None,
) -> dict[str, object]:
    manager = _managed_jobs.get_job_manager()
    created = manager.create(
        JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.CODE,
            project_root=str(project_root),
            mode=JobMode.REBUILD,
        ),
        JobInitiator("cli", "server jobs", str(project_root)),
        start_paused=outcome_name == "controlled",
    )
    assert created.job is not None
    job_id = created.job.id
    owner_task: asyncio.Task[object] | None = None
    if outcome_name == "controlled":
        terminal = manager.set_desired_state(job_id, DesiredJobState.CANCELLED)
        terminal_outcome = JobState.CANCELLED.value
    elif outcome_name == "interrupted":
        owner_task = asyncio.create_task(asyncio.Event().wait())
        started = manager.start_attempt(
            job_id,
            task=owner_task,
            control=RunControlToken(),
        )
        assert started.code == "attempt_started"
        terminal = manager.finish_attempt(
            job_id,
            AttemptTerminal(
                attempt=1,
                task=owner_task,
                state=JobState.INTERRUPTED,
                result="the service stopped before the attempt completed",
                error_kind=JobState.INTERRUPTED.value,
            ),
        )
        terminal_outcome = JobState.INTERRUPTED.value
    else:
        assert error_kind is not None
        terminal = manager.fail_unstarted(
            job_id,
            result=str(JobError(error_kind, f"{outcome_name} safety boundary reached")),
        )
        terminal_outcome = error_kind.value
    try:
        assert terminal.job is not None
        resilience = IndexResilienceSnapshot(
            generation_id=f"generation-{outcome_name}",
            committed_units=41,
            replayed_units=3,
            checkpoint_compatible=True,
            last_durable_progress_at=1_722_000_000.0,
            no_progress_timeout_seconds=300.0,
            no_progress_remaining_seconds=17.5,
            circuit_state=(
                "open" if error_kind is JobErrorKind.WATCHER_CIRCUIT_OPEN else "closed"
            ),
            next_retry_at=1_722_000_060.0,
            peak_rss_mb=512.0,
            rss_ceiling_mb=2048.0,
            peak_cuda_allocated_mb=768.0,
            peak_cuda_reserved_mb=896.0,
            cuda_ceiling_mb=4096.0,
            support_profile="embedded-local",
            terminal_outcome=terminal_outcome,
        )
        assert manager.update_terminal_resilience(
            job_id,
            attempt=terminal.job.attempt.number,
            resilience=resilience,
        )
        snapshot = manager.get(job_id)
        assert snapshot is not None
        return snapshot.to_dict()
    finally:
        if owner_task is not None:
            owner_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await owner_task


def _resilience_http_views(
    port: int,
    token: str,
    job_id: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Fetch and validate the collection, detail, and health HTTP surfaces."""
    import httpx

    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
        collection_response = client.get("/jobs", headers=headers)
        detail_response = client.get(f"/jobs/{job_id}", headers=headers)
        health_response = client.get("/health")
    assert collection_response.status_code == 200
    assert detail_response.status_code == 200
    assert health_response.status_code == 200
    collection_job = cast("dict[str, object]", collection_response.json()["jobs"][0])
    detail_job = cast("dict[str, object]", detail_response.json()["job"])
    health_jobs = cast("dict[str, object]", health_response.json()["jobs"])
    return collection_job, detail_job, health_jobs


@dataclass(frozen=True)
class _ResilienceJobParity:
    canonical: dict[str, object]
    collection_job: dict[str, object]
    detail_job: dict[str, object]
    job_id: str
    expected_state: JobState
    expected_error_kind: str | None


def _assert_resilience_job_parity(parity: _ResilienceJobParity) -> str:
    """Assert canonical collection and detail payload parity."""
    assert parity.collection_job["id"] == parity.detail_job["id"] == parity.job_id
    assert (
        parity.collection_job["state"]
        == parity.detail_job["state"]
        == parity.canonical["state"]
    )
    assert parity.detail_job["state"] == parity.expected_state.value
    assert (
        parity.collection_job["error_kind"]
        == parity.detail_job["error_kind"]
        == parity.expected_error_kind
    )
    assert parity.collection_job["resilience"] == parity.detail_job["resilience"]
    expected_terminal_outcome = (
        parity.expected_error_kind
        if parity.expected_error_kind is not None
        else JobState.CANCELLED.value
    )
    detail_resilience = cast("dict[str, object]", parity.detail_job["resilience"])
    assert detail_resilience["terminal_outcome"] == expected_terminal_outcome
    return expected_terminal_outcome


# The resilience measures the job response rounds to operator precision; the
# health rollup projects them at full snapshot precision. Rounding both sides
# to the same precision before comparing makes the identity a comparison of
# state, not of serialization cadence, so a future fractional-memory scenario
# cannot reintroduce a rounds-vs-full-precision divergence.
_RESILIENCE_MEASURE_KEYS = (
    "no_progress_timeout_seconds",
    "no_progress_remaining_seconds",
    "peak_rss_mb",
    "rss_ceiling_mb",
    "peak_cuda_allocated_mb",
    "peak_cuda_reserved_mb",
    "cuda_ceiling_mb",
)


def _resilience_state(resilience: dict[str, object]) -> dict[str, object]:
    """Return the shared resilience state: measures rounded, remediation dropped.

    ``remediation`` is excluded because it is not resilience state - it is a
    derived presentation hint the broker-facing job response adds and the
    liveness-facing health rollup deliberately does not carry. It is verified
    separately as a correct derivation of the shared terminal outcome.
    """
    state = {
        key: (
            round(float(value), 1)
            if key in _RESILIENCE_MEASURE_KEYS
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            else value
        )
        for key, value in resilience.items()
        if key != "remediation"
    }
    return state


def _assert_resilience_health(
    health_jobs: dict[str, object],
    detail_job: dict[str, object],
    *,
    job_id: str,
    outcome_name: str,
    error_kind: JobErrorKind | None,
) -> None:
    """Assert health carries the same bounded resilience STATE and failure evidence.

    Health and the job response expose identical resilience STATE - the full
    canonical field set, including the terminal outcome. They differ only on the
    derived ``remediation`` hint, which the broker-facing job response carries
    and the liveness health rollup does not. So the identity is over the state,
    and the job response's remediation is verified separately as the correct
    derivation of the terminal outcome both surfaces share.
    """
    health_resilience = cast("dict[str, object]", health_jobs["resilience"]).copy()
    assert health_resilience.pop("job_id") == job_id
    assert health_resilience.pop("source") == "code"
    detail_resilience = cast("dict[str, object]", detail_job["resilience"])
    # Identical resilience state across the two surfaces (remediation excluded,
    # measures compared at one precision). Any divergence in generation,
    # checkpoint counts, circuit, ceilings, or terminal outcome still fails.
    assert _resilience_state(health_resilience) == _resilience_state(detail_resilience)
    # The broker response's remediation is the correct derivation of the
    # terminal outcome both surfaces carry - same state, same derivation.
    shared_terminal = health_resilience["terminal_outcome"]
    assert detail_resilience["remediation"] == remediation(
        shared_terminal if isinstance(shared_terminal, str) else None
    )
    if error_kind is None or outcome_name == "interrupted":
        assert health_jobs["last_failed"] is None
        return
    last_failed = cast("dict[str, object]", health_jobs["last_failed"])
    assert last_failed["id"] == job_id
    assert last_failed["error_kind"] == error_kind.value


def _assert_resilience_cli_json(
    port: int,
    job_id: str,
    detail_job: dict[str, object],
) -> None:
    """Assert the JSON CLI retains detail-route resilience fields."""
    cli_json = runner.invoke(
        app,
        [
            "server",
            "jobs",
            "--port",
            str(port),
            "--job-id",
            job_id,
            "--json",
        ],
    )
    assert cli_json.exit_code == 0, cli_json.output
    cli_job = cast("dict[str, object]", json.loads(cli_json.output)["data"]["jobs"][0])
    assert cli_job["error_kind"] == detail_job["error_kind"]
    assert cli_job["resilience"] == detail_job["resilience"]


def _assert_resilience_cli_human(
    port: int,
    job_id: str,
    outcome_name: str,
    expected_terminal_outcome: str,
) -> None:
    """Assert the human CLI renders every bounded resilience field."""
    cli_human = runner.invoke(
        app,
        ["server", "jobs", "--port", str(port), "--job-id", job_id],
    )
    assert cli_human.exit_code == 0, cli_human.output
    expected_lines = (
        "Index profile: embedded-local",
        f"Checkpoint generation: generation-{outcome_name}",
        "Checkpoint compatible: yes",
        "Checkpoint units: 41 committed, 3 resumed",
        "No-progress budget remaining: 17 seconds",
        "Retry circuit: " + ("open" if outcome_name == "circuit-open" else "closed"),
        "Next retry: 2024-07-26 13:21:00 UTC",
        "RSS high-water / ceiling: 512.0 MiB / 2.0 GiB",
        "CUDA allocated high-water: 768.0 MiB",
        "CUDA reserved high-water / ceiling: 896.0 MiB / 4.0 GiB",
        f"Index outcome: {expected_terminal_outcome}",
    )
    for line in expected_lines:
        assert line in cli_human.output


@pytest.mark.unit
@pytest.mark.parametrize(
    ("outcome_name", "error_kind", "expected_state", "expected_error_kind"),
    [
        ("controlled", None, JobState.CANCELLED, None),
        ("interrupted", None, JobState.INTERRUPTED, "interrupted"),
        (
            "rss-limited",
            JobErrorKind.RSS_MEMORY_CEILING,
            JobState.FAILED,
            "rss_memory_ceiling",
        ),
        (
            "cuda-limited",
            JobErrorKind.CUDA_MEMORY_CEILING,
            JobState.FAILED,
            "cuda_memory_ceiling",
        ),
        (
            "timed-out",
            JobErrorKind.NO_PROGRESS_TIMEOUT,
            JobState.FAILED,
            "no_progress_timeout",
        ),
        (
            "circuit-open",
            JobErrorKind.WATCHER_CIRCUIT_OPEN,
            JobState.FAILED,
            "watcher_circuit_open",
        ),
    ],
)
async def test_canonical_resilience_snapshot_has_http_health_and_cli_parity(
    tmp_path: Path,
    outcome_name: str,
    error_kind: JobErrorKind | None,
    expected_state: JobState,
    expected_error_kind: str | None,
) -> None:
    project_root = tmp_path / outcome_name
    project_root.mkdir()
    with _canonical_resilience_server(tmp_path) as (port, token):
        canonical = await _seed_terminal_resilience_job(
            project_root,
            outcome_name=outcome_name,
            error_kind=error_kind,
        )
        job_id = cast("str", canonical["id"])
        collection_job, detail_job, health_jobs = _resilience_http_views(
            port,
            token,
            job_id,
        )
        expected_terminal_outcome = _assert_resilience_job_parity(
            _ResilienceJobParity(
                canonical=canonical,
                collection_job=collection_job,
                detail_job=detail_job,
                job_id=job_id,
                expected_state=expected_state,
                expected_error_kind=expected_error_kind,
            )
        )
        _assert_resilience_health(
            health_jobs,
            detail_job,
            job_id=job_id,
            outcome_name=outcome_name,
            error_kind=error_kind,
        )
        _assert_resilience_cli_json(port, job_id, detail_job)
        _assert_resilience_cli_human(
            port,
            job_id,
            outcome_name,
            expected_terminal_outcome,
        )
