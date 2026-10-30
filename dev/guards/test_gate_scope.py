"""A commit skips a suite only on proof that the suite already passed its tree.

A wrong skip lands unmeasured code with a green check, so every case here is the
guard's negative side: each proves one reason the answer must stay ``full``.
The GitHub API is the one double, because the decision is pure over its answers.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from dev.gate_scope import (
    FULL,
    MEASURING_JOBS,
    POLL_ATTEMPTS,
    PROOF,
    RELEASE_BOT,
    REUSED,
    SCOPE_JOB,
    decide,
    non_version_change,
    prove_release_head,
    wait_for_push_gate,
)
from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit]

SHA = "c" * 40
PARENT = "p" * 40
HEAD = "h" * 40
GATE_RUNS = "actions/workflows/merge-gate.yml/runs"

VERSION_PATCH = '@@ -1 +1 @@\n-version = "1.0.0"\n+version = "1.0.1"'
VERSION_ONLY = [
    {"filename": "CHANGELOG.md", "patch": "@@ -1 +1,2 @@\n+anything"},
    {"filename": "pyproject.toml", "patch": VERSION_PATCH},
    {"filename": "uv.lock", "patch": VERSION_PATCH},
]
CODE_CHANGE = [{"filename": "src/app.py", "patch": "@@ -1 +1 @@\n-a\n+b"}]


def _no_sleep(_seconds: float) -> None:
    """Skip the wait between polls."""


def _api(routes: dict[str, Any]) -> Any:
    """Return an API double that fails on any path the case did not expect."""

    def call(path: str) -> Any:
        assert path in routes, f"unexpected GitHub read: {path}"
        return routes[path]

    return call


def _push_run(sha: str, status: str = "completed", conclusion: str = "success") -> dict:
    """Return the route answering *sha*'s newest push gate."""
    return {
        f"{GATE_RUNS}?head_sha={sha}&event=push&per_page=10": {
            "workflow_runs": [
                {
                    "id": 1,
                    "created_at": "2026-10-30T00:00:00Z",
                    "status": status,
                    "conclusion": conclusion,
                }
            ]
        }
    }


def _jobs(run: int, conclusion: str, scope: str = "success") -> dict:
    """Return the route answering one run's jobs, every measuring job alike."""
    names = [*sorted(MEASURING_JOBS), SCOPE_JOB]
    conclusions = [conclusion] * len(MEASURING_JOBS) + [scope]
    return {
        f"actions/runs/{run}/jobs?filter=all&per_page=100": {
            "jobs": [
                {"name": name, "run_attempt": 1, "id": index, "conclusion": outcome}
                for index, (name, outcome) in enumerate(
                    zip(names, conclusions, strict=True)
                )
            ]
        }
    }


def _pr_runs(*runs: tuple[int, str]) -> dict:
    """Return the route answering the pull-request head's completed runs."""
    query = f"head_sha={HEAD}&event=pull_request&status=completed&per_page=100"
    return {
        f"{GATE_RUNS}?{query}": {
            "workflow_runs": [
                {"id": run, "conclusion": conclusion} for run, conclusion in runs
            ]
        }
    }


def _landed(files: list[dict[str, str]], *, same_tree: bool = True) -> dict:
    """Return the routes describing a squash merge that landed *files*."""
    return {
        f"commits/{SHA}": {
            "parents": [{"sha": PARENT}],
            "commit": {"tree": {"sha": "tree"}},
        },
        f"compare/{PARENT}...{SHA}": {"files": files},
        f"commits/{SHA}/pulls": [
            {"merge_commit_sha": SHA, "merged_at": "now", "head": {"sha": HEAD}}
        ],
        f"commits/{HEAD}": {
            "commit": {"tree": {"sha": "tree" if same_tree else "other"}}
        },
    }


def _decide_push(routes: dict[str, Any]) -> str:
    """Return the suites a push is told to run."""
    return decide(_api(routes), {"EVENT": "push", "SHA": SHA}, _no_sleep)[0]


