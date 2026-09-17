"""No workflow expression is expanded into a script, and writes are job-scoped.

An expression inside ``run:`` is substituted into the script text before the
shell parses it, so a value carrying shell syntax - a dispatch input, a tag, a
pull request title - executes as code on the runner. Passed through ``env:``
it arrives as data. The rule holds for static matrix values too, so that a
later edit swapping a literal for an input cannot slip past a reviewer.

A write permission declared at workflow level is granted to every job in the
workflow, including jobs added later that never needed it; each job that
writes declares its own.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

_EXPRESSION = re.compile(r"\$\{\{.*?\}\}")


def _documents() -> list[tuple[str, dict[str, Any]]]:
    """Return every workflow and local action, parsed."""
    root = workflows.repository_root() / ".github"
    paths = sorted([*root.rglob("*.yml"), *root.rglob("*.yaml")])
    return [
        (path.relative_to(root).as_posix(), yaml.safe_load(path.read_text("utf-8")))
        for path in paths
        if path.name != "actionlint.yaml"
    ]


def _injection_findings(documents: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """Name every ``run:`` script that embeds an expression."""
    findings: list[str] = []
    for name, document in documents:
        steps = [
            (job_id, step)
            for job_id, body in (document.get("jobs") or {}).items()
            for step in body.get("steps") or []
        ]
        steps += [
            ("composite", step)
            for step in (document.get("runs") or {}).get("steps") or []
        ]
        for job_id, step in steps:
            run = step.get("run")
            if isinstance(run, str) and _EXPRESSION.search(run):
                findings.append(f"{name}:{job_id}: {step.get('name')!r}")
    return findings


def _permission_findings(documents: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """Name every workflow granting a write permission to all of its jobs."""
    findings: list[str] = []
    for name, document in documents:
        granted = document.get("permissions")
        if granted == "write-all" or (
            isinstance(granted, dict) and "write" in granted.values()
        ):
            findings.append(name)
    return findings


def test_no_script_embeds_a_workflow_expression() -> None:
    """Every value reaches a script through ``env:``."""
    assert _injection_findings(_documents()) == []


def test_an_embedded_expression_is_named() -> None:
    """Mutation proof: the shape that put the tag into the bundle step is caught.

    Restoring ``just release-bundle "${{ inputs.tag }}"`` in ``binaries.yml``
    made ``test_no_script_embeds_a_workflow_expression`` fail naming that
    step; passing the tag through ``env:`` again made it pass.
    """
    document = {
        "jobs": {
            "build": {
                "steps": [
                    {
                        "name": "Bundle",
                        "run": 'just release-bundle "${{ inputs.tag }}"',
                    },
                    {"name": "Safe", "env": {"TAG": "${{ inputs.tag }}"}, "run": "x"},
                ]
            }
        }
    }
    assert _injection_findings([("w.yml", document)]) == ["w.yml:build: 'Bundle'"]


def test_no_workflow_grants_writes_to_every_job() -> None:
    """Write permissions are declared on the job that needs them."""
    assert _permission_findings(_documents()) == []


def test_a_workflow_level_write_is_named() -> None:
    """Mutation proof: the release-please shape before the move is caught.

    Moving ``contents: write`` back to the top of ``release-please.yml`` made
    ``test_no_workflow_grants_writes_to_every_job`` fail naming that file;
    moving it back onto the job made it pass.
    """
    documents = [
        ("wide.yml", {"permissions": {"contents": "write"}}),
        ("all.yml", {"permissions": "write-all"}),
        ("narrow.yml", {"permissions": {"contents": "read"}}),
    ]
    assert _permission_findings(documents) == ["wide.yml", "all.yml"]
