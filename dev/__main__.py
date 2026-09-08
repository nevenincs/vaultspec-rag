"""The ``python -m dev`` entry point behind every justfile recipe.

Usage::

    python -m dev <verb> [target]
    python -m dev <verb> help
    python -m dev help

Exit codes are the point of this module: a gating target propagates the exit
code of whichever step failed, so ``just`` and CI both see the real result. An
advisory target suppresses its FINDINGS - and only its findings - because a
scan that yields leads rather than verdicts must not gate a build. A tool that
failed to RUN is a different event and propagates as ADVISORY_BROKEN: the
`; exit 0` this replaced mapped every status onto success, so a scanner that
crashed or was never installed reported exactly like a clean run.
``dev/EXIT-CODES.md`` states the contract in full. The shell form
this replaced restated that decision in every case body, which is how a step
labelled report-only came to gate and a complexity gate came to never run.
"""

from __future__ import annotations

import sys
import textwrap
from typing import assert_never

from dev.exit_codes import (
    NOTHING_SELECTED,
    PYTEST_NO_TESTS_COLLECTED,
    advisory_result,
)
from dev.gates import SKIPPED
from dev.runner import (
    Cmd,
    Echo,
    Ref,
    Step,
    ToolOrDocker,
    ToolOrSkip,
    run,
    run_tool_or_docker,
    run_tool_or_skip,
)
from dev.toolchain import DEFAULTS, VERBS, Target, Verb, find_verb, public_targets

HELP_TOKENS = frozenset({"help", "--help", "-h"})
WRAP_WIDTH = 88


def _print_verb_help(verb: Verb) -> None:
    """Print a verb's usage, targets, and note.

    Args:
        verb: The verb whose help to render.
    """
    print(f"usage: just {verb.name} <target>")
    print(f"  {verb.summary}")
    print()
    width = max(len(name) for name in public_targets(verb))
    for target in verb.targets:
        if target.name.startswith("_"):
            continue
        flag = " (advisory)" if target.advisory and target.name != "all" else ""
        print(f"  {target.name:<{width}}  {target.summary}{flag}")
    default = DEFAULTS.get(verb.name)
    if default:
        print()
        print(f"  default target: {default}")
    if verb.note:
        print()
        print(
            textwrap.fill(
                verb.note,
                width=WRAP_WIDTH,
                initial_indent="  ",
                subsequent_indent="  ",
            )
        )


def _print_root_help() -> None:
    """Print the list of every verb."""
    print("usage: python -m dev <verb> [target]")
    print()
    width = max(len(verb.name) for verb in VERBS)
    for verb in VERBS:
        print(f"  {verb.name:<{width}}  {verb.summary}")
    print()
    print("  Run 'python -m dev <verb> help' for a verb's targets.")


def _summarise(verb: Verb, target: Target, outcomes: list[tuple[str, int]]) -> int:
    """Report what an aggregate ran, what it skipped, and what that adds up to.

    An aggregate that prints nothing about the lanes it did not run is
    indistinguishable from one that ran them all. This prints every referenced
    lane by name with its verdict, and refuses to call a run in which NOTHING
    executed a success.

    Args:
        verb: The owning verb, named in the summary heading.
        target: The aggregate target being summarised.
        outcomes: Each referenced target's name and its exit code, where
            :data:`~dev.gates.SKIPPED` means its gate was closed.

    Returns:
        0 when at least one lane ran and none failed, the first failing lane's
        exit code when one failed, and :data:`~dev.exit_codes.NOTHING_SELECTED` when
        every lane was skipped.
    """
    ran = [name for name, code in outcomes if code == 0]
    skipped = [name for name, code in outcomes if code == SKIPPED]
    failed = [(name, code) for name, code in outcomes if code not in (0, SKIPPED)]

    print(f"\n--- {verb.name} {target.name} summary ---", flush=True)
    for name, code in outcomes:
        verdict = (
            "SKIPPED" if code == SKIPPED else "ok" if code == 0 else f"FAILED ({code})"
        )
        print(f"  {name:<14} {verdict}", flush=True)
    reached = {name for name, _ in outcomes}
    for step in target.steps:
        if isinstance(step, Ref) and step.target not in reached:
            print(
                f"  {step.target:<14} not reached (an earlier lane failed)",
                flush=True,
            )

    if failed:
        name, code = failed[0]
        print(f"{verb.name} {target.name}: FAILED in lane '{name}'", flush=True)
        return code
    if not ran:
        print(
            f"{verb.name} {target.name}: NOTHING RAN - all "
            f"{len(skipped)} lane(s) were skipped, so this run proves nothing. "
            "Exiting non-zero rather than reporting a pass.",
            file=sys.stderr,
            flush=True,
        )
        return NOTHING_SELECTED
    if skipped:
        print(
            f"{verb.name} {target.name}: passed {len(ran)} lane(s); "
            f"{len(skipped)} skipped for want of hardware.",
            flush=True,
        )
    return 0


