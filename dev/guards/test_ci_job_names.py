"""Every workflow and job is named in the fleet's check-set grammar.

A workflow is ``<Product> <Purpose>`` - ``RAG Merge Gate``, ``RAG Release
Please`` - so this product's workflows group together beside its siblings'. A
job is ``<Kind>: <Subject> [(<Platform>[, <leg>])]`` - ``Check: Merge gate
(Linux)``, ``Test: Correctness suite (Linux, 3.14)`` - the grammar every
repository in the fleet uses, so a reviewer reading two products' checks reads
one vocabulary.

**Kind** is ``Check``, ``Test`` or ``Build``: the justfile's consequence
groups of the same names, so the checks and the recipe registry share a
vocabulary rather than each inventing one.

**Subject** is sentence case and says WHAT IS COVERED, never which tool covers
it. Two rules follow from that, and both were paid for:

- A tool name goes stale the day the tool changes. ``Dependency Audit (uv
  audit)`` outlived the tool in its own name - the gate resolves coordinates
  out of the lockfile and queries OSV directly, and has not called ``uv
  audit`` for some time - so the merge box named a command that no longer
  runs. The forbidden set is DERIVED from the toolchain rather than typed
  here, so a tool swapped tomorrow is forbidden tomorrow.

- A marker name is not a subject either. ``broad`` reads as a description and
  is a pytest selector; a reader who does not know the marker vocabulary
  learns nothing, and one who does goes looking for a lane by that name. The
  forbidden set is derived from the registered markers.

**Platform** is the operating system the job lands on, optionally followed by
the matrix leg, and is the only parenthesis permitted. A job that only calls a
reusable workflow names no platform: its called jobs carry their own. A matrix
job whose legs span operating systems names the leg alone.
"""

from __future__ import annotations

import re
import tomllib

import pytest

from dev.ci_names import (
    GATE_CHECK,
    JOB_NAME,
    PRODUCT,
    WORKFLOW_NAME,
    Kind,
    Platform,
    collapse,
    listed,
)
from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]


def _executable(command: tuple[str, ...]) -> str | None:
    """Return the tool *command* finally invokes, stepping over the launchers.

    ``uv run --no-sync python -m dev.actionlint`` runs actionlint, not uv, not
    python; ``uv run --no-sync python tools/citation_gate.py`` runs the
    citation gate. Reading the first word instead would forbid ``uv`` and
    ``python`` everywhere and never notice the tool that is actually named.
    """
    words = [
        word for word in command if not word.startswith("-") or word in {"--", "-m"}
    ]
    if not words:
        return None
    index = 0
    # `uv` is stepped over only in front of `run`. `uv build` and `uv lock`
    # are uv itself under a subcommand, and reading the subcommand as the
    # tool would forbid the ordinary English word it happens to be.
    if words[index].lower() == "uv" and words[index + 1 : index + 2] == ["run"]:
        index += 2
    if index < len(words) and words[index].lower() in {"python", "python3"}:
        index += 1
    if index >= len(words):
        return words[0].lower()
    token = words[index]
    if token == "-m" and index + 1 < len(words):
        token = words[index + 1].rsplit(".", 1)[-1]
    elif token.endswith(".py"):
        token = token.rsplit("/", 1)[-1].removesuffix(".py")
    return token.lower()


def _invoked(command: tuple[str, ...]) -> set[str]:
    """Return every tool name *command* runs, including behind a ``--``.

    The advisory wrapper is why the tail matters: an advisory scanner runs as
    ``python tools/advisory.py --finding-exit 1 -- bandit ...``, so reading
    only the head would learn ``advisory`` and never learn ``bandit``, and a
    job could go on naming the scanner in its title unchallenged.
    """
    names = {_executable(command)}
    if "--" in command:
        tail = command[command.index("--") + 1 :]
        names.add(_executable(tail))
    return {
        name
        for name in names
        if name is not None and name[:1].isalpha() and not name.endswith(".toml")
    }


def _tool_names() -> frozenset[str]:
    """Return every tool a GATE runs, by the name it runs as.

    Derived rather than listed: a name is forbidden because the repository
    runs a tool by it, so swapping the tool moves the prohibition without
    anyone remembering to edit a list here. Compared WHOLE - a name like
    ``dependency_audit`` is never split, because its parts are ordinary words
    a subject is entitled to use.

    Scoped to the measuring groups. Including the provisioning and build verbs
    would drag in ``uv``'s own subcommands - ``sync``, ``lock``, ``build`` -
    which are ordinary English and would forbid naming what a job covers.
    """
    groups = workflows.recipe_groups()
    return frozenset(
        name
        for recipe, group in groups.items()
        if group in {"check", "audit", "test"}
        for command in workflows.final_commands(recipe)
        for name in _invoked(command)
    )


def _marker_names() -> frozenset[str]:
    """Return every pytest marker registered in ``pyproject.toml``."""
    with (workflows.repository_root() / "pyproject.toml").open("rb") as handle:
        configuration = tomllib.load(handle)
    markers = configuration["tool"]["pytest"]["ini_options"]["markers"]
    return frozenset(str(entry).split(":", 1)[0].strip().lower() for entry in markers)


def _jobs() -> tuple[workflows.Job, ...]:
    """Return every job in every workflow."""
    return workflows.load_jobs()


def _names() -> tuple[tuple[str, str], ...]:
    """Return ``(job id, name)`` for every job in every workflow."""
    return tuple((f"{job.workflow}:{job.job_id}", job.name) for job in _jobs())


