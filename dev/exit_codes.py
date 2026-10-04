"""The repository-wide exit-code contract.

A command's exit code is its contract with CI and with the developer. This
module states that contract once, as data, so every command in this
repository means the same thing by the same number. It is stdlib-only and
imports nothing from the rest of ``dev`` so that any instrument - including
one that runs before the virtual environment exists - can depend on it.

The governing distinction is between a tool that RAN and reported findings and
a tool that FAILED TO RUN. Advisory targets suppress the first and must never
suppress the second: a scanner that crashed, was misconfigured, or was never
installed reports nothing, and "reported nothing" is not "found nothing".

Verb classes, keyed to CONSEQUENCE:

``check``
    GATES. Read-only. A finding is a verdict and fails the build.
``fix``
    MUTATES. Exits :data:`OK` on success whether or not it changed anything.
``test``
    GATES. Additionally, a lane that ran nothing exits
    :data:`NOTHING_SELECTED` - never :data:`OK`.
``audit``
    ADVISORY, except the DEPENDENCY audit, which GATES. A published advisory
    against a pinned version is a verdict; every other scan yields a lead.
``build``
    GATES.
``health``
    Measures. Always exits :data:`OK`; its output is the product.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Container

#: Success. The command ran and found nothing that gates.
OK = 0

#: Generic failure: the command ran and reported a gating result.
FAILED = 1

#: `just init`: a required HOST tool is absent. Reserved so nothing else in
#: this contract claims it. Outside `init`, an absent executable discovered at
#: dispatch time is :data:`TOOL_MISSING`, which carries the shell's own
#: command-not-found meaning and needs no lookup table.
INIT_HOST_TOOL_MISSING = 2

#: `just init`: the environment exists but is stale relative to its inputs.
INIT_STALE = 3

#: `just init`: one bootstrap step failed.
INIT_STEP_FAILED = 4

#: `just init`: the lockfile and the environment disagree.
DRIFT = 5

#: `just init`: the environment is held open by another process.
INIT_LOCKED = 6

#: An advisory tool failed to RUN: it crashed, was misconfigured, or exited
#: with a status outside :data:`FINDINGS_CODES` and :data:`OK`. Advisory means
#: "these findings do not gate", not "this scanner's silence is trustworthy":
#: the findings are suppressed, a tool that could not run is not.
ADVISORY_BROKEN = 7

#: Nothing ran. An empty selection, a suite in which every test skipped, or an
#: aggregate with no reachable steps. Deliberately non-zero: a run that proved
#: nothing must not be readable as a run that proved everything.
NOTHING_SELECTED = 8

#: A required tool is not installed and has no fallback. 127 is the
#: conventional shell status for command-not-found, which keeps the meaning
#: legible in CI logs and to anyone reading the number directly.
TOOL_MISSING = 127

#: Statuses meaning "the tool ran and reported findings". Every scanner this
#: repository runs - ruff, bandit, vulture, deptry, jscpd, complexipy, xenon,
#: npm audit, cargo deny - uses 1 for this. An advisory target suppresses
#: exactly these; anything else is :data:`ADVISORY_BROKEN`.
FINDINGS_CODES = frozenset({FAILED})

#: pytest's status for "no tests were collected", which the dispatcher reports
#: as a skipped lane so an empty selection cannot read as a pass.
PYTEST_NO_TESTS_COLLECTED = 5


def advisory_result(code: int, findings: Container[int] = FINDINGS_CODES) -> int:
    """Collapse an advisory step's status onto the contract.

    Args:
        code: The status the advisory tool exited with.
        findings: The statuses THIS tool uses to mean "I found something".
            Defaults to :data:`FINDINGS_CODES`, which is right for every
            scanner this repository runs but one: vulture reports dead code
            with 3 and reserves 1 and 2 for invalid input and invalid
            arguments. Reading its 3 as breakage would silence the finding;
            reading its 1 as a finding would silence a broken invocation. A
            tool that does not use 1 must therefore SAY so, which is the
            difference between this and a blanket flag.

    Returns:
        :data:`OK` when the tool ran and merely reported findings, otherwise
        :data:`ADVISORY_BROKEN`. This is the whole of the mechanism that
        `; exit 0` got wrong: `exit 0` maps EVERY status onto success, so a
        scanner that was missing or crashed reported exactly like a clean run.
    """
    if code == OK or code in findings:
        return OK
    return ADVISORY_BROKEN
