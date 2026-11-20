"""``server jobs --state`` filters against the real service route.

The service owns the job vocabulary and the filtering. These tests drive the
real CLI against a real ``GET /jobs`` route over a seeded registry, so a state
name the CLI sends that the service does not recognise surfaces as an empty
list instead of passing on a stubbed server.

The service serves two record shapes side by side: activity records carry a
raw phase (``done``, ``error``, ``cancelled``), while canonical manager jobs
carry only a lifecycle state and are reported under the phase ``failed``. A
phase filter cannot name a failed job in both shapes, so the failed outcome
must be requested by state.

Mutation check: restoring the failure alias that maps ``failed`` to the phase
``error`` fails ``test_failed_state_returns_every_failed_job`` on its id
assertion, because the canonical failed job is missing; restoring the fix
passes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ... import jobs as _jobs
from ...cli import app
from ...indexer._run_ledger_models import RunAuthority
from ...job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
)
from ._service_jobs_support import _canonical_resilience_server, runner

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_CANONICAL_FAILED_ID = "0badc0de-0000-4000-8000-0000000000f1"


def _seed_canonical_failed_job(project_root: Path) -> None:
    """Admit one canonical job and fail it before any runtime owns it."""
    (project_root / ".vault").mkdir(parents=True)
    manager = _jobs.get_job_manager()
    created = manager.create(
        JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.VAULT,
            project_root=str(project_root),
            mode=JobMode.INCREMENTAL,
            authority=RunAuthority.PUBLICATION,
        ),
        JobInitiator(
            kind="cli",
            command="test_state_filter",
            project_root=str(project_root),
        ),
        job_id=_CANONICAL_FAILED_ID,
    )
    assert created.code == "job_created"
    failed = manager.fail_unstarted(_CANONICAL_FAILED_ID, result="no runtime")
    assert failed.job is not None
    assert failed.job.state.value == "failed"


def _seed_terminal_jobs(project_root: Path) -> dict[str, list[str]]:
    """Record finished, failed and cancelled jobs; return ids by outcome."""
    done = _jobs.record_start(JobSource.VAULT, "tool")
    _jobs.record_finish(done, result="indexed")
    failed = _jobs.record_start(JobSource.VAULT, "tool")
    _jobs.record_finish(failed, error="encode failed")
    cancelled = _jobs.record_start(JobSource.VAULT, "tool")
    _jobs.record_finish(cancelled, phase="cancelled")
    _seed_canonical_failed_job(project_root)
    return {
        "finished": [done],
        "failed": sorted([failed, _CANONICAL_FAILED_ID]),
        "cancelled": [cancelled],
    }


def _jobs_ids(*args: str, port: int) -> list[str]:
    result = runner.invoke(
        app, ["server", "jobs", *args, "--json", "--port", str(port)]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    return sorted(str(job["id"]) for job in data["jobs"])


def test_failed_state_returns_every_failed_job(tmp_path: Path) -> None:
    with _canonical_resilience_server(tmp_path) as (port, _token):
        expected = _seed_terminal_jobs(tmp_path / "project")["failed"]
        by_state = _jobs_ids("--state", "failed", port=port)
        by_flag = _jobs_ids("--failed", port=port)

    assert by_state == expected
    assert by_flag == expected


@pytest.mark.parametrize("state", ["finished", "cancelled"])
def test_other_terminal_states_return_exactly_that_outcome(
    tmp_path: Path, state: str
) -> None:
    with _canonical_resilience_server(tmp_path) as (port, _token):
        expected = _seed_terminal_jobs(tmp_path / "project")[state]
        returned = _jobs_ids("--state", state, port=port)

    assert returned == expected
