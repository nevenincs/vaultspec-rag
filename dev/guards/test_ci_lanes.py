"""One automatic pull-request workflow owns merge readiness.

A draft runs nothing. Every ready pull-request head runs every merge
gate; the commit that lands on main runs
every gate again. The release App's pull request runs the same workflow from
its own events, so the required context has one implementation for
contributor and release branches.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from dev.guards import _workflows as workflows
from dev.guards._ci_names import (
    GATE_JOB,
    GATE_NAME_EXPRESSION,
    RELEASE_BOT,
    Workflow,
)

pytestmark = [pytest.mark.unit, pytest.mark.repo]

PULL_REQUEST_TYPES = [
    "opened",
    "reopened",
    "synchronize",
    "ready_for_review",
    "labeled",
]
FULL_JOBS = frozenset(
    {"lint", "tests", "tests-windows", "dependency-audit", "code-scanning"}
)
GATE_RECIPES = {
    "check-all": frozenset({"linux"}),
    "test-python": frozenset({"linux", "windows"}),
    "audit-deps": frozenset({"linux"}),
}


def _triggers() -> dict[object, object]:
    """Return the merge gate's ``on:`` mapping."""
    triggers = workflows.triggers(workflows.document(Workflow.MERGE_GATE))
    assert isinstance(triggers, dict), f"{Workflow.MERGE_GATE} has no `on:` mapping"
    return cast("dict[object, object]", triggers)


def _jobs() -> dict[str, dict[str, Any]]:
    """Return the merge gate's raw jobs mapping."""
    jobs = workflows.document(Workflow.MERGE_GATE).get("jobs")
    assert isinstance(jobs, dict), f"{Workflow.MERGE_GATE} has no jobs"
    return cast("dict[str, dict[str, Any]]", jobs)


def _platforms_by_recipe(event: str) -> dict[str, set[str]]:
    """Return ``recipe -> platforms`` for every measuring recipe *event* runs."""
    found: dict[str, set[str]] = {}
    for job in workflows.load_jobs(Workflow.MERGE_GATE):
        for recipe in job.measuring_recipes_on(event):
            found.setdefault(recipe, set()).update(job.platforms)
    return found


def test_pull_request_heads_start_the_gate_automatically() -> None:
    """Every lifecycle event that can create a merge candidate starts CI.

    Mutation proof: removing ``synchronize`` makes this fail with the complete
    actual type list; restoring it makes this pass.
    """
    pull_request = _triggers().get("pull_request")
    assert isinstance(pull_request, dict)
    types = cast("dict[object, object]", pull_request).get("types")
    assert types == PULL_REQUEST_TYPES, (
        f"{Workflow.MERGE_GATE} starts on {types!r}; expected {PULL_REQUEST_TYPES!r}"
    )


def test_the_gate_is_reusable_and_measures_every_main_commit() -> None:
    """Release automation can call the gate, and every commit on main runs it.

    Both the merge candidate and the landed commit receive full proof;
    Release Please waits on the landed commit's run.

    Mutation proof: dropping the ``push`` trigger makes this fail on the
    missing main push; restoring it makes this pass.
    """
    triggers = _triggers()
    push = triggers.get("push")
    assert isinstance(push, dict), f"{Workflow.MERGE_GATE} does not run on push"
    assert cast("dict[object, object]", push).get("branches") == ["main"]
    assert "workflow_call" in triggers
    assert "workflow_dispatch" in triggers


#: The repository the pull requests below are opened against.
_HOME = "owner/repo"

