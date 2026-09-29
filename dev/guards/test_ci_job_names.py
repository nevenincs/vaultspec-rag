"""Workflow and job names stay addressable.

Every workflow is named ``<Product> <Purpose>`` so its runs group together.
Every row a workflow run shows carries a distinct label, so a required check
names exactly one row.
"""

from __future__ import annotations

import pytest

from dev.ci_names import PRODUCT
from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]


def test_every_workflow_name_starts_with_the_product() -> None:
    """Every workflow is ``<Product> <Purpose>``."""
    findings = [
        f"{workflow}: {name!r}"
        for workflow, name in workflows.workflow_names()
        if not name.startswith(f"{PRODUCT} ")
    ]
    assert not findings, (
        f"A workflow is not named `{PRODUCT} <Purpose>`.\n\n" + "\n".join(findings)
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
