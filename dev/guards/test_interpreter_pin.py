"""One statement of which interpreters this project supports.

WHY THIS IS A TEST AND NOT THREE WORKFLOW STEPS. It used to be three copies of
one Python heredoc pasted into ``run:`` blocks - one asserting the venv
matches ``.python-version``, two asserting a matrix leg runs the interpreter it
claims - each carried in the CI-contract allowlist as debt with the note
"Recipe needed: check-interpreter". A check that only READS committed files is
not a job: it needs no runner, it costs a place in a serial fleet's queue, and
it can only ever run where somebody remembered to paste it. As a test it holds
on every platform, on every matrix leg, and on a laptop before the push.

WHAT IT ACTUALLY ASSERTS, WHICH IS MORE THAN THE STEPS DID. The steps compared
a running interpreter to a string. The interesting failure is upstream of
that: the supported range in ``pyproject.toml``, the development pin in
``.python-version``, the version every static analyser assumes, and the two CI
matrices are five statements of one fact, kept in five files, and nothing
compared them. A matrix leg quietly dropped, or an analyser left checking an
older minor than the suite runs, produces a green board over a version nobody
tested.
"""

from __future__ import annotations

import re
import sys
import tomllib
from typing import TYPE_CHECKING

import pytest
import yaml

from dev.guards import _workflows as workflows

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: ``requires-python`` must state a closed range. An open upper bound cannot
#: be enumerated, so the matrices below could not be compared against it and
#: this guard would quietly check nothing.
_RANGE = re.compile(r"^>=(\d+)\.(\d+),\s*<(\d+)\.(\d+)$")


