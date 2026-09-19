"""The accelerator tiers are defined once and provision what they read.

The MPS and CUDA tiers refuse to run when a precondition is missing: an empty
model cache, no Hugging Face token, no pinned Qdrant binary, or no resident
service to borrow. A refusal fails the job, and the release requires the job,
so a tier copied into a second workflow without its provisioning steps blocks
every release while measuring nothing.

So the tiers have exactly one home, every job running one provisions its
preconditions before it, and every caller hands that home the token.
"""

from __future__ import annotations

from typing import cast

import pytest

from dev.ci_names import Workflow
from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: The step that fills the model cache.
WARM = "just warm-models"

#: The recipes that need an accelerator, and the steps that must precede them
#: in the same job, each identified by a fragment of its ``run:``.
PRECONDITIONS = {
    "test-mps": (WARM,),
    "test-gpu": (
        "server qdrant install",
        WARM,
        "server start",
    ),
}

#: The secret the model-cache warm-up reads.
TOKEN = "HF_TOKEN"


def _workflow_names() -> list[str]:
    """Return every workflow file name."""
    directory = workflows.repository_root() / ".github" / "workflows"
    return sorted(path.name for path in directory.glob("*.yml"))


def _run(step: dict[str, object]) -> str:
    """Return a step's ``run:`` text, or an empty string."""
    run = step.get("run")
    return run if isinstance(run, str) else ""


def _reads_token(step: dict[str, object]) -> bool:
    """Whether *step* hands the job the Hugging Face token from a secret."""
    env = step.get("env")
    if not isinstance(env, dict):
        return False
    value = cast("dict[object, object]", env).get(TOKEN)
    return isinstance(value, str) and f"secrets.{TOKEN}" in value


def test_accelerator_recipes_live_only_in_the_hardware_workflow() -> None:
    """No workflow but the hardware one runs an accelerator tier itself.

    Mutation proof: adding a ``just test-gpu`` step to ``ci.yml``'s ``lint``
    job makes this fail naming ``ci.yml:lint``; removing it makes this pass.
    """
    elsewhere = [
        f"{workflow}:{job.job_id} runs `just {recipe}`"
        for workflow in _workflow_names()
        if workflow != Workflow.HARDWARE
        for job in workflows.load_jobs(workflow)
        for _, recipe in job.recipes()
        if recipe in PRECONDITIONS
    ]
    assert not elsewhere, (
        f"An accelerator tier is defined outside {Workflow.HARDWARE}; call that "
        "workflow instead.\n\n" + "\n".join(elsewhere)
    )


def test_every_tier_provisions_its_preconditions_first() -> None:
    """Each accelerator step is preceded by every step it depends on.

    Mutation proof: deleting the CUDA job's Qdrant provisioning step makes
    this fail naming ``server qdrant install``; restoring it makes this pass.
    """
    findings: list[str] = []
    seen: set[str] = set()
    for job in workflows.load_jobs(Workflow.HARDWARE):
        runs = [_run(step) for step in job.steps]
        for index, step in enumerate(job.steps):
            for recipe, needed in PRECONDITIONS.items():
                if f"just {recipe}" not in _run(step):
                    continue
                seen.add(recipe)
                earlier = job.steps[:index]
                findings.extend(
                    f"{job.job_id}: `just {recipe}` has no earlier `{fragment}` step"
                    for fragment in needed
                    if not any(fragment in text for text in runs[:index])
                )
                if not any(
                    WARM in _run(prior) and _reads_token(prior) for prior in earlier
                ):
                    findings.append(
                        f"{job.job_id}: the cache warm-up before `just {recipe}` "
                        f"does not read {TOKEN} from a secret"
                    )
    missing = sorted(set(PRECONDITIONS) - seen)
    assert not missing, f"{Workflow.HARDWARE} no longer runs {missing}"
    assert not findings, (
        "An accelerator tier runs before its preconditions exist, so it "
        "refuses and fails every caller.\n\n" + "\n".join(findings)
    )


