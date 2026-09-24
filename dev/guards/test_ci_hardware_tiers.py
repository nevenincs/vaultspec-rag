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

import ast
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

_LIVE_SERVICE_FIXTURES = {"live_service", "live_service_with_watch"}


def _uses_live_service(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether a test starts or consumes a model-bearing live service."""
    if any(
        argument.arg in _LIVE_SERVICE_FIXTURES
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
    ):
        return True
    for decorator in node.decorator_list:
        if not (
            isinstance(decorator, ast.Call)
            and ast.unparse(decorator.func) == "pytest.mark.usefixtures"
        ):
            continue
        if any(
            isinstance(argument, ast.Constant)
            and argument.value in _LIVE_SERVICE_FIXTURES
            for argument in decorator.args
        ):
            return True
    return any(
        isinstance(child, ast.Call)
        and (
            (
                isinstance(child.func, ast.Name)
                and child.func.id == "_live_service_context"
            )
            or (
                isinstance(child.func, ast.Attribute)
                and child.func.attr == "_live_service_context"
            )
        )
        for child in ast.walk(node)
    )


def test_live_service_consumers_run_outside_the_resident_model_tier() -> None:
    """A daemon must not load beside the resident tier's session models.

    Mutation proof: remove ``subprocess_gpu`` from a live-service test or its
    containing class/module; this guard names that test. Restore it to pass.
    """
    directory = (
        workflows.repository_root() / "src" / "vaultspec_rag" / "tests" / "integration"
    )
    unisolated: list[str] = []
    for path in directory.glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_marked = any(
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "pytestmark"
                for target in statement.targets
            )
            and "pytest.mark.subprocess_gpu" in ast.unparse(statement.value)
            for statement in tree.body
        )
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            if not _uses_live_service(node):
                continue
            function_marked = any(
                "pytest.mark.subprocess_gpu" in ast.unparse(decorator)
                for decorator in node.decorator_list
            )
            class_marked = any(
                isinstance(parent, ast.ClassDef)
                and node in parent.body
                and any(
                    "pytest.mark.subprocess_gpu" in ast.unparse(decorator)
                    for decorator in parent.decorator_list
                )
                for parent in tree.body
            )
            if not (module_marked or class_marked or function_marked):
                unisolated.append(f"{path.name}:{node.name}")
    assert not unisolated, f"live-service GPU tests in resident tier: {unisolated}"


def _workflow_names() -> list[str]:
    """Return every workflow file name."""
    directory = workflows.repository_root() / ".github" / "workflows"
    return sorted(path.name for path in directory.glob("*.yml"))


def _run(step: dict[str, object]) -> str:
    """Return a step's ``run:`` text, or an empty string."""
    run = step.get("run")
    return run if isinstance(run, str) else ""


def _reads_token(step: dict[str, object], token: str = TOKEN) -> bool:
    """Whether *step* hands the job the Hugging Face token from a secret."""
    env = step.get("env")
    if not isinstance(env, dict):
        return False
    value = cast("dict[object, object]", env).get(token)
    return isinstance(value, str) and f"secrets.{token}" in value


def test_accelerator_recipes_live_only_in_the_hardware_workflow() -> None:
    """No workflow but the hardware one runs an accelerator tier itself.

    Mutation proof: adding a ``just test-gpu`` step to the merge gate's lint
    job makes this fail naming that job; removing it makes this pass.
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


@pytest.mark.parametrize("token", [TOKEN, "VAULTSPEC_RAG_TYPESAFE_API_KEY"])
def test_every_caller_hands_the_hardware_workflow_its_token(token: str) -> None:
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
    assert isinstance(declared, dict) and token in declared, (
        f"{Workflow.HARDWARE} does not declare the {token} secret"
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
                cast("dict[object, object]", secrets).get(token)
                if isinstance(secrets, dict)
                else secrets
            )
            if not (passed == "inherit" or f"secrets.{token}" in str(passed)):
                missing.append(f"{workflow}:{job_id}")
    assert callers, f"nothing calls {Workflow.HARDWARE}"
    assert not missing, f"callers that do not pass {token}: {missing}"


def test_typesafe_secret_reaches_service_and_gpu_integration_tier() -> None:
    """Removing the GPU test's secret failed here; restoration passed.

    Restoring the retired ``$status.health.typesafe.enrolled`` check failed on
    the Typesafe state assertion; the state check was restored before passing.
    """
    job = next(
        job for job in workflows.load_jobs(Workflow.HARDWARE) if job.job_id == "cuda"
    )
    fragments = ("server start", "just test-gpu")
    indices: list[int] = []
    for fragment in fragments:
        index, step = next(
            (index, step)
            for index, step in enumerate(job.steps)
            if fragment in _run(step)
        )
        assert _reads_token(step, "VAULTSPEC_RAG_TYPESAFE_API_KEY"), fragment
        indices.append(index)
    assert indices == sorted(indices)
    start = _run(job.steps[indices[0]])
    # The service reports enrollment only as a Typesafe state; `off` is the
    # one unenrolled state, and a missing field must refuse, not pass.
    assert "$status.health.features.typesafe.state -in @($null, 'off')" in start, start
    assert job.steps[indices[0]].get("id") == "resident"
    stop = next(step for step in job.steps if "server stop" in _run(step))
    assert (
        cast("dict[str, object]", stop["env"])["RESIDENT_START_OUTCOME"]
        == "${{ steps.resident.outcome }}"
    )
    assert "$env:RESIDENT_START_OUTCOME -notin" in _run(stop)


def test_resident_service_binds_a_free_port_not_the_default() -> None:
    """The CUDA tier's resident never claims the fixed default service port.

    The GPU runner is a workstation whose own service and Qdrant can hold the
    default port, and a start that loses that race fails the whole release.

    Mutation proof: deleting the ``VAULTSPEC_RAG_PORT`` assignment from the
    resident step made this fail on the port assertion; restoring it passed.
    """
    job = next(
        job for job in workflows.load_jobs(Workflow.HARDWARE) if job.job_id == "cuda"
    )
    resident = next(step for step in job.steps if step.get("id") == "resident")
    start = _run(resident)
    probe = start.find("TcpListener]::new([System.Net.IPAddress]::Loopback, 0)")
    assign = start.find("$env:VAULTSPEC_RAG_PORT = ")
    launch = start.find("vaultspec-rag server start")
    assert -1 < probe < assign < launch, (probe, assign, launch)
    assert "--port" not in start


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
