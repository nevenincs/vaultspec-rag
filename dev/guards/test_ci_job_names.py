"""Workflow and job names stay addressable.

Owned workflows are named ``<Product> <Purpose>`` so their runs group together.
Shared generated workflows retain their owner's exact name.
Every row a workflow run shows carries a distinct label, so a required check
names exactly one row.
"""

from __future__ import annotations

import pytest

from dev.ci_names import PRODUCT, SHARED_WORKFLOW_NAMES
from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]


def test_every_workflow_name_starts_with_the_product() -> None:
    """Owned workflows use the product; shared workflows use their exact name.

    Verified: renaming devserver.yml's workflow to an arbitrary name failed
    here; restoring it passed. The parity guard also checks its full content.
    """
    findings = [
        f"{workflow}: {name!r}"
        for workflow, name in workflows.workflow_names()
        if (
            name != SHARED_WORKFLOW_NAMES[workflow]
            if workflow in SHARED_WORKFLOW_NAMES
            else not name.startswith(f"{PRODUCT} ")
        )
    ]
    assert not findings, (
        "A workflow differs from its product or shared name.\n\n" + "\n".join(findings)
    )


def test_job_names_are_unique() -> None:
    """No two rows of one workflow run carry the same label.

    Two ways that happens, and only one is visible in the YAML. Two jobs may
    simply be given the same ``name:``. Or one job with a matrix may leave its
    variable out of the name - which reads as a single unique name in the file
    and produces one identically labelled row per leg, at which point a
    required status check can only ever name one of them and a reviewer cannot
    tell which leg went red.
    """
    seen: dict[tuple[str, str], list[str]] = {}
    for job in workflows.load_jobs():
        seen.setdefault((job.workflow, job.name), []).append(job.job_id)
    findings = [
        f"{workflow}: {name!r} is used by {', '.join(ids)}"
        for (workflow, name), ids in sorted(seen.items())
        if len(ids) > 1
    ]
    findings.extend(
        f"{job.workflow}:{job.job_id}: {job.name!r} varies over "
        f"{', '.join(job.matrix_axes)} but names no leg, so every leg is one "
        "identically labelled row"
        for job in workflows.load_jobs()
        if job.matrix_axes
        and not any(f"matrix.{axis}" in job.name for axis in job.matrix_axes)
    )
    assert not findings, (
        "Two rows carry the same label.\n"
        "Carry the matrix variable in the name, or fold the jobs together.\n\n"
        + "\n".join(findings)
    )