def _run_step(
    verb: Verb,
    step: Step,
    outcomes: list[tuple[str, int]],
) -> int | None:
    """Run one step and return its exit code.

    Args:
        verb: The owning verb, used to resolve :class:`~dev.runner.Ref` steps.
        step: The step to run.
        outcomes: Accumulator that each resolved reference appends its verdict
            to, so an aggregate can summarise the lanes it reached.

    Returns:
        The step's exit code, or ``None`` when the step contributes no verdict
        of its own - a section header, or a reference whose gate was closed -
        and the caller should move on to the next step.
    """
    match step:
        case Echo():
            print(f"\n{step.text}", flush=True)
            return None
        case Ref():
            referenced = verb.find(step.target)
            if referenced is None:
                print(
                    f"internal error: {verb.name} references undefined target "
                    f"'{step.target}'",
                    file=sys.stderr,
                )
                return 1
            code = _execute(verb, referenced)
            outcomes.append((referenced.name, code))
            return None if code == SKIPPED else code
        case ToolOrDocker():
            return run_tool_or_docker(step)
        case ToolOrSkip():
            return run_tool_or_skip(step)
        case Cmd():
            return run(step.argv, step.env, step.cwd)
        case _:
            assert_never(step)


def _execute(verb: Verb, target: Target) -> int:
    """Run one target's steps and return the resulting exit code.

    Args:
        verb: The owning verb, used to resolve :class:`~dev.runner.Ref` steps.
        target: The target to execute.

    Returns:
        0 when the target is advisory, :data:`~dev.gates.SKIPPED` when the
        target's own gate is closed, otherwise the exit code of the first
        failing step (or of the last failing step when ``keep_going`` is set).
        An aggregate target returns its summary's verdict.
    """
    if target.gate is not None and not target.gate.open():
        print(
            f"\nSKIPPED  {verb.name} {target.name} - {target.gate.reason}",
            flush=True,
        )
        return SKIPPED

    outcomes: list[tuple[str, int]] = []
    worst = 0
    for step in target.steps:
        code = _run_step(verb, step, outcomes)
        if code is None:
            continue

        # A lane that collected nothing did not pass - it selected an empty
        # set, which is what a stale marker expression or a collection guard
        # bailing out both look like. Report it as the skip it is.
        if code == PYTEST_NO_TESTS_COLLECTED and target.lane:
            print(
                f"\nSKIPPED  {verb.name} {target.name} - pytest collected no "
                "tests for this lane's selection",
                flush=True,
            )
            return SKIPPED

        if code != 0:
            # FIRST non-zero wins. An aggregate that keeps going reports the
            # status of the earliest thing that broke, because that is the one
            # whose failure may explain the rest.
            worst = worst or code
            if not target.keep_going:
                break

    if target.aggregate:
        return _summarise(verb, target, outcomes)
    return advisory_result(worst) if target.advisory else worst


def main(argv: list[str] | None = None) -> int:
    """Dispatch a verb and target from the argument vector.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        The process exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in HELP_TOKENS:
        _print_root_help()
        return 0

    verb_name, *rest = args
    verb = find_verb(verb_name)
    if verb is None:
        print(f"unknown verb: {verb_name}", file=sys.stderr)
        print(f"  verbs: {' '.join(v.name for v in VERBS)}", file=sys.stderr)
        return 1

    target_name = rest[0] if rest else DEFAULTS.get(verb.name, "all")

    if target_name in HELP_TOKENS:
        _print_verb_help(verb)
        return 0

    target = verb.find(target_name)
    if target is None or target.name.startswith("_"):
        print(f"unknown {verb.name} target: {target_name}", file=sys.stderr)
        print(f"  targets: {' '.join(public_targets(verb))}", file=sys.stderr)
        return 1

    code = _execute(verb, target)
    # A lane selected directly on a host that cannot run it exits non-zero for
    # the same reason an all-skipped aggregate does: nothing was proved, and a
    # zero here would be read as a pass by the caller and by CI alike.
    if code == SKIPPED:
        print(
            f"{verb.name} {target.name} did not run on this host, so nothing "
            "was proved.",
            file=sys.stderr,
        )
        return NOTHING_SELECTED
    return code


if __name__ == "__main__":
    raise SystemExit(main())
