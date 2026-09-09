"""Every merge-box job is named ``<Kind>: <Subject> [(Platform)]``.

The job name is the whole of what a reviewer sees. A merge box listing
``PR Gate (ruff, ty, tests)`` beside ``Lint, Type, Config, Link, and Markdown
Checks`` and ``Tests (Windows, advisory)`` gives three different grammars for
three jobs doing one kind of thing, and nothing in it says which of them
covers the file the reviewer changed.

**Kind** is one of three, and they are the harness verbs - ``dev lint``,
``dev test``, ``dev audit`` - so the merge box and the recipe registry share a
vocabulary rather than each inventing one. (The justfile files these under the
fleet-wide consequence groups ``check``/``test``/``audit``; ``check`` and
``lint`` are the same set of gates under two labels, and the verb is the one
this guard can resolve mechanically.)

**Subject** says WHAT IS COVERED, never which tool covers it. Two rules follow
from that, and both were paid for:

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

**Platform** is the optional trailing parenthesis, and it is the only
parenthesis permitted: it is what distinguishes two jobs that genuinely cover
the same subject on two runners.
"""

from __future__ import annotations

import re
import tomllib

import pytest

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: The workflow that is the merge box. Release-plane workflows build and
#: publish rather than measure, so ``Build``/``Publish`` are honest Kinds
#: there and this three-word vocabulary would be a lie.
WORKFLOW = "ci.yml"

#: The three Kinds, matching the harness verbs in :mod:`dev.toolchain`.
KINDS = ("Lint", "Test", "Audit")

#: The platforms a job may name. A runner pool, not a tool or an adjective.
PLATFORMS = ("Linux", "Windows", "macOS", "CUDA")

#: What a name must look like once interpolations are collapsed.
NAME = re.compile(
    rf"^(?:{'|'.join(KINDS)}): "
    r"[A-Z][^()]*[^()\s]"
    rf"(?: \((?:{'|'.join(PLATFORMS)})\))?$"
)

#: An expression in a job name, replaced by a stand-in before matching so a
#: matrix leg's name is checked for shape rather than for its resolved value.
_INTERPOLATION = re.compile(r"\$\{\{[^}]*\}\}")


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

    Scoped to the measuring groups, because those are the only recipes a
    merge-box job runs. Including the provisioning and build verbs would drag
    in ``uv``'s own subcommands - ``sync``, ``lock``, ``build`` - which are
    ordinary English and would forbid naming what a job covers.
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


def _names() -> tuple[tuple[str, str], ...]:
    """Return ``(job id, name)`` for every job in the merge box."""
    return tuple((job.job_id, job.name) for job in workflows.load_jobs(WORKFLOW))


def _collapsed(name: str) -> str:
    """Return *name* with every expression replaced by a stand-in token."""
    return _INTERPOLATION.sub("Xx", name)


def _subject(name: str) -> str:
    """Return the Subject alone, with the Kind and the Platform removed.

    The Platform is excluded on purpose: it is a runner pool, and one of them
    is spelled the same as a pytest marker. Scanning it would forbid naming
    the runner a job actually lands on.
    """
    body = _collapsed(name).split(": ", 1)[-1]
    return re.sub(rf"\s*\((?:{'|'.join(PLATFORMS)})\)$", "", body)


def _words(name: str) -> set[str]:
    """Return the lower-cased word tokens of a job Subject."""
    return set(re.findall(r"[A-Za-z]+", _subject(name).lower()))


def test_every_job_name_follows_the_pattern() -> None:
    """Every merge-box job name is ``<Kind>: <Subject> [(Platform)]``."""
    findings = [
        f"{job_id}: {name!r}"
        for job_id, name in _names()
        if not NAME.fullmatch(_collapsed(name))
    ]
    assert not findings, (
        "A merge-box job is not named `<Kind>: <Subject> [(Platform)]`.\n"
        f"Kind is one of {', '.join(KINDS)}; Platform, when present, is one of "
        f"{', '.join(PLATFORMS)} and is the only parenthesis allowed.\n\n"
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
    """No two rows of the merge box carry the same label.

    Two ways that happens, and only one is visible in the YAML. Two jobs may
    simply be given the same ``name:``. Or one job with a matrix may leave its
    variable out of the name - which reads as a single unique name in the file
    and produces one identically labelled row per leg, at which point a
    required status check can only ever name one of them and a reviewer cannot
    tell which leg went red.
    """
    seen: dict[str, list[str]] = {}
    for job_id, name in _names():
        seen.setdefault(name, []).append(job_id)
    findings = [
        f"{name!r} is used by {', '.join(ids)}"
        for name, ids in sorted(seen.items())
        if len(ids) > 1
    ]
    findings.extend(
        f"{job.job_id}: {job.name!r} varies over "
        f"{', '.join(job.matrix_axes)} but names no leg, so every leg is one "
        "identically labelled row"
        for job in workflows.load_jobs(WORKFLOW)
        if job.matrix_axes
        and not any(f"matrix.{axis}" in job.name for axis in job.matrix_axes)
    )
    assert not findings, (
        "Two rows of the merge box carry the same label.\n"
        "Carry the matrix variable in the name, or fold the jobs together.\n\n"
        + "\n".join(findings)
    )
