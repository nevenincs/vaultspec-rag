"""The declarative registry of development verbs and their targets.

This module is the single source of truth for what the harness can do. The
justfile exposes each verb; everything about *what a target runs*, whether it
gates, and how targets compose into aggregates is stated here as data.

The verbs split by CONSEQUENCE, not by tool:

``deps``
    MUTATES the environment. Deliberately does not go through ``--no-sync``.
``lint``
    GATES. Read-only, and a finding fails the build.
``fix``
    MUTATES. Everything automatically repairable, in one pass.
``audit``
    Only ``deps`` gates. Every other target is advisory and exits 0 even with
    findings, because each yields a lead to confirm rather than a verdict.
``test``
    GATES. See :data:`TEST` for what each lane proves.
``build``
    Produces distribution artifacts.
``health``
    MEASURES. Always exits 0.

Every target below was previously a ``case`` inside a backslash-joined
PowerShell ``switch`` in the justfile. Their own comments warned three separate
times that a ``#`` inside such a block silently swallows every case after it,
including the closing braces - a hazard that exists only because the logic was
in the wrong file. Stating the toolchain as data removes the hazard rather than
documenting it.
"""

from __future__ import annotations

from dataclasses import dataclass

from dev.gates import CUDA_GATE, MPS_GATE, PERF_GATE, Gate
from dev.runner import (
    Cmd,
    Echo,
    Ref,
    Step,
    ToolOrDocker,
    ToolOrSkip,
    dev_module,
    uv_run,
)

#: The shipped package. Every production-scoped scan is rooted here.
PACKAGE = "src/vaultspec_rag"

#: The package's import name, used where a tool resolves modules from ``src``
#: rather than from the repository root.
MODULE = "vaultspec_rag"

#: Python trees carrying committed source, and therefore linted.
#:
#: ``tools`` joins the package because it holds the release binary builder and
#: the Scoop/Homebrew generators, where a break fails a release rather than a
#: test. Both were outside this gate when a generator naming a product that
#: does not exist, and a builder invoked so it could not import its own
#: package, reached main with CI green.
#:
#: ``dev`` joins them because a harness that is not itself linted is the one
#: place a convention can quietly stop applying.
PYTHON_PATHS = ("src", "tools", "dev")

#: Markdown trees checked and formatted.
MARKDOWN_PATHS = ("README.md", ".vaultspec/", ".vault/")

#: Link-checked trees.
LINK_PATHS = ("README.md", ".vault", ".vaultspec")

#: Pinned images backing the native binaries that cannot live in the lockfile.
TAPLO_IMAGE = "tamasfe/taplo:0.9"
LYCHEE_IMAGE = "lycheeverse/lychee:latest"

#: Duplication-detector thresholds. jscpd's own defaults (5 lines / 50 tokens)
#: report formatting coincidences; 20 lines with 70 tokens is the threshold at
#: which a clone is a maintenance liability rather than a similarity.
JSCPD = ("--min-lines", "20", "--min-tokens", "70", "--reporters", "console")

#: Markers that require real infrastructure or a real accelerator.
#:
#: This is the exact set ``conftest.py``'s own ``pytest_runtestloop`` guard
#: checks before requiring ``HF_TOKEN``, plus ``cuda`` and ``mps`` for tests
#: targeting one real accelerator without the shared CUDA model fixtures.
#: Excluding only ``integration`` once let a quality/performance/robustness/
#: subprocess_gpu/cuda test slip through gateless and hard-abort the recipe on
#: a GPU-less runner; matching conftest's own set is the durable fix, because a
#: newly-added GPU-marked test is then excluded automatically.
NEEDS_REAL_INFRA = (
    "integration",
    "quality",
    "performance",
    "robustness",
    "subprocess_gpu",
    "cuda",
    "mps",
)

#: The marker expression selecting every lane runnable without an accelerator.
CPU_ONLY = f"not ({' or '.join(NEEDS_REAL_INFRA)})"