def _decide_proposal(routes: dict[str, Any], author: str = RELEASE_BOT) -> str:
    """Return the suites a pull request is told to run."""
    env = {
        "EVENT": "pull_request",
        "ACTION": "synchronize",
        "AUTHOR": author,
        "HEAD_SHA": HEAD,
        "BASE_REF": "main",
    }
    return decide(_api(routes), env, _no_sleep)[0]


def _proposal(files: list[dict[str, str]], behind: int = 0) -> dict:
    """Return the route comparing a proposal with its base."""
    return {
        f"compare/main...{HEAD}": {
            "behind_by": behind,
            "files": files,
            "merge_base_commit": {"sha": PARENT},
        }
    }


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        (CODE_CHANGE, "src/app.py is not a release version file"),
        (
            [{"filename": "uv.lock", "patch": '@@\n+version = "2"\n+source = "x"'}],
            "uv.lock changes more than its version line",
        ),
        (
            [{"filename": "pyproject.toml"}],
            "pyproject.toml has no readable diff",
        ),
        (
            [{"filename": "CHANGELOG.md", "previous_filename": "src/app.py"}],
            "CHANGELOG.md was renamed",
        ),
    ],
    ids=["other-file", "dependency-line", "omitted-patch", "rename"],
)
def test_more_than_a_version_bump_is_named(
    files: list[dict[str, str]], reason: str
) -> None:
    """Mutation proof: ``return None`` as the first line of ``non_version_change``
    failed all four cases on this assertion; restoring it passed.
    """
    assert non_version_change(files) == reason


def test_a_listing_at_the_cap_may_hide_a_file() -> None:
    """Mutation proof: deleting the cap check failed this; restoring it passed."""
    files = [{"filename": "CHANGELOG.md"}] * 300
    assert non_version_change(files) == (
        "the comparison reached the 300-file listing cap"
    )


def test_a_version_bump_is_not_named() -> None:
    """The positive side, so a rule that refuses everything cannot pass above."""
    assert non_version_change(VERSION_ONLY) is None


def test_a_version_bump_over_a_green_parent_needs_no_suite() -> None:
    assert _decide_push({**_landed(VERSION_ONLY), **_push_run(PARENT)}) == PROOF


def test_a_version_bump_over_a_red_parent_measures() -> None:
    """Mutation proof: accepting any settled parent state failed this on the
    returned ``proof``; restoring the success comparison passed.
    """
    routes = {
        **_landed(VERSION_ONLY),
        **_push_run(PARENT, conclusion="failure"),
        **_pr_runs(),
    }
    assert _decide_push(routes) == FULL


def test_a_merge_with_the_passed_tree_reuses_its_proof() -> None:
    routes = {
        **_landed(CODE_CHANGE),
        **_pr_runs((7, "success")),
        **_jobs(7, "success"),
    }
    assert _decide_push(routes) == REUSED


def test_a_merge_with_another_tree_measures() -> None:
    """Mutation proof: dropping the tree comparison failed this on ``reused``;
    restoring it passed. This is what keeps an admin merge of a stale head honest.
    """
    routes = {
        **_landed(CODE_CHANGE, same_tree=False),
        **_pr_runs((7, "success")),
        **_jobs(7, "success"),
    }
    assert _decide_push(routes) == FULL


def test_a_direct_push_with_no_pull_request_measures() -> None:
    routes = {**_landed(CODE_CHANGE), f"commits/{SHA}/pulls": []}
    assert _decide_push(routes) == FULL


def test_a_newer_red_ends_the_proof_walk() -> None:
    """Mutation proof: skipping non-success runs in the walk failed this on
    ``reused``; restoring the early return passed.
    """
    routes = {
        **_landed(CODE_CHANGE),
        **_pr_runs((7, "success"), (8, "failure")),
        **_jobs(7, "success"),
    }
    assert _decide_push(routes) == FULL


def test_an_unrelated_label_run_carries_the_proof_before_it() -> None:
    routes = {
        **_landed(CODE_CHANGE),
        **_pr_runs((7, "success"), (8, "success")),
        **_jobs(7, "success"),
        **_jobs(8, "skipped", scope="skipped"),
    }
    assert _decide_push(routes) == REUSED