#: ``(label, event, payload, jobs that must run)``. Every other measuring job
#: must skip.
_SCENARIOS: tuple[tuple[str, str, dict[str, object], frozenset[str]], ...] = (
    ("push to main", "push", {}, FULL_JOBS),
    ("dispatch", "workflow_dispatch", {}, FULL_JOBS),
    (
        "ready pull request opened",
        "pull_request",
        {"action": "opened", "draft": False, "head": _HOME},
        FULL_JOBS,
    ),
    (
        "ready pull request reopened",
        "pull_request",
        {"action": "reopened", "draft": False, "head": _HOME},
        FULL_JOBS,
    ),
    (
        "draft marked ready",
        "pull_request",
        {"action": "ready_for_review", "draft": False, "head": _HOME},
        FULL_JOBS,
    ),
    (
        "push to a ready pull request",
        "pull_request",
        {"action": "synchronize", "draft": False, "head": _HOME},
        FULL_JOBS,
    ),
    (
        "draft opened",
        "pull_request",
        {"action": "opened", "draft": True, "head": _HOME},
        frozenset(),
    ),
    (
        "push to a draft",
        "pull_request",
        {"action": "synchronize", "draft": True, "head": _HOME},
        frozenset(),
    ),
    (
        "draft pressed ci:full",
        "pull_request",
        {"action": "labeled", "label": "ci:full", "draft": True, "head": _HOME},
        FULL_JOBS,
    ),
    (
        "ready pressed ci:full",
        "pull_request",
        {"action": "labeled", "label": "ci:full", "draft": False, "head": _HOME},
        FULL_JOBS,
    ),
    (
        "unrelated label",
        "pull_request",
        {"action": "labeled", "label": "docs", "draft": False, "head": _HOME},
        frozenset(),
    ),
    (
        "fork pull request",
        "pull_request",
        {"action": "opened", "draft": False, "head": "stranger/repo"},
        frozenset(),
    ),
    (
        "push to a fork's pull request",
        "pull_request",
        {"action": "synchronize", "draft": False, "head": "stranger/repo"},
        frozenset(),
    ),
    (
        "Dependabot's pull request opened",
        "pull_request",
        {"action": "opened", "draft": False, "head": _HOME, "author": "CONTRIBUTOR"},
        frozenset(),
    ),
    (
        "push to Dependabot's pull request",
        "pull_request",
        {
            "action": "synchronize",
            "draft": False,
            "head": _HOME,
            "author": "CONTRIBUTOR",
        },
        frozenset(),
    ),
    (
        "a collaborator pressed ci:full on Dependabot's pull request",
        "pull_request",
        {
            "action": "labeled",
            "label": "ci:full",
            "draft": False,
            "head": _HOME,
            "author": "CONTRIBUTOR",
        },
        frozenset(),
    ),
    (
        "the release App's pull request opened",
        "pull_request",
        {
            "action": "opened",
            "draft": False,
            "head": _HOME,
            "author": "NONE",
            "login": RELEASE_BOT,
        },
        FULL_JOBS,
    ),
    (
        "the release App pushed to its pull request",
        "pull_request",
        {
            "action": "synchronize",
            "draft": False,
            "head": _HOME,
            "author": "NONE",
            "login": RELEASE_BOT,
        },
        FULL_JOBS,
    ),
    (
        "the release App labelled its pull request",
        "pull_request",
        {
            "action": "labeled",
            "label": "autorelease: pending",
            "draft": False,
            "head": _HOME,
            "author": "NONE",
            "login": RELEASE_BOT,
            "sender": "Bot",
        },
        frozenset(),
    ),
    (
        "the default token's pull request opened",
        "pull_request",
        {
            "action": "opened",
            "draft": False,
            "head": _HOME,
            "author": "CONTRIBUTOR",
            "login": "github-actions[bot]",
        },
        frozenset(),
    ),
    (
        "a fork's branch named like the release App's",
        "pull_request",
        {
            "action": "opened",
            "draft": False,
            "head": "stranger/repo",
            "author": "NONE",
            "login": RELEASE_BOT,
        },
        frozenset(),
    ),
    (
        "a bot pressed ci:full",
        "pull_request",
        {
            "action": "labeled",
            "label": "ci:full",
            "draft": False,
            "head": _HOME,
            "sender": "Bot",
        },
        frozenset(),
    ),
)


def _bindings(payload: dict[str, object]) -> dict[str, object]:
    """Return the context references a pull request *payload* resolves.

    The author defaults to the owner and the sender to a user, the ordinary
    case; the Dependabot, bot and release App scenarios override them.
    """
    return {
        "github.repository": _HOME,
        "github.event.action": payload.get("action", ""),
        "github.event.label.name": payload.get("label", ""),
        "github.event.pull_request.draft": payload.get("draft", False),
        "github.event.pull_request.head.repo.full_name": payload.get("head", ""),
        "github.event.pull_request.author_association": payload.get("author", "OWNER"),
        "github.event.pull_request.user.login": payload.get("login", "someone"),
        "github.event.sender.type": payload.get("sender", "User"),
        "github.ref_name": payload.get("ref_name", "feature"),
    }


@pytest.mark.parametrize(
    ("event", "payload", "expected"),
    [(event, payload, expected) for _, event, payload, expected in _SCENARIOS],
    ids=[label for label, *_ in _SCENARIOS],
)
def test_pull_request_state_selects_the_cost_tier(
    event: str, payload: dict[str, object], expected: frozenset[str]
) -> None:
    """Drafts run nothing; every ready head runs everything automatically.

    Mutation proof: replacing the ``tests`` job's draft comparison with
    ``true`` made the draft cases fail naming ``tests``. Removing
    ``synchronize`` from the full condition fails the push case naming the
    missing full jobs; restoration passes.
    """
    running = {
        job_id
        for job_id, body in _jobs().items()
        if job_id != GATE_JOB
        and workflows.evaluate(str(body.get("if") or "true"), event, _bindings(payload))
        is workflows.TRUE
    }
    assert running == expected, f"runs {sorted(running)}, expected {sorted(expected)}"


