"""Every job runs on runners this project owns. None runs GitHub-hosted.

A hosted runner is not a neutral substitute. It has no GPU, no resident
service, no warmed model cache and no pinned Qdrant binary, so a lane that
drifts onto one silently stops measuring the thing it was written to measure -
and a binary built there is built on a machine nobody here controls.

There is no exemption. Handling input this project does not trust used to be
one: a dispatch's free-text tag was resolved on a hosted runner before the
fleet saw it. Those resolvers now run on the fleet, and what keeps them safe is
what they never do - check out, run an action, or interpolate the input into a
script - which `tools/binaries/tests/test_release_workflow.py` holds. A job
container no fleet host can start was the other exemption; such a job now runs
natively instead of leaving the fleet.
"""

from __future__ import annotations

import re
from typing import Any, cast

import pytest
import yaml

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: A GitHub-hosted runner image label: `ubuntu-24.04`, `windows-latest`,
#: `macos-15`, `ubuntu-24.04-arm`. Fleet labels carry no version or channel
#: suffix, which is what separates the two without naming every fleet label.
_HOSTED = re.compile(r"^(ubuntu|windows|macos)-(latest|\d[\w.]*)(-arm)?$")


def _runner_labels(raw: Any, matrix: list[dict[str, Any]]) -> list[list[str]]:
    """Return every concrete label set *raw* resolves to across the matrix."""
    if isinstance(raw, str) and "matrix." in raw:
        key = raw.split("matrix.", 1)[1].rstrip("} ").strip()
        resolved: list[list[str]] = []
        for leg in matrix:
            value = leg.get(key)
            if isinstance(value, str):
                resolved.append([value])
            elif isinstance(value, list):
                resolved.append([str(item) for item in value])
        return resolved
    if isinstance(raw, str):
        return [[raw]]
    if isinstance(raw, list):
        return [[str(item) for item in raw]]
    return []


def _jobs() -> list[tuple[str, str, list[list[str]]]]:
    """Return `(workflow, job id, label sets)` for every job in every workflow."""
    root = workflows.repository_root() / ".github" / "workflows"
    found: list[tuple[str, str, list[list[str]]]] = []
    for path in sorted(root.glob("*.yml")):
        document = cast(
            "dict[str, Any]", yaml.safe_load(path.read_text(encoding="utf-8"))
        )
        for job_id, body in (document.get("jobs") or {}).items():
            if not isinstance(body, dict) or "runs-on" not in body:
                continue
            matrix = (body.get("strategy") or {}).get("matrix") or {}
            include = matrix.get("include") or []
            found.append((path.name, job_id, _runner_labels(body["runs-on"], include)))
    return found


def _offenders(jobs: list[tuple[str, str, list[list[str]]]]) -> list[str]:
    """Name every job or matrix leg that does not select a fleet label set.

    A `runs-on` that resolves to no label set at all is named too: an
    unreadable selector is not evidence of a fleet one.
    """
    return [
        f"{workflow}::{job} -> {labels or '<unresolved>'}"
        for workflow, job, label_sets in jobs
        for labels in (label_sets or [[]])
        if "self-hosted" not in {label.lower() for label in labels}
        or any(_HOSTED.match(label) for label in labels)
    ]


def test_no_job_runs_on_a_github_hosted_runner() -> None:
    """Every job and every matrix leg selects a `self-hosted` label set."""
    offenders = _offenders(_jobs())
    assert not offenders, (
        "these jobs select a GitHub-hosted runner, or no self-hosted label "
        f"set; every job runs on the fleet: {offenders}"
    )


def test_a_hosted_leg_is_named() -> None:
    """Mutation proof: a hosted leg hidden in a self-hosted matrix is caught.

    Matrix legs are resolved one by one, so one hosted leg among fleet legs is
    named, as are a literal hosted label and a selector that cannot be read.
    """
    legs = [
        {"runner": ["self-hosted", "Linux", "X64"]},
        {"runner": "ubuntu-24.04-arm"},
    ]
    jobs = [
        ("w.yml", "build", _runner_labels("${{ matrix.runner }}", legs)),
        ("w.yml", "gate", _runner_labels("ubuntu-24.04", [])),
        ("w.yml", "lint", _runner_labels(["self-hosted", "Linux", "X64"], [])),
        ("w.yml", "odd", _runner_labels("${{ fromJSON(inputs.runner) }}", [])),
    ]
    assert _offenders(jobs) == [
        "w.yml::build -> ['ubuntu-24.04-arm']",
        "w.yml::gate -> ['ubuntu-24.04']",
        "w.yml::odd -> ['${{ fromJSON(inputs.runner) }}']",
    ]
