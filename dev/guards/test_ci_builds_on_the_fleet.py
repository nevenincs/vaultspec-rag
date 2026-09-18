"""Work that builds or tests this product runs on runners this project owns.

A hosted runner is not a neutral substitute. It has no GPU, no resident
service, no warmed model cache and no pinned Qdrant binary, so a lane that
drifts onto one silently stops measuring the thing it was written to measure -
and a binary built there is built on a machine nobody here controls.

Hosted runners keep exactly one job: handling input this project does not
trust, away from the fleet. A fork's pull request and a dispatch's free-text
tag are both attacker-controlled, and both are resolved on a hosted runner so
that only a validated result reaches a machine on this network. That is a
security boundary, not a convenience, so those jobs are named here rather than
pattern-matched - a new hosted job has to be added deliberately, with a reason.
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

#: `workflow.yml::job` pairs that MUST stay hosted, each with why. Untrusted
#: input is resolved here, before anything it names reaches the fleet.
_BOUNDARY: dict[tuple[str, str], str] = {
    ("publish.yml", "resolve-target"): (
        "validates a dispatch's free-text tag and resolves it to a commit "
        "before the fleet sees either"
    ),
    ("binaries.yml", "validate"): (
        "proves the fleet's runner selectors are satisfiable before "
        "dispatching work to it"
    ),
    ("merge-gate.yml", "gate"): (
        "reads check results and edits a label; never runs a pull request's "
        "code, and must answer for a fork's pull request too"
    ),
    ("claude.yml", "claude"): (
        "runs an assistant on issue and comment text, which is untrusted "
        "input by construction"
    ),
}


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


def test_no_job_outside_the_trust_boundary_runs_hosted() -> None:
    """Every build and test job selects a runner this project owns."""
    offenders = [
        f"{workflow}::{job} -> {labels}"
        for workflow, job, label_sets in _jobs()
        if (workflow, job) not in _BOUNDARY
        for labels in label_sets
        if any(_HOSTED.match(label) for label in labels)
    ]
    assert not offenders, (
        "these jobs run on GitHub-hosted runners; builds and tests belong on "
        f"the fleet: {offenders}"
    )


def test_every_boundary_job_still_exists() -> None:
    """A stale exemption would quietly re-admit a hosted job under its name."""
    present = {(workflow, job) for workflow, job, _ in _jobs()}
    missing = [f"{w}::{j}" for (w, j) in _BOUNDARY if (w, j) not in present]
    assert not missing, (
        f"these hosted exemptions name jobs that no longer exist: {missing}"
    )