def test_the_cuda_tier_always_stops_the_service_it_started() -> None:
    """A failed borrow never leaves a daemon holding the card.

    Mutation proof: removing ``if: always()`` from the stop step makes this
    fail; restoring it makes this pass.
    """
    stops = [
        step
        for job in workflows.load_jobs(Workflow.HARDWARE)
        if any("just test-gpu" in _run(step) for step in job.steps)
        for step in job.steps
        if "server stop" in _run(step)
    ]
    assert stops, f"the CUDA tier in {Workflow.HARDWARE} never stops its service"
    assert all(step.get("if") == "always()" for step in stops), (
        "the service stop does not run when the tier fails"
    )


def test_every_caller_hands_the_hardware_workflow_its_token() -> None:
    """The token is declared by the tiers and passed by every caller.

    A reusable workflow sees no secret its caller does not pass, so a caller
    that omits it warms nothing and the tier refuses.

    Mutation proof: deleting the ``secrets:`` block from ``publish.yml``'s
    hardware job makes this fail naming ``publish.yml``; restoring it makes
    this pass.
    """
    document = workflows.document(Workflow.HARDWARE)
    # YAML 1.1 reads a bare `on` key as the boolean True.
    triggers = document.get("on", document.get(True))
    call = (
        cast("dict[object, object]", triggers).get("workflow_call")
        if isinstance(triggers, dict)
        else None
    )
    declared = (
        cast("dict[object, object]", call).get("secrets")
        if isinstance(call, dict)
        else None
    )
    assert isinstance(declared, dict) and TOKEN in declared, (
        f"{Workflow.HARDWARE} does not declare the {TOKEN} secret"
    )

    target = f"./.github/workflows/{Workflow.HARDWARE}"
    callers: list[str] = []
    missing: list[str] = []
    for workflow in _workflow_names():
        jobs = workflows.document(workflow).get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_id, body in cast("dict[object, object]", jobs).items():
            if not isinstance(body, dict):
                continue
            job = cast("dict[object, object]", body)
            if job.get("uses") != target:
                continue
            callers.append(f"{workflow}:{job_id}")
            secrets = job.get("secrets")
            passed = (
                cast("dict[object, object]", secrets).get(TOKEN)
                if isinstance(secrets, dict)
                else secrets
            )
            if not (passed == "inherit" or f"secrets.{TOKEN}" in str(passed)):
                missing.append(f"{workflow}:{job_id}")
    assert callers, f"nothing calls {Workflow.HARDWARE}"
    assert not missing, f"callers that do not pass {TOKEN}: {missing}"


def test_no_windows_step_hands_powershell_a_heredoc() -> None:
    """A Windows step never carries bash-only syntax into PowerShell.

    A Windows runner's default step shell is PowerShell, which rejects a
    ``<<`` heredoc as a parse error before anything runs.

    Mutation proof: replacing the CUDA job's ``just warm-models`` with a
    ``uv run --no-sync python - <<'PY'`` block makes this fail naming that
    step; restoring the recipe makes this pass.
    """
    offenders = [
        f"{workflow}:{job.job_id}:{step.get('name', '<unnamed>')}"
        for workflow in _workflow_names()
        for job in workflows.load_jobs(workflow)
        if "windows" in job.platforms
        for step in job.steps
        if "<<" in _run(step) and step.get("shell") != "bash"
    ]
    assert not offenders, (
        f"Windows steps pass a heredoc to PowerShell: {offenders}. Use a recipe."
    )


def test_the_cuda_tier_checks_out_full_history() -> None:
    """The CUDA tier can read the frozen ranking corpus.

    The ranking-quality gates extract ``.vault/`` at a pinned historical
    commit with ``git archive``. A shallow checkout lacks that commit, and
    every one of those gates errors before measuring anything.

    Mutation proof: deleting ``fetch-depth: 0`` from the CUDA job's checkout
    makes this fail; restoring it makes this pass.
    """
    checkouts = [
        step
        for job in workflows.load_jobs(Workflow.HARDWARE)
        if any("just test-gpu" in _run(step) for step in job.steps)
        for step in job.steps
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts, f"the CUDA tier in {Workflow.HARDWARE} checks nothing out"
    depths = [
        cast("dict[object, object]", step.get("with") or {}).get("fetch-depth")
        for step in checkouts
    ]
    assert depths == [0] * len(checkouts), (
        f"the CUDA tier checks out with fetch-depth {depths}; the frozen "
        "ranking corpus needs full history"
    )
