"""A dashboard that cannot fail must not contain a check that can.

``audit all`` is a REPORT. Every dimension in it yields a lead to confirm
rather than a verdict, which is what lets it run weekly, off the merge path,
and exit zero with findings on the board.

``audit deps`` is the exception inside that verb: a published advisory against
a pinned version IS a verdict, so it gates and holds a job of its own. It was
also a member of the aggregate, and that combination is worse than either
half. The same advisory query ran twice for one commit - once where somebody
acts on it, once inside a report that cannot fail - and the copy inside the
report is the one that teaches a reader the whole dashboard is optional.

The rule is therefore structural rather than a list of names: no target the
advisory aggregate references may be one that gates. That way a dimension
PROMOTED into a gate later - which is exactly what the audit group's own note
invites, once a finding count reaches zero - fails here rather than quietly
becoming a second copy of itself.

How a gate is recognised: every target declares whether its findings are a
verdict or a lead, in ``Target.reports``. That is a declaration rather than an
inference for a reason - the advisory wrapping lives in an argv prefix, in a
``ToolOrSkip`` field, and inside one harness instrument's own ``main``, so
reading the steps classifies the third kind wrongly.
"""

from __future__ import annotations

import pytest

from dev import toolchain
from dev.runner import Ref

pytestmark = [pytest.mark.unit, pytest.mark.repo]


def _gates(target: toolchain.Target) -> bool:
    """Whether *target*'s FINDINGS can fail a build.

    Read from the target's own declaration rather than inferred from its
    steps. The advisory wrapping lives in three different places - an argv
    prefix, a ``ToolOrSkip`` field, and inside a harness instrument's own
    ``main`` - so a reader of the steps classifies the third kind wrongly, and
    a guard that misclassifies a dimension is one somebody switches off.
    """
    return not (target.reports or target.advisory)


def test_the_advisory_aggregate_references_no_gating_target() -> None:
    """Every dimension ``audit all`` reports is one that cannot fail.

    Guard assertion: adding ``Ref("deps")`` back to that aggregate - or
    promoting any member into a gate while leaving it a member - fails here,
    naming the target and what it would cost.
    """
    aggregate = toolchain.AUDIT.find("all")
    assert aggregate is not None, "the audit verb has no `all` target"
    findings: list[str] = []
    for step in aggregate.steps:
        if not isinstance(step, Ref):
            continue
        member = toolchain.AUDIT.find(step.target)
        if member is None:
            findings.append(f"`audit all` references `{step.target}`, which is gone")
        elif _gates(member):
            findings.append(
                f"`audit all` reports `{member.name}`, which GATES - so the "
                "same measurement is taken twice for one commit, once as a "
                "verdict and once inside a report that cannot fail"
            )
    assert not findings, (
        "The advisory dashboard holds a gate.\n"
        "Reach the gate directly - `ci all` does - and keep the aggregate to "
        "the dimensions that report.\n\n" + "\n".join(findings)
    )


def test_the_gating_audit_target_is_still_reachable() -> None:
    """Dropping the gate from the dashboard did not drop it from the pipeline.

    Guard assertion: removing ``deps`` from ``audit all`` is only correct
    while something else still runs it. Without this, the previous test could
    be satisfied by deleting the gate rather than by separating it.
    """
    gating = [
        target.name
        for target in toolchain.AUDIT.targets
        if target.name != "all" and _gates(target)
    ]
    assert gating, "the audit verb has no gating target left to reach"
    pipeline = toolchain.CI.find("all")
    assert pipeline is not None, "the ci verb has no `all` target"
    reached = {
        argv[-1]
        for step in pipeline.steps
        if (argv := getattr(step, "argv", ())) and "audit" in argv
    }
    missing = sorted(set(gating) - reached)
    assert not missing, (
        "a gating audit target is in no pipeline: "
        f"{', '.join(missing)}. `ci all` reaches "
        f"{', '.join(sorted(reached)) or 'nothing'} from the audit verb."
    )
