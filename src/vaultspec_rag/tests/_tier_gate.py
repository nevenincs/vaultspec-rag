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

Triaging a refusal from this module: read the EXIT CODE, not the summary line.
A ``UsageError`` raised from ``pytest_collection_modifyitems`` still prints
``N tests collected in X.XXs`` on stdout as though nothing were wrong; the
refusal goes to stderr and the only reliable signal is the exit code (4). A
serial ``--collect-only`` was read here as proof that collection was fine, on
the strength of that summary line, while the run had in fact been refused -
which sent an investigation of a distributed worker crash down three wrong
paths. Under ``-n``, the same refusal kills the worker, and xdist reports it
as ``assert not crashitem`` naming whatever unrelated test that worker held.

The marker a suite is refused for may not be missing so much as inherited: a
module-level ``pytestmark`` reaches a sibling that imports it by name, and
nothing in the suite body references it, so any "import only what is used"
pass drops it and un-tiers every test in that file at once.
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
    "MPS",
    "SLOW_TIERS",
    "SUBPROCESS_GPU",
    "TIER_MARKERS",
    "coscheduled_device_tiers",
    "coscheduled_gpu_failure_message",
    "coscheduled_mps_tiers",
    "distributed_worker_count",
    "enforce_device_tier_isolation",
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

#: Real-model tests that require Apple silicon through PyTorch MPS. This is a
#: separate hardware lane: it neither borrows the CUDA runner's resident service
#: nor shares a selection with tests sized and coordinated for discrete VRAM.
MPS = "mps"

#: CLI subprocess tests that load their own GPU models. These must NOT
#: co-schedule with GPU_MARKERS tests - combined VRAM exceeds 16 GB on RTX 4080.
#: Enforced twice, because stating it beside the marker is what failed: a test
#: may not DECLARE this alongside a GPU_MARKERS tier, and no selection may hold
#: both. The first keeps the second from having anything to catch.
SUBPROCESS_GPU = "subprocess_gpu"

#: The lane that needs no real device.
FAST_TIER = "unit"

#: Everything that does. Derived, so a new tier is named in one place.
SLOW_TIERS = GPU_MARKERS | {SUBPROCESS_GPU, "cuda", MPS}

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


def tier_violations(
    items: Sequence[TieredItem],
) -> tuple[list[str], list[str], list[str]]:
    """Return node ids that declare no tier, two lanes, or two device tiers.

    Args:
        items: The collected test items.

    Returns:
        ``(untiered, contradictory, both_devices)`` - tests carrying no tier
        marker, tests carrying the fast tier alongside a slow one, and tests
        declaring the subprocess tier alongside a resident-model one.
    """
    untiered: list[str] = []
    contradictory: list[str] = []
    both_devices: list[str] = []
    for item in items:
        names = _marker_names(item)
        nodeid = item.nodeid
        if not names & TIER_MARKERS:
            untiered.append(nodeid)
        elif FAST_TIER in names and names & SLOW_TIERS:
            contradictory.append(nodeid)
        elif SUBPROCESS_GPU in names and names & GPU_MARKERS:
            both_devices.append(nodeid)
    return untiered, contradictory, both_devices


def _listing(ids: list[str]) -> str:
    """Render at most twenty node ids, saying how many were withheld."""
    shown = "\n  ".join(ids[:20])
    rest = len(ids) - 20
    return f"  {shown}" + (f"\n  ... and {rest} more" if rest > 0 else "")


def tier_failure_message(
    untiered: list[str], contradictory: list[str], both_devices: list[str]
) -> str:
    """Compose the operator-facing explanation for a tier violation."""
    parts: list[str] = []
    if both_devices:
        parts.append(
            f"{len(both_devices)} test(s) declare '{SUBPROCESS_GPU}' alongside a "
            f"resident-model tier:\n{_listing(both_devices)}\n\nA test that "
            "spawns a service loading its own models belongs to the subprocess "
            "tier alone. Declaring a resident tier as well puts it in both "
            "lanes, and the lane that selects it by that second declaration "
            "cannot run it - the two exceed the card. This is usually inherited "
            "rather than written: a module-level `pytestmark` applies to every "
            "test in the module and pytest ADDS it to the decorator. Scope the "
            "default, or drop it and let each test name its own tier."
        )
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
    untiered, contradictory, both_devices = tier_violations(items)
    if untiered or contradictory or both_devices:
        raise pytest.UsageError(
            tier_failure_message(untiered, contradictory, both_devices)
        )


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

    Evaluated with the same evaluator that performs the deselection, rather
    than a second reading of the same syntax. An unrestricted expression leaves
    every slow tier reachable.
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