def test_a_proof_tier_run_is_not_measured_proof() -> None:
    """A run the scope job skipped everything in measured nothing itself.

    Mutation proof: dropping the scope comparison from the preservation test
    failed this on ``reused``; restoring it passed.
    """
    routes = {
        **_landed(CODE_CHANGE),
        **_pr_runs((7, "success"), (8, "success")),
        **_jobs(7, "success"),
        **_jobs(8, "skipped", scope="success"),
    }
    assert _decide_push(routes) == FULL


def test_only_the_release_app_proposal_may_skip() -> None:
    """Mutation proof: removing the author check failed this with an unexpected
    compare read; restoring it passed.
    """
    assert _decide_proposal({}, author="someone") == FULL


def test_a_current_proposal_over_a_green_base_needs_no_suite() -> None:
    routes = {**_proposal(VERSION_ONLY), **_push_run(PARENT)}
    assert _decide_proposal(routes) == PROOF


@pytest.mark.parametrize(
    "routes",
    [
        {**_proposal(VERSION_ONLY, behind=1)},
        {**_proposal(CODE_CHANGE)},
        {**_proposal(VERSION_ONLY), **_push_run(PARENT, conclusion="cancelled")},
    ],
    ids=["behind-main", "code-change", "unproven-base"],
)
def test_a_proposal_without_every_condition_measures(routes: dict[str, Any]) -> None:
    """Mutation proof: deleting the behind check failed ``behind-main`` on
    ``proof``; accepting any base state failed ``unproven-base``; restoring each
    passed.
    """
    assert _decide_proposal(routes) == FULL


@pytest.mark.parametrize(
    "env",
    [
        {"EVENT": "workflow_dispatch"},
        {"EVENT": "pull_request", "ACTION": "labeled", "LABEL": "ci:full"},
    ],
    ids=["dispatch", "full-label"],
)
def test_an_explicit_request_always_measures(env: dict[str, str]) -> None:
    assert decide(_api({}), env, _no_sleep)[0] == FULL


def test_a_parent_that_never_settles_is_reported_running() -> None:
    """A bounded wait, so a stalled parent cannot hold the job to its ceiling."""
    sleeps: list[float] = []
    routes = _push_run(PARENT, status="in_progress", conclusion="")
    assert wait_for_push_gate(_api(routes), PARENT, sleeps.append) == "running"
    assert len(sleeps) == POLL_ATTEMPTS - 1


@pytest.mark.parametrize(
    ("files", "state", "reason"),
    [
        (CODE_CHANGE, "success", "changes more than its version files"),
        (VERSION_ONLY, "failure", "push run is failure"),
    ],
    ids=["code-change", "red-parent"],
)
def test_the_release_cut_refuses_an_unproven_head(
    files: list[dict[str, str]], state: str, reason: str
) -> None:
    """Mutation proof: returning ``None`` from the state branch failed
    ``red-parent`` on this assertion; restoring it passed.
    """
    routes = {
        **_landed(files),
        **_push_run(PARENT, conclusion=state),
    }
    failure = prove_release_head(_api(routes), SHA, _no_sleep)
    assert failure is not None
    assert reason in failure


def test_the_gate_reads_the_same_measuring_jobs() -> None:
    """The verdict's history query names exactly the jobs proof is judged on.

    Mutation proof: renaming one job in the gate's ``select`` failed this naming
    that job; restoring it passed.
    """
    jobs = workflows.document("merge-gate.yml")["jobs"]
    script = next(
        str(step["run"])
        for step in jobs["gate"]["steps"]
        if step.get("name") == "Every full check passed on this commit"
    )
    select = next(line for line in script.splitlines() if "--jq '.jobs[] |" in line)
    assert set(re.findall(r'\.name == "([^"]+)"', select)) == MEASURING_JOBS
    assert jobs["scope"]["name"] == SCOPE_JOB
