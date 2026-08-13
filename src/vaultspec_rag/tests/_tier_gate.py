"""The test-tier vocabulary and the startup gates that enforce it.

Every test declares which lane it belongs to. The fast lane is selected by
EXCLUDING the slow tiers rather than by naming the fast one, so a test that
declares nothing is not skipped - it is pulled into the fast lane and run on a
machine that may have neither a GPU nor a Hugging Face token. The inverse costs
just as much: a module-level ``pytestmark`` is ADDED to a test's own decorator
rather than overridden by it, so a blanket module default drags GPU tests into
``-m unit``.

The tier rules are enforced at collection time, from the root conftest, so they
run on every pytest invocation rather than only where someone remembered a gate.
The vocabulary lives here rather than in that conftest so the enforcement can be
exercised by ordinary in-package tests.

The second gate here refuses to distribute a GPU-bound selection across
processes at all. It is checked before collection rather than during it, because
the process that owns the ``-n`` decision is the only one that can refuse
cleanly: under distribution the plugin collects in its workers and never calls
the collection or run-loop hooks in the process the operator launched, while a
worker that raises during its own collection is reported as an internal
scheduling fault whose text never reaches the operator. So the gate reads the
resolved distribution options and the marker expression, both of which are
final before collection starts, and refuses there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeIs

import pytest

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterator, Sequence

__all__ = [
    "FAST_TIER",
    "GPU_MARKERS",
    "SLOW_TIERS",
    "SUBPROCESS_GPU",
    "TIER_MARKERS",
    "coscheduled_device_tiers",
    "coscheduled_gpu_failure_message",
    "distributed_worker_count",
    "enforce_serial_gpu_lane",
    "enforce_tiers",
    "selectable_slow_tiers",
    "selected_tiers",
    "tier_violations",
]


class MarkLike(Protocol):
    """The part of a pytest ``Mark`` this module reads.

    Declared read-only: pytest's ``Mark`` is frozen, so a writable attribute
    here would exclude the very type this protocol exists to describe.
    """

    @property
    def name(self) -> str: ...


class TieredItem(Protocol):
    """The part of a collected item the tier rules read."""

    @property
    def nodeid(self) -> str: ...

    def iter_markers(self) -> Iterator[MarkLike]: ...


def _is_object_list(value: object) -> TypeIs[list[object]]:
    """Recognize an option list whose members this gate never inspects."""
    return isinstance(value, list)


#: Tiers whose tests require exclusive GPU access.
GPU_MARKERS = frozenset({"integration", "quality", "performance", "robustness"})

#: CLI subprocess tests that load their own GPU models. These must NOT
#: co-schedule with GPU_MARKERS tests - combined VRAM exceeds 16 GB on RTX 4080.
SUBPROCESS_GPU = "subprocess_gpu"

#: The lane that needs no real device.
FAST_TIER = "unit"

#: Everything that does. Derived, so a new tier is named in one place.
SLOW_TIERS = GPU_MARKERS | {SUBPROCESS_GPU, "cuda"}

#: Every collected test must declare one side of that split.
TIER_MARKERS = SLOW_TIERS | {FAST_TIER}


def _marker_names(item: TieredItem) -> set[str]:
    """Return the marker names carried by *item*."""
    return {mark.name for mark in item.iter_markers()}


def selected_tiers(items: Sequence[TieredItem]) -> set[str]:
    """Return every tier declared across *items*, ignoring other markers.

    Callers that must decide whether a run needs a device, a token, or the
    machine's GPU ask this rather than re-deriving the marker intersection, so
    one reading of the vocabulary serves all of them.
    """
    tiers: set[str] = set()
    for item in items:
        tiers |= _marker_names(item) & TIER_MARKERS
    return tiers


def tier_violations(items: Sequence[TieredItem]) -> tuple[list[str], list[str]]:
    """Return node ids that declare no tier, and those that declare two lanes.

    Args:
        items: The collected test items.

    Returns:
        ``(untiered, contradictory)`` - tests carrying no tier marker, and
        tests carrying the fast tier alongside a slow one.
    """
    untiered: list[str] = []
    contradictory: list[str] = []
    for item in items:
        names = _marker_names(item)
        nodeid = item.nodeid
        if not names & TIER_MARKERS:
            untiered.append(nodeid)
        elif FAST_TIER in names and names & SLOW_TIERS:
            contradictory.append(nodeid)
    return untiered, contradictory


def _listing(ids: list[str]) -> str:
    """Render at most twenty node ids, saying how many were withheld."""
    shown = "\n  ".join(ids[:20])
    rest = len(ids) - 20
    return f"  {shown}" + (f"\n  ... and {rest} more" if rest > 0 else "")


def tier_failure_message(untiered: list[str], contradictory: list[str]) -> str:
    """Compose the operator-facing explanation for a tier violation."""
    parts: list[str] = []
    if untiered:
        parts.append(
            f"{len(untiered)} test(s) declare no tier marker:\n{_listing(untiered)}"
            f"\n\nAdd one of: {', '.join(sorted(TIER_MARKERS))}. The fast lane is "
            "selected by EXCLUDING the slow tiers rather than by naming the fast "
            "one, so a test with no tier is silently pulled into it and run on a "
            "machine that may have no GPU and no token."
        )
    if contradictory:
        parts.append(
            f"{len(contradictory)} test(s) declare '{FAST_TIER}' alongside a slow "
            f"tier:\n{_listing(contradictory)}\n\nA module-level `pytestmark` "
            "applies to every test in the module, and pytest ADDS it to a test's "
            "own decorator rather than letting the decorator override it. Scope "
            "the default to the classes or tests that want it, not the module."
        )
    return "\n\n".join(parts)


def enforce_tiers(items: Sequence[TieredItem]) -> None:
    """Abort collection when any test declares no tier, or two lanes.

    Raises:
        pytest.UsageError: On the first collection carrying a violation.
    """
    untiered, contradictory = tier_violations(items)
    if untiered or contradictory:
        raise pytest.UsageError(tier_failure_message(untiered, contradictory))


class _TierMatcher:
    """Report one tier as present and every other identifier as absent.

    Evaluating a marker expression against this answers the only question the
    parallel ban asks: could a test carrying this one tier survive deselection?
    Keyword arguments are accepted and ignored, so a parametrised marker
    expression is read as naming its tier rather than rejected.
    """

    def __init__(self, tier: str) -> None:
        self._tier = tier

    def __call__(self, name: str, /, **_kwargs: str | int | bool | None) -> bool:
        return name == self._tier


def distributed_worker_count(option: argparse.Namespace) -> int:
    """Return how many separate processes this session will distribute across.

    Reads the resolved options rather than the command line: ``auto`` is already
    an integer by this point, and a distribution mode on its own spawns nothing,
    so the configured execution environments are the authority and the requested
    count only covers reading them before they are expanded. Zero means this
    process runs its own tests - which is what a distributed session's workers
    report too, because a worker is told neither the count nor the mode.
    """
    requested: object = getattr(option, "numprocesses", None)
    if isinstance(requested, int) and requested > 0:
        return requested
    environments: object = getattr(option, "tx", None)
    if not _is_object_list(environments):
        return 0
    return len(environments)


def selectable_slow_tiers(markexpr: str) -> list[str]:
    """Return the slow tiers a marker expression can still select.

    An empty expression selects the whole suite, so every slow tier remains
    reachable. Otherwise the expression is compiled once and evaluated against
    one tier at a time using the same evaluator that performs the deselection,
    rather than a second reading of the same syntax. A malformed expression
    excludes nothing that can be proven, so it is reported as selecting
    everything; pytest rejects it on its own terms moments later.
    """
    from _pytest.mark.expression import Expression

    tiers = sorted(SLOW_TIERS)
    if not markexpr.strip():
        return tiers
    try:
        expression = Expression.compile(markexpr)
    except SyntaxError:
        return tiers
    return [tier for tier in tiers if expression.evaluate(_TierMatcher(tier))]


def parallel_gpu_failure_message(
    tiers: list[str], *, workers: int, markexpr: str
) -> str:
    """Compose the operator-facing explanation for a distributed GPU selection."""
    selection = (
        f"marker expression '{markexpr}'"
        if markexpr.strip()
        else "no marker expression, so the whole suite is selected"
    )
    exclusion = " or ".join(sorted(SLOW_TIERS))
    return (
        f"refusing to distribute this session across {workers} worker "
        f"process(es): {selection}, which can still select the GPU-bound "
        f"tier(s) {', '.join(tiers)}.\n\n"
        "This machine has one GPU and every worker process loads its own model "
        "stack onto it, so a distributed GPU selection exhausts device memory "
        "and takes the host down with it. A scheduling group does not help: it "
        "serialises execution inside one process while each worker's models "
        "stay resident.\n\n"
        "Run the GPU tiers serially, without -n or --dist, or keep the "
        "distributed lane clear of them by excluding every slow tier: "
        f'-m "not ({exclusion})".'
    )


def coscheduled_device_tiers(markexpr: str) -> list[str]:
    """Return the GPU tiers a selection would co-schedule with subprocess GPU.

    Empty when the expression cannot reach ``subprocess_gpu``, or reaches no
    resident-model tier alongside it.
    """
    selectable = set(selectable_slow_tiers(markexpr))
    if SUBPROCESS_GPU not in selectable:
        return []
    return sorted(selectable & GPU_MARKERS)


def coscheduled_gpu_failure_message(tiers: list[str], *, markexpr: str) -> str:
    """Compose the operator-facing explanation for a co-scheduled GPU selection."""
    selection = (
        f"marker expression '{markexpr}'"
        if markexpr.strip()
        else "no marker expression, so the whole suite is selected"
    )
    named = ", ".join(tiers)
    return (
        f"This session uses {selection}, which selects {SUBPROCESS_GPU} tests "
        f"alongside {named}. Those cannot share a device: the lane holds its "
        "models resident while each subprocess test spawns a service that loads "
        "its own, and the combined footprint exceeds the card. The symptom is "
        "not an out-of-memory error but a spawned service that never becomes "
        "healthy, surfacing as an unrelated-looking timeout late in the run.\n"
        f"Run them as two sequential selections instead, e.g. "
        f"-m '({' or '.join(tiers)}) and not {SUBPROCESS_GPU}' followed by "
        f"-m {SUBPROCESS_GPU}."
    )


def enforce_serial_gpu_lane(option: argparse.Namespace) -> None:
    """Abort the session when it would distribute GPU tests across processes.

    Raises:
        pytest.UsageError: When a distributed session's selection can still
            reach a slow tier.
    """
    workers = distributed_worker_count(option)
    if workers <= 0:
        return
    markexpr = getattr(option, "markexpr", "")
    markexpr = markexpr if isinstance(markexpr, str) else ""
    tiers = selectable_slow_tiers(markexpr)
    if tiers:
        raise pytest.UsageError(
            parallel_gpu_failure_message(tiers, workers=workers, markexpr=markexpr)
        )