@dataclass(frozen=True)
class Target:
    """One selectable behaviour within a verb.

    Args:
        name: The target token typed on the command line.
        summary: One-line description shown by ``help``.
        steps: The steps to run, in order.
        advisory: When true the target reports findings but always exits 0.
        keep_going: When true a failing step does not stop the remaining steps.
            Aggregate dashboards set this so one red dimension does not hide
            every dimension after it.
        gate: A precondition that must hold before this target runs at all.
            When it does not, the target is REPORTED as skipped and counted,
            never quietly omitted.
        lane: When true this is a pytest lane, so pytest's exit status 5 ("no
            tests were collected") counts as a visible skip rather than a pass.
        aggregate: When true this target summarises the targets it references
            and fails when every one of them was skipped.
    """

    name: str
    summary: str
    steps: tuple[Step, ...]
    advisory: bool = False
    keep_going: bool = False
    gate: Gate | None = None
    lane: bool = False
    aggregate: bool = False


@dataclass(frozen=True)
class Verb:
    """A top-level harness verb and the targets it dispatches to.

    Args:
        name: The verb token, matching the justfile recipe name.
        summary: One-line description of the verb.
        targets: The selectable targets, in display order.
        note: Optional extra paragraph appended to the verb's ``help`` output.
    """

    name: str
    summary: str
    targets: tuple[Target, ...]
    note: str = ""

    def find(self, name: str) -> Target | None:
        """Return the named target, or ``None`` when it is not defined."""
        return next((t for t in self.targets if t.name == name), None)


def public_targets(verb: Verb) -> tuple[str, ...]:
    """Return the target tokens a user may type, in display order."""
    return tuple(t.name for t in verb.targets if not t.name.startswith("_"))


def _verb(verb: str, target: str) -> Cmd:
    """Build a command that re-enters this harness at another verb.

    :class:`Ref` composes targets WITHIN one verb. An aggregate that spans
    verbs - only ``ci`` does - re-enters through the documented entry point
    rather than reaching into another verb's internals, so it cannot bypass
    that verb's own advisory-versus-gating decision.
    """
    return uv_run("python", "-m", "dev", verb, target)


def _advisory(finding_exit: int, *argv: str) -> Cmd:
    """Wrap a scanner so its FINDINGS do not gate but its BREAKAGE does.

    Marking a target ``advisory`` maps every non-zero status onto success,
    which also swallows a bad config, an unparsable file, and a scanner that is
    not installed at all - a dimension that has stopped running then looks
    exactly like a clean one. ``tools/advisory.py`` maps only the scanner's own
    findings-exit-code onto success and propagates everything else, so the
    targets below carry no blanket ``advisory`` flag.

    Args:
        finding_exit: The status this scanner uses to mean "I found something".
            vulture uses 3; most others use 1.
        *argv: The scanner command line.

    Returns:
        The corresponding :class:`Cmd`.
    """
    return uv_run(
        "python", "tools/advisory.py", "--finding-exit", str(finding_exit), "--", *argv
    )


def _pytest(*argv: str) -> Cmd:
    """Run pytest against the library test tree."""
    return uv_run("pytest", f"{PACKAGE}/tests/", *argv)


# ---------------------------------------------------------------------------
#  deps
# ---------------------------------------------------------------------------

DEPS = Verb(
    name="deps",
    summary="Manage project dependencies and the lockfile.",
    note=(
        "These targets deliberately do NOT go through 'uv run --no-sync': "
        "changing the environment is their whole purpose."
    ),
    targets=(
        Target(
            "sync",
            "Resolve the development environment from the lock.",
            (Cmd(("uv", "sync", "--locked", "--group", "dev")),),
        ),
        Target(
            "upgrade",
            "Re-resolve every group to the newest permitted versions.",
            (Cmd(("uv", "sync", "--upgrade", "--all-groups")),),
        ),
        Target(
            "lock",
            "Refresh the lockfile without changing the environment.",
            (Cmd(("uv", "lock")),),
        ),
        Target(
            "lock-upgrade",
            "Refresh the lockfile, raising pins where permitted.",
            (Cmd(("uv", "lock", "--upgrade")),),
        ),
    ),
)