def test_the_gate_needs_every_measuring_job_and_skips_only_a_draft() -> None:
    """The required check cannot skip a failure, and skips nothing but a draft.

    A skipped required check counts as passed. A draft cannot merge, so its
    skip is harmless; on any other occasion a skip would pass a commit nothing
    measured, so the gate must run there - including after a cancellation,
    which is what ``always()`` buys.

    Mutation proof: deleting the draft clause made the draft cases fail as
    reachable; replacing ``always()`` with ``success()`` failed the prefix
    check; restoring each made this pass.
    """
    jobs = _jobs()
    gate = jobs.get(GATE_JOB)
    assert isinstance(gate, dict)
    raw = cast("dict[object, object]", gate)
    assert raw.get("name") == GATE_NAME_EXPRESSION
    needs = raw.get("needs")
    needed: set[str] = (
        set(cast("list[str]", needs)) if isinstance(needs, list) else set()
    )
    measuring = {str(job_id) for job_id in jobs} - {GATE_JOB}
    assert needed == measuring, (
        f"the gate needs {sorted(needed)}, but measuring jobs are {sorted(measuring)}"
    )
    condition = " ".join(str(raw.get("if") or "").split())
    assert condition.startswith("always() &&"), (
        f"the gate runs under {condition!r}; a cancelled run must still reach it"
    )
    findings: list[str] = []
    for label, event, payload, _expected in _SCENARIOS:
        verdict = workflows.evaluate(condition, event, _bindings(payload))
        untrusted = event == "pull_request" and (
            payload.get("head") != _HOME
            or (
                payload.get("author", "OWNER") not in {"OWNER", "COLLABORATOR"}
                and payload.get("login") != RELEASE_BOT
            )
        )
        skips = untrusted or (
            payload.get("draft") is True and payload.get("label") != "ci:full"
        )
        if skips and verdict is not workflows.FALSE:
            findings.append(f"{label}: the gate runs on a draft ({verdict})")
        if not skips and verdict is workflows.FALSE:
            findings.append(f"{label}: the gate skips, which passes the commit")
    assert not findings, "\n".join(findings)


def test_the_gate_runs_every_check_on_every_platform() -> None:
    """A ready pull request can reach every required recipe and platform."""
    running = _platforms_by_recipe("pull_request")
    findings = [
        f"`just {recipe}` runs on {sorted(running.get(recipe, set()))}, "
        f"expected {sorted(platforms)}"
        for recipe, platforms in sorted(GATE_RECIPES.items())
        if not platforms <= running.get(recipe, set())
    ]
    assert not findings, "The merge gate lost required coverage.\n\n" + "\n".join(
        findings
    )


def test_pr_verdict_requires_full_proof() -> None:
    """Light or skipped jobs cannot authorize a PR head.

    Mutation proof: restoring light-lint authorization fails the light-verdict
    assertion; deleting the historical measured-job check fails the prior-proof
    assertion. Restoration after each mutation passes.
    """
    script = next(
        str(step["run"])
        for step in _jobs()[GATE_JOB]["steps"]
        if step.get("name") == "Every full check passed on this commit"
    )
    assert '${LIGHT}" = "success"' not in script, (
        "light lint must never authorize the merge gate"
    )
    assert 'if require_full_run "$run"; then' in script
    assert 'if [ "$previous" != "success" ]; then' in script
    assert 'if [ "$proof" -ne 2 ]; then' in script
    assert "status=completed&per_page=100" in script
    assert "if (count && !measured) exit 2" in script
    assert "sort -t $'\\t' -k1,1nr" in script
    assert 'if ($4 != "success") failed=1' in script
    assert "exit(failed || count != 8)" in script
    assert "jobs?filter=all&per_page=100" in script
    assert "jobs=$(gh api --paginate " in script
    assert "sort -t $'\\t' -k1,1 -k2,2nr -k3,3nr" in script
    # Reading the history without a tab separator failed this assertion;
    # restoration passed.
    assert "while IFS=$'\\t' read -r run previous; do" in script


def test_dispatch_cannot_select_partial_merge_proof() -> None:
    """Restoring a scope input or light job fails admission."""
    for event in ("workflow_dispatch", "workflow_call"):
        trigger = _triggers()[event]
        assert isinstance(trigger, dict)
        inputs = cast("dict[object, object]", trigger)["inputs"]
        assert isinstance(inputs, dict)
        assert set(cast("dict[object, object]", inputs)) == {"ref"}
    assert "lint-light" not in _jobs()