def coscheduled_device_tiers(
    items: Sequence[TieredItem],
) -> tuple[list[str], list[str]]:
    """Split *items* into the subprocess tier and the resident-model tier.

    Read off what was actually selected rather than modelled from the marker
    expression, because the expression does not know which tests exist. Probing
    every tier combination that could exist refuses the performance lane to
    protect it from subprocess tests it never selects, and probing one tier at
    a time misses any test declaring two - which is what the suite looked like
    when this was written, before those declarations were untangled.

    A test declaring both is still counted on the subprocess side rather than
    ignored: what it does is spawn a service that loads its own models. The
    declaration gate refuses that combination separately, so the two checks
    cannot disagree about which lane such a test belongs to.

    Returns:
        ``(subprocess_ids, resident_ids)`` - the selected node ids on each
        side. The hazard is both being non-empty.
    """
    subprocess_ids: list[str] = []
    resident_ids: list[str] = []
    for item in items:
        names = _marker_names(item)
        if SUBPROCESS_GPU in names:
            subprocess_ids.append(item.nodeid)
        elif names & GPU_MARKERS:
            resident_ids.append(item.nodeid)
    return subprocess_ids, resident_ids


def coscheduled_mps_tiers(
    items: Sequence[TieredItem],
) -> tuple[list[str], list[str]]:
    """Return selected MPS and non-MPS hardware test ids.

    An MPS selection runs a real model stack on unified-memory Apple silicon.
    Every other slow tier is coordinated for the CUDA fleet and must remain in
    its own pytest session.
    """
    mps_ids: list[str] = []
    other_hardware_ids: list[str] = []
    other_hardware_tiers = SLOW_TIERS - {MPS}
    for item in items:
        names = _marker_names(item)
        if MPS in names:
            mps_ids.append(item.nodeid)
        if names & other_hardware_tiers:
            other_hardware_ids.append(item.nodeid)
    return mps_ids, other_hardware_ids


def coscheduled_gpu_failure_message(
    subprocess_ids: list[str], resident_ids: list[str]
) -> str:
    """Compose the operator-facing explanation for a co-scheduled GPU selection."""
    exclusion = " or ".join(sorted(GPU_MARKERS))
    return (
        f"refusing this selection: it runs {len(subprocess_ids)} {SUBPROCESS_GPU} "
        f"test(s) alongside {len(resident_ids)} that hold a model resident.\n\n"
        f"Subprocess tier, first few:\n{_listing(subprocess_ids[:3])}\n"
        f"Resident tier, first few:\n{_listing(resident_ids[:3])}\n\n"
        "Those cannot share a device: the resident tier keeps its models loaded "
        "while each subprocess test spawns a service that loads its own, and the "
        "combined footprint exceeds the card. The symptom is not an "
        "out-of-memory error but a spawned service that never becomes healthy, "
        "surfacing as an unrelated-looking timeout late in a long run.\n\n"
        "Run them as two sequential selections instead: "
        f"-m '({exclusion}) and not {SUBPROCESS_GPU}' followed by "
        f"-m {SUBPROCESS_GPU}."
    )


def enforce_device_tier_isolation(items: Sequence[TieredItem]) -> None:
    """Abort the session when one selection reaches both device tiers.

    Raises:
        pytest.UsageError: When the selection mixes incompatible CUDA tiers,
            or mixes the MPS tier with another hardware tier.
    """
    subprocess_ids, resident_ids = coscheduled_device_tiers(items)
    if subprocess_ids and resident_ids:
        raise pytest.UsageError(
            coscheduled_gpu_failure_message(subprocess_ids, resident_ids)
        )
    mps_ids, other_hardware_ids = coscheduled_mps_tiers(items)
    if mps_ids and other_hardware_ids:
        raise pytest.UsageError(
            "refusing this selection: Apple silicon MPS tests must run in their "
            "own hardware tier, separate from CUDA-coordinated tests.\n\n"
            f"MPS tier, first few:\n{_listing(mps_ids[:3])}\n"
            "Other hardware tier, first few:\n"
            f"{_listing(other_hardware_ids[:3])}\n\n"
            f"Run the MPS guard alone with `-m {MPS}`."
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