def _pyproject() -> dict[str, object]:
    """Return the parsed project configuration."""
    with (workflows.repository_root() / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _supported_minors() -> tuple[str, ...]:
    """Return every ``major.minor`` inside ``requires-python``, in order."""
    configuration = _pyproject()
    project = configuration["project"]
    assert isinstance(project, dict)
    requires = str(project["requires-python"]).replace(" ", "")
    match = _RANGE.fullmatch(requires)
    assert match is not None, (
        f"requires-python is {requires!r}; this guard needs a closed "
        ">=X.Y,<X.Z range so the supported minors can be enumerated and "
        "compared against the CI matrices."
    )
    low_major, low_minor, high_major, high_minor = (int(g) for g in match.groups())
    assert low_major == high_major, "the supported range spans two major versions"
    return tuple(f"{low_major}.{minor}" for minor in range(low_minor, high_minor))


def _development_pin() -> str:
    """Return the full version ``.python-version`` pins."""
    return (
        (workflows.repository_root() / ".python-version")
        .read_text(encoding="utf-8")
        .strip()
    )


def _matrix_versions(workflow: str, job_id: str) -> tuple[str, ...]:
    """Return the ``python-version`` axis a job's matrix declares."""
    path = workflows.repository_root() / ".github" / "workflows" / workflow
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    job = (document.get("jobs") or {}).get(job_id) or {}
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    return tuple(str(value) for value in matrix.get("python-version", ()))


def test_the_development_pin_is_a_supported_interpreter() -> None:
    """``.python-version`` names a full version inside ``requires-python``."""
    pin = _development_pin()
    assert re.fullmatch(r"\d+\.\d+\.\d+", pin), (
        f".python-version is {pin!r}; pin a full major.minor.patch so a "
        "provisioner resolves one interpreter rather than a range."
    )
    minor = ".".join(pin.split(".")[:2])
    supported = _supported_minors()
    assert minor in supported, (
        f".python-version pins {pin}, whose minor {minor} is outside "
        f"requires-python ({', '.join(supported)}). The development "
        "environment would be built on an interpreter the package refuses to "
        "install on."
    )


def test_the_running_interpreter_is_one_the_project_supports() -> None:
    """The interpreter running this suite is inside ``requires-python``.

    This is what the workflow steps were reaching for, and it holds here on
    every matrix leg rather than only on the two that carried the heredoc:
    the assertion is against the supported RANGE, not against the development
    pin, because a leg testing the upper minor is doing its job.
    """
    running = f"{sys.version_info[0]}.{sys.version_info[1]}"
    supported = _supported_minors()
    assert running in supported, (
        f"this suite is running on Python {sys.version.split()[0]}, which is "
        f"outside requires-python ({', '.join(supported)}). Either the "
        "environment was built on the wrong interpreter, or the supported "
        "range no longer says what the project actually supports."
    )


def test_the_static_analysers_check_the_interpreter_the_suite_runs() -> None:
    """Every analyser assumes the minor ``.python-version`` pins.

    An analyser left on an older minor passes syntax and typing the suite then
    runs on a newer one - and the reverse admits code the floor interpreter
    cannot parse. Both are green boards over an untested version.
    """
    configuration = _pyproject()
    tools = configuration["tool"]
    assert isinstance(tools, dict)
    minor = ".".join(_development_pin().split(".")[:2])
    compact = minor.replace(".", "")
    declared = {
        "tool.ty.environment.python-version": _dig(
            tools, ("ty", "environment", "python-version")
        ),
        "tool.basedpyright.pythonVersion": _dig(
            tools, ("basedpyright", "pythonVersion")
        ),
        "tool.ruff.target-version": _dig(tools, ("ruff", "target-version")),
    }
    expected = {
        "tool.ty.environment.python-version": minor,
        "tool.basedpyright.pythonVersion": minor,
        "tool.ruff.target-version": f"py{compact}",
    }
    findings = [
        f"{key} is {value!r}, expected {expected[key]!r}"
        for key, value in declared.items()
        if value is not None and value != expected[key]
    ]
    assert not findings, (
        f".python-version pins {minor}, and an analyser assumes another "
        "interpreter.\n\n" + "\n".join(findings)
    )


def _dig(mapping: object, path: tuple[str, ...]) -> object:
    """Return a nested configuration value, or ``None`` when it is absent."""
    for key in path:
        if not isinstance(mapping, dict) or key not in mapping:
            return None
        mapping = mapping[key]
    return mapping


def test_the_test_matrix_covers_every_supported_interpreter() -> None:
    """The suite runs on every minor ``requires-python`` admits.

    A minor inside the supported range and outside the matrix is a version the
    project promises and never tests.
    """
    supported = set(_supported_minors())
    declared = set(_matrix_versions("ci.yml", "tests"))
    assert declared == supported, (
        "the test matrix and requires-python disagree about which "
        f"interpreters this project supports: matrix {sorted(declared)}, "
        f"requires-python {sorted(supported)}."
    )


def test_the_release_smoke_matrix_matches_the_test_matrix() -> None:
    """The published artifact is smoke-tested on exactly what CI tested.

    A wheel proven on one set of interpreters and installed on another is the
    release-time failure this cross-read exists to make impossible; it is also
    a matrix read no single job can perform, because neither workflow sees the
    other.
    """
    tested = set(_matrix_versions("ci.yml", "tests"))
    smoked = set(_matrix_versions("publish.yml", "smoke-test"))
    assert tested == smoked, (
        "CI tests one set of interpreters and the release smoke-tests "
        f"another: CI {sorted(tested)}, publish {sorted(smoked)}."
    )


def test_no_workflow_reimplements_the_interpreter_check() -> None:
    """No workflow carries the heredoc this module replaced.

    The steps are gone from the workflows and from the CI-contract allowlist;
    this keeps them gone. A pasted copy would drift from the range above and
    would only ever run where somebody remembered to paste it.
    """
    directory = workflows.repository_root() / ".github" / "workflows"
    findings = [
        f"{path.name} still asserts on `{_ASSERTION}` in a run: step"
        for path in sorted(directory.glob("*.yml"))
        if _reads_the_pin_in_a_step(path)
    ]
    assert not findings, (
        "A workflow re-implements the interpreter check as a step. It belongs "
        "here, where it holds on every platform and on a laptop.\n\n"
        + "\n".join(findings)
    )


#: What the removed heredocs all did. Matched on the ASSERTION rather than on
#: the pin's filename: ``uv python install ${{ matrix.python-version }}`` is a
#: provisioning step that legitimately names the pin, and a needle loose
#: enough to catch it would have to be switched off to allow it.
_ASSERTION = "sys.version_info"


def _reads_the_pin_in_a_step(path: Path) -> bool:
    """Whether any ``run:`` step in *path* asserts on the running interpreter."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return any(
        isinstance(step, dict)
        and isinstance(step.get("run"), str)
        and _ASSERTION in str(step["run"])
        for job in (document.get("jobs") or {}).values()
        if isinstance(job, dict)
        for step in job.get("steps") or []
    )