# ---------------------------------------------------------------------------
#  lint
# ---------------------------------------------------------------------------

#: The dimensions ``lint all`` chains, in order. Stated once, as data, so a
#: target cannot exist without being part of the aggregate that claims to run
#: everything - which is exactly what a hand-repeated chain of `just check-<dimension>`
#: calls could not guarantee.
LINT_ALL = (
    "python",
    "type",
    "links",
    "toml",
    "markdown",
    "workflow",
    "absolute-imports",
    "complexity",
    "nesting",
    "size",
    "docs-version",
    "citations",
    "type-strict",
)

LINT = Verb(
    name="lint",
    summary="Run gating static analysis; a finding fails the build.",
    note=(
        "The complexity gate measures PRODUCTION code; the test tree is measured "
        "by 'audit complexity', which reports without failing. That split is not "
        "a concession: the worst scores in this tree belong to guard tests that "
        "walk the AST of every module to prove a structural invariant, and "
        "branch count and nesting are what those tests ARE."
    ),
    targets=(
        Target(
            "python",
            "Check style and formatting (ruff).",
            (
                uv_run("ruff", "check", *PYTHON_PATHS),
                uv_run("ruff", "format", "--check", *PYTHON_PATHS),
            ),
        ),
        Target(
            "type",
            "Check types across the package and the release tooling.",
            (uv_run("python", "-m", "ty", "check", *PYTHON_PATHS),),
        ),
        Target(
            "type-strict",
            "Check types under the strict profile (basedpyright).",
            (uv_run("basedpyright"),),
        ),
        Target(
            "links",
            "Check every documentation link resolves.",
            (
                ToolOrDocker(
                    tool="lychee",
                    argv=("--config", "lychee.toml", *LINK_PATHS),
                    image=LYCHEE_IMAGE,
                    docker_argv=("--config", "/repo/lychee.toml", *LINK_PATHS),
                ),
            ),
        ),
        Target(
            "toml",
            "Check TOML formatting (taplo, or its pinned image).",
            (
                ToolOrDocker(
                    tool="taplo",
                    argv=("lint", "*.toml"),
                    image=TAPLO_IMAGE,
                ),
            ),
        ),
        Target(
            "markdown",
            "Check markdown formatting and structure.",
            (
                uv_run("mdformat", "--check", *MARKDOWN_PATHS),
                uv_run(
                    "pymarkdown",
                    "--config",
                    ".pymarkdown.json",
                    "scan",
                    "-r",
                    *MARKDOWN_PATHS,
                ),
            ),
        ),
        Target(
            "workflow",
            "Lint the workflows, then hold them to the CI/justfile contract.",
            (
                # Two questions about the same artifacts. actionlint asks
                # whether the YAML is well-formed and its expressions resolve;
                # the contract asks whether a `run:` step is calling a recipe
                # or re-implementing one. A workflow can be perfectly valid
                # YAML and still install `just` by hand-rolled pwsh download.
                uv_run("python", "-m", "dev.actionlint"),
                uv_run("python", "-m", "dev.ci_contract"),
            ),
        ),
        Target(
            "complexity",
            "Gate production cyclomatic and cognitive complexity.",
            (dev_module("complexity", "gate"),),
        ),
        Target(
            "nesting",
            "Gate nesting depth (PLR1702, preview-scoped).",
            (uv_run("ruff", "check", "src", "--select", "PLR1702", "--preview"),),
        ),
        Target(
            "size",
            "Gate module length and class design limits.",
            (
                uv_run(
                    "pylint",
                    PACKAGE,
                    "--rcfile=pyproject.toml",
                    "--recursive=y",
                    "--score=n",
                ),
            ),
        ),
        Target(
            "docs-version",
            "Check the documented version matches the packaged one.",
            (uv_run("python", "tools/check_docs_version.py"),),
        ),
        Target(
            "citations",
            "Check every citation resolves to a real source.",
            (uv_run("python", "tools/citation_gate.py"),),
        ),
        Target(
            "absolute-imports",
            "Check the package uses absolute imports throughout.",
            (uv_run("python", "tools/absolute_import_gate.py"),),
        ),
        Target(
            "all",
            "Run every gating dimension; one red dimension never hides the rest.",
            tuple(Ref(name) for name in LINT_ALL),
            keep_going=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
#  fix
# ---------------------------------------------------------------------------

FIX = Verb(
    name="fix",
    summary="Apply every available formatter and automatic fix.",
    targets=(
        Target(
            "python",
            "Format and auto-fix Python (ruff).",
            (
                uv_run("ruff", "format", *PYTHON_PATHS),
                uv_run("ruff", "check", "--fix", *PYTHON_PATHS),
            ),
        ),
        Target(
            "toml",
            "Format TOML (taplo, or its pinned image).",
            (
                ToolOrDocker(
                    tool="taplo",
                    argv=("fmt", "*.toml"),
                    image=TAPLO_IMAGE,
                ),
            ),
        ),
        Target(
            "markdown",
            "Format and repair markdown.",
            (
                uv_run("mdformat", *MARKDOWN_PATHS),
                uv_run(
                    "pymarkdown",
                    "--config",
                    ".pymarkdown.json",
                    "fix",
                    "-r",
                    *MARKDOWN_PATHS,
                ),
            ),
        ),
        Target(
            "vault",
            "Reconcile and format this checkout's own .vault/ corpus.",
            (uv_run("vaultspec-core", "vault", "check", "all", "--fix"),),
        ),
        Target(
            "all",
            "Apply every automatic fix, in one pass.",
            (Ref("python"), Ref("toml"), Ref("markdown"), Ref("vault")),
            keep_going=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
#  audit
# ---------------------------------------------------------------------------

AUDIT = Verb(
    name="audit",
    summary="Audit dependencies and code quality; only 'deps' gates.",
    note=(
        "'deps' GATES: a published advisory against a pinned version is a "
        "verdict, not a lead. Every other target is ADVISORY and exits 0 even "
        "with findings, because each yields a lead to confirm - vulture infers "
        "reachability it cannot always see, bandit reports this project's "
        "deliberate subprocess design alongside anything real, and deptry "
        "reports imports that resolve transitively. Promote a dimension into "
        "'lint' once its finding count reaches zero and the gate can hold that "
        "line."
    ),
    targets=(
        # The gate resolves every pinned coordinate itself - out of uv.lock
        # and dependency-audit-binaries.toml, which declares the PyApp
        # bootstrapper the release binaries are built from - and queries OSV
        # for all of them, so the verdict is a property of the finding set
        # rather than of `uv audit`, a preview tool that exits 0 even when it
        # prints advisories. Accepted advisories live in
        # dependency-audit-allowlist.toml with a reason and an expiry each; an
        # expired acceptance fails the gate rather than lapsing quietly.
        Target(
            "deps",
            "Gate on published advisories against the locked versions.",
            (uv_run("python", "-m", "dev.audit.dependency_audit"),),
        ),
        Target(
            "security",
            "Scan for insecure patterns (bandit).",
            (
                _advisory(
                    1,
                    "bandit",
                    "-c",
                    "pyproject.toml",
                    "-r",
                    PACKAGE,
                    "-x",
                    f"{PACKAGE}/tests",
                    "-q",
                ),
            ),
        ),
        Target(
            "dead-code",
            "Report unreachable code (vulture).",
            (_advisory(3, "vulture"),),
        ),
        Target(
            "dependencies",
            "Report undeclared and unused dependencies (deptry).",
            (_advisory(1, "deptry", PACKAGE),),
        ),
        Target(
            "duplication",
            "Report copy-paste clones (jscpd, when npx is available).",
            (
                ToolOrSkip(
                    tool="npx",
                    argv=("--yes", "jscpd@4", PACKAGE, *JSCPD),
                    reason="the duplication scan",
                    advisory_finding_exit=1,
                ),
            ),
        ),
        Target(
            "complexity",
            "Report test-tree cognitive and cyclomatic complexity.",
            (dev_module("complexity", "audit"),),
        ),
        Target(
            "all",
            "Report every dimension; one red dimension does not hide the rest.",
            (
                Echo("=== dependency advisories ==="),
                Ref("deps"),
                Echo("=== security ==="),
                Ref("security"),
                Echo("=== dead code ==="),
                Ref("dead-code"),
                Echo("=== undeclared dependencies ==="),
                Ref("dependencies"),
                Echo("=== duplication ==="),
                Ref("duplication"),
                Echo("=== test-tree complexity ==="),
                Ref("complexity"),
            ),
            keep_going=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
#  test
# ---------------------------------------------------------------------------

TEST = Verb(
    name="test",
    summary="Run the project test suites.",
    note=(
        "'all' runs EVERY lane: python, gpu, mps and perf. The three "
        "hardware-gated lanes are probed first and, where the host cannot run "
        "one, reported by name as SKIPPED with the reason - they are never "
        "silently omitted. 'all' stops at the first lane that FAILS, and exits "
        "non-zero when every lane was skipped, because a run that proved "
        "nothing must not read as a pass. 'fast' and 'provisioning' are "
        "selections WITHIN the python lane rather than lanes of their own, so "
        "'all' does not re-run them."
    ),
    targets=(
        Target(
            "python",
            "Run every lane that needs no accelerator, in parallel.",
            # Only this lane runs parallel. `-n auto` resolves to PHYSICAL cores
            # when psutil is importable, which it always is here, and `--dist
            # loadfile` keeps a module's tests on one worker so module-scoped
            # state and the ports a file reserves stay private to it. The tier
            # is dominated by subprocess spawns and socket waits rather than by
            # CPU, so it parallelises well: 666s to 162s on a 12-core host. No
            # `-x`: a repo-health lane must report every failure, not stop at
            # the first one.
            (
                _pytest(
                    "tools",
                    "-q",
                    "-n",
                    "auto",
                    "--dist",
                    "loadfile",
                    "-m",
                    CPU_ONLY,
                ),
            ),
            lane=True,
        ),
        Target(
            "fast",
            "Run the unit tier only, stopping at the first failure.",
            (_pytest("-x", "-q", "-m", "unit"),),
        ),
        Target(
            "gpu",
            "Run the real-GPU correctness tiers, serially, on a CUDA host.",
            # TWO sequential selections, and the split is load bearing rather
            # than tidiness. A resident-model tier holds its models for the
            # length of the lane while each subprocess_gpu test spawns a service
            # that loads its own set, and the combined footprint exceeds the
            # card. Co-scheduled, the spawned service simply never becomes
            # healthy - so the failure arrives as a health-poll timeout in
            # whichever test drew the short straw, naming nothing about memory.
            (
                _pytest(
                    "-q",
                    "-m",
                    "(integration or quality or robustness or cuda) "
                    "and not performance and not subprocess_gpu",
                ),
                _pytest("-q", "-m", "subprocess_gpu"),
            ),
            lane=True,
            gate=CUDA_GATE,
        ),
        Target(
            "perf",
            "Run the latency and footprint lane; quiet machines only.",
            # A separate quiet-machine-ONLY lane: its wall-clock assertions ARE
            # the system under test, so a loaded machine fails them for reasons
            # unrelated to a regression. Never a correctness gate.
            (_pytest("-q", "-m", "performance"),),
            lane=True,
            gate=PERF_GATE,
        ),
        Target(
            "mps",
            "Run the Apple-silicon backend lane with the fallback disabled.",
            (
                Cmd(
                    uv_run(
                        "pytest",
                        f"{PACKAGE}/tests/integration/test_mps_backend.py",
                        "-q",
                        "-m",
                        "mps",
                    ).argv,
                    {"PYTORCH_ENABLE_MPS_FALLBACK": "0"},
                ),
            ),
            lane=True,
            gate=MPS_GATE,
        ),
        Target(
            "provisioning",
            "Run the environment-provisioning and readiness holders.",
            (
                uv_run(
                    "pytest",
                    *(
                        f"{PACKAGE}/tests/{name}.py"
                        for name in (
                            "test_env_holders",
                            "test_tool_env_provisioning_hostile",
                            "test_tool_torch_repair",
                            "test_torch_pin_single_source",
                            "test_readiness_holders",
                        )
                    ),
                    "-q",
                ),
            ),
        ),
        Target(
            "all",
            "Run every lane; a failed or gated lane never hides the ones after it.",
            (
                Ref("python"),
                Ref("gpu"),
                Ref("mps"),
                Ref("perf"),
            ),
            aggregate=True,
            keep_going=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
#  build
# ---------------------------------------------------------------------------

BUILD = Verb(
    name="build",
    summary="Build the distribution artifacts.",
    note=(
        "'all' builds everything this repository produces from a plain "
        "checkout, which is the wheel and the sdist. The standalone PyApp "
        "binaries and the Scoop/Homebrew channel pointers are NOT part of it: "
        "both need a released tag and a Rust target that only exist at release "
        "time, so they stay on their own recipes and are named here rather "
        "than left unmentioned."
    ),
    targets=(
        Target(
            "python",
            "Build the wheel and sdist.",
            (Cmd(("uv", "build")),),
        ),
        Target(
            "all",
            "Build every artifact producible without a release tag.",
            (Ref("python"),),
            aggregate=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
#  health
# ---------------------------------------------------------------------------

HEALTH = Verb(
    name="health",
    summary="Rank the worst offenders per dimension; always exits 0.",
    targets=(
        Target(
            "report",
            "Rank the worst offenders across every code-health dimension.",
            (uv_run("python", "tools/health_report.py"),),
            advisory=True,
        ),
        Target(
            "fast",
            "The same report, skipping the strict type check.",
            (uv_run("python", "tools/health_report.py", "--fast"),),
            advisory=True,
        ),
    ),
)


# ---------------------------------------------------------------------------
#  ci
# ---------------------------------------------------------------------------

CI = Verb(
    name="ci",
    summary="Run the full local gate: lint, dependency audit, vault, tests.",
    targets=(
        Target(
            "all",
            "Run the complete local validation baseline.",
            (
                _verb("lint", "all"),
                # `audit deps` and nothing else from the audit verb. The rest
                # of that group is advisory by construction - each finding is
                # a lead to confirm, and a pipeline that fails on a lead
                # teaches people to stop reading it. A published advisory
                # against a pinned version is not a lead, it is a verdict.
                _verb("audit", "deps"),
                uv_run("vaultspec-core", "vault", "check", "all"),
                _verb("test", "all"),
                # BUILD IS PART OF CI, and this repository is where that was
                # measured: the wheel build broke on the release path and
                # surfaced at release time, with the tag already cut. The
                # gates above prove the source is well-formed and the tests
                # pass; only this one proves the artifact a user receives can
                # still be produced from it.
                _verb("build", "all"),
            ),
        ),
    ),
)


#: Every verb this harness exposes, in display order.
VERBS: tuple[Verb, ...] = (DEPS, LINT, FIX, AUDIT, TEST, BUILD, HEALTH, CI)

#: The target each verb selects when invoked with no argument.
DEFAULTS: dict[str, str] = {
    "deps": "sync",
    "lint": "all",
    "fix": "all",
    "audit": "all",
    "test": "all",
    "build": "all",
    "health": "report",
    "ci": "all",
}


def find_verb(name: str) -> Verb | None:
    """Return the named verb, or ``None`` when it is not defined."""
    return next((v for v in VERBS if v.name == name), None)


__all__ = [
    "AUDIT",
    "BUILD",
    "CI",
    "DEFAULTS",
    "DEPS",
    "FIX",
    "HEALTH",
    "LINT",
    "TEST",
    "VERBS",
    "Target",
    "Verb",
    "find_verb",
    "public_targets",
]