def test_every_dispatch_requires_the_exact_commit_devserver_proof() -> None:
    """A feature-branch dispatch cannot bypass frontend verification."""
    name = "Require the dev server proof on this exact commit"
    step = next(step for step in _jobs()[GATE_JOB]["steps"] if step.get("name") == name)
    assert (
        workflows.evaluate(
            str(step["if"]),
            "workflow_dispatch",
            {"github.ref_name": "feature"},
        )
        is workflows.TRUE
    )


def test_a_dispatch_ref_that_is_not_a_commit_sha_is_refused() -> None:
    """The proof names the commit the measuring jobs checked out, or nothing.

    Mutation proof: restoring the fallback that replaced a non-SHA ref with
    ``GITHUB_SHA`` fails the refusal assertion; restoring the refusal passes.
    """
    name = "Require the dev server proof on this exact commit"
    step = next(step for step in _jobs()[GATE_JOB]["steps"] if step.get("name") == name)
    assert "inputs.ref" in str(step["env"]["PROOF_SHA"])
    run = str(step["run"])
    guard = run[: run.index("for _ in")]
    assert '[[ "$PROOF_SHA" =~ ^[0-9a-f]{40}$ ]]' in guard
    # The non-SHA branch must fail; any reassignment would prove another commit.
    assert "exit 1" in guard
    assert "PROOF_SHA=" not in guard


@pytest.mark.parametrize("author", ["CONTRIBUTOR", "NONE", "FIRST_TIMER"])
@pytest.mark.parametrize("head", [_HOME, "stranger/repo"])
def test_untrusted_pull_requests_never_run_even_with_a_full_label(
    author: str, head: str
) -> None:
    """Removing author admission fails a named measuring-job assertion."""
    payload: dict[str, object] = {
        "action": "labeled",
        "label": "ci:full",
        "head": head,
        "author": author,
        "draft": False,
    }
    for job_id, body in _jobs().items():
        assert (
            workflows.evaluate(str(body["if"]), "pull_request", _bindings(payload))
            is workflows.FALSE
        ), f"untrusted PR reaches {job_id}"
    withheld = GATE_NAME_EXPRESSION.removeprefix("${{ ").split(
        " && 'Admission withheld (Linux)'", 1
    )[0]
    assert (
        workflows.evaluate(withheld, "pull_request", _bindings(payload))
        is workflows.TRUE
    ), "a skipped external PR must not report the required context"


@pytest.mark.parametrize("job_id", ["tests", "tests-windows"])
def test_lifecycle_suites_receive_the_compiled_monitor(job_id: str) -> None:
    """Removing native compilation fails admission before the test suite.

    Mutation proof: removing each job's build recipe independently failed the
    missing-producer assertion (exit 1); restoration passed (exit 0).
    Restoring the Windows operator-service init recipe failed dependency
    admission (exit 1); exact restoration passed the 26-case suite (exit 0).
    """
    steps = _jobs()[job_id]["steps"]
    runs = [step.get("run") for step in steps]
    assert "just build-monitor" in runs, f"{job_id} has no compiled producer"
    assert "npm ci" in runs, f"{job_id} does not restore the committed dependencies"
    assert "just init-monitor" not in runs, f"{job_id} mutates operator dev services"
    assert runs.index("just build-monitor") < runs.index("just test-python")


@pytest.mark.parametrize(
    ("author", "login"),
    [("OWNER", "someone"), ("COLLABORATOR", "someone"), ("NONE", RELEASE_BOT)],
)
def test_trusted_pull_requests_report_the_required_context(
    author: str, login: str
) -> None:
    """A trusted author's gate, the release App's included, is the required one.

    Mutation proof: dropping the release App's term from the gate's ``name:``
    in ``merge-gate.yml`` and from ``GATE_NAME_EXPRESSION`` together made the
    release App case fail on this assertion; restoring both made it pass.
    """
    payload: dict[str, object] = {
        "action": "opened",
        "head": _HOME,
        "author": author,
        "login": login,
        "draft": False,
    }
    gate = _jobs()[GATE_JOB]
    withheld = (
        str(gate["name"])
        .removeprefix("${{ ")
        .split(" && 'Admission withheld (Linux)'", 1)[0]
    )
    assert (
        workflows.evaluate(withheld, "pull_request", _bindings(payload))
        is workflows.FALSE
    ), f"a pull request by {login} ({author}) reports the withheld context"