def _subject(name: str) -> str:
    """Return the Subject alone, with the Kind and the parenthesis removed.

    The parenthesis is excluded on purpose: it names a runner, and a runner
    may be spelled the same as a pytest marker. Scanning it would forbid
    naming the runner a job actually lands on.
    """
    body = collapse(name).split(": ", 1)[-1]
    return re.sub(r"\s*\([^()]*\)$", "", body)


def _words(name: str) -> set[str]:
    """Return the lower-cased word tokens of a job Subject."""
    return set(re.findall(r"[A-Za-z]+", _subject(name).lower()))


def _name_findings(jobs: tuple[workflows.Job, ...]) -> list[str]:
    """Name every job whose name breaks the grammar or omits its platform."""
    findings: list[str] = []
    for job in jobs:
        collapsed = collapse(job.name)
        where = f"{job.workflow}:{job.job_id}: {job.name!r}"
        if not JOB_NAME.fullmatch(collapsed):
            findings.append(where)
        elif job.steps and not collapsed.endswith(")"):
            findings.append(f"{where} names no platform")
    return findings


def test_every_job_name_follows_the_pattern() -> None:
    """Every job name is ``<Kind>: <Subject> [(<Platform>[, <leg>])]``."""
    findings = _name_findings(_jobs())
    assert not findings, (
        "A job is not named `<Kind>: <Subject> (<Platform>[, <leg>])`.\n"
        f"Kind is one of {listed(Kind)}; the Subject is sentence case; "
        f"Platform is one of {listed(Platform)} or a matrix leg, and only a "
        "job that calls a reusable workflow may omit it.\n\n" + "\n".join(findings)
    )


def test_the_pattern_rejects_the_retired_grammar() -> None:
    """Mutation proof: every shape the previous grammar allowed is refused.

    Each retired name breaks exactly one rule, so each rule is proved alone.
    Adding ``Gate`` back to :class:`~dev.ci_names.Kind` made this fail on
    the retired merge verdict's Kind; removing it again made this pass.
    """
    retired = (
        "Gate: Merge readiness (Linux)",
        "Lint: Static validation (Linux)",
        "Audit: Dependency advisories (Linux)",
        "Test: GPU correctness (CUDA)",
        "Test: Full Suite (Windows)",
    )
    current = (
        GATE_CHECK,
        "Test: GPU correctness (Windows)",
        "Test: Correctness suite (Linux, ${{ matrix.python-version }})",
        "Build: Standalone binaries (${{ matrix.name }})",
        "Test: Release hardware",
    )
    assert [name for name in retired if JOB_NAME.fullmatch(collapse(name))] == []
    assert [name for name in current if not JOB_NAME.fullmatch(collapse(name))] == []


def test_a_job_with_steps_and_no_platform_is_named() -> None:
    """Mutation proof: only a job calling a reusable workflow omits a platform."""
    stepped = workflows.Job(
        "w.yml", "lint", "Check: Lint", (("ubuntu-24.04",),), 10, None, None, ({},)
    )
    calling = workflows.Job("w.yml", "tiers", "Test: Tiers", (), None, None, None, ())
    assert _name_findings((stepped, calling)) == [
        "w.yml:lint: 'Check: Lint' names no platform"
    ]


def test_every_workflow_name_starts_with_the_product() -> None:
    """Every workflow is ``<Product> <Purpose>``, so its runs group together."""
    findings = [
        f"{workflow}: {name!r}"
        for workflow, name in workflows.workflow_names()
        if not WORKFLOW_NAME.fullmatch(name)
    ]
    assert not findings, (
        f"A workflow is not named `{PRODUCT} <Purpose>` in title case.\n\n"
        + "\n".join(findings)
    )


def test_no_job_name_states_the_tool_that_covers_it() -> None:
    """A Subject says what is covered, never which tool covers it.

    The forbidden words are the executables the toolchain actually runs, so
    this prohibition tracks the toolchain rather than a list somebody has to
    remember to update after a swap.
    """
    tools = _tool_names()
    findings = [
        f"{job_id}: {name!r} names the tool(s) {', '.join(sorted(named))}"
        for job_id, name in _names()
        if (named := _words(name) & tools)
    ]
    assert not findings, (
        "A job name states a tool. Name what the job COVERS instead: the tool "
        "is an implementation detail of the recipe, and the name outlives it.\n\n"
        + "\n".join(findings)
    )


def test_no_job_name_states_a_pytest_marker() -> None:
    """A Subject is not a selector either.

    A marker reads as a description to anyone who does not know the
    vocabulary, and sends anyone who does looking for a lane by that name.
    """
    markers = _marker_names()
    findings = [
        f"{job_id}: {name!r} names the marker(s) {', '.join(sorted(named))}"
        for job_id, name in _names()
        if (named := _words(name) & markers)
    ]
    assert not findings, (
        "A job name states a pytest marker. Name the coverage, not the "
        "selection that produces it.\n\n" + "\n".join(findings)
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
    for job in _jobs():
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
        for job in _jobs()
        if job.matrix_axes
        and not any(f"matrix.{axis}" in job.name for axis in job.matrix_axes)
    )
    assert not findings, (
        "Two rows carry the same label.\n"
        "Carry the matrix variable in the name, or fold the jobs together.\n\n"
        + "\n".join(findings)
    )
