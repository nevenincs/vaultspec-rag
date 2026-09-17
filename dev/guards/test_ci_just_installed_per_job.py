"""Every job that calls ``just`` installs it, before the first call.

A job runs on its own host with only the tools its own steps provide. The
CI/justfile contract checks that a workflow which calls ``just`` installs it
somewhere, which a job in that workflow can satisfy for another job: a release
job calling a recipe after a build matrix installed ``just`` on other hosts
passes that check and fails on its runner with ``just: command not found``.
"""

from __future__ import annotations

import pytest

from dev import ci_contract
from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]


def _calls_just(step: dict[str, object]) -> bool:
    """Whether *step* runs a ``just`` command on any of its lines."""
    run = step.get("run")
    if not isinstance(run, str):
        return False
    return any(line.strip().split()[:1] == ["just"] for line in run.splitlines())


def _installs_just(step: dict[str, object]) -> bool:
    """Whether *step* is the fleet's pinned ``just`` install."""
    with_ = step.get("with")
    return (
        str(step.get("uses") or "").startswith(ci_contract.JUST_INSTALL_USES)
        and isinstance(with_, dict)
        and with_.get("tool") == ci_contract.JUST_INSTALL_TOOL
    )


def _findings(jobs: tuple[workflows.Job, ...]) -> list[str]:
    """Name every job whose first ``just`` call precedes any pinned install."""
    findings: list[str] = []
    for job in jobs:
        installed = False
        for step in job.steps:
            if _installs_just(step):
                installed = True
            elif _calls_just(step) and not installed:
                findings.append(
                    f"{job.workflow}:{job.job_id} step {step.get('name')!r} "
                    "calls just before the job installs it"
                )
                break
    return findings


def test_every_job_installs_just_before_calling_it() -> None:
    """No job relies on another job, or the host, for its ``just``."""
    jobs = workflows.load_jobs()
    assert any(_calls_just(step) for job in jobs for step in job.steps), (
        "no job calls just; this guard is vacuous"
    )
    assert _findings(jobs) == []


def test_a_job_calling_just_without_installing_it_is_named() -> None:
    """Mutation proof: the install-less shape of the release job is caught.

    Deleting the ``Set up just`` step from the binaries ``release`` job made
    ``test_every_job_installs_just_before_calling_it`` fail naming
    ``binaries.yml:release``; restoring it made that test pass again.
    """
    install = {
        "uses": ci_contract.JUST_INSTALL_USES,
        "with": {"tool": ci_contract.JUST_INSTALL_TOOL},
    }
    call = {"name": "Channels", "run": 'just release-channels "${TAG}" channels'}
    bare = workflows.Job("w.yml", "release", "release", (), 30, None, None, (call,))
    late = workflows.Job("w.yml", "late", "late", (), 30, None, None, (call, install))
    ready = workflows.Job(
        "w.yml", "ready", "ready", (), 30, None, None, (install, call)
    )

    assert _findings((bare, late, ready)) == [
        "w.yml:release step 'Channels' calls just before the job installs it",
        "w.yml:late step 'Channels' calls just before the job installs it",
    ]
