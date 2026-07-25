"""The test-tier vocabulary and the collection-time gate that enforces it.

Every test declares which lane it belongs to. The fast lane is selected by
EXCLUDING the slow tiers rather than by naming the fast one, so a test that
declares nothing is not skipped - it is pulled into the fast lane and run on a
machine that may have neither a GPU nor a Hugging Face token. The inverse costs
just as much: a module-level ``pytestmark`` is ADDED to a test's own decorator
rather than overridden by it, so a blanket module default drags GPU tests into
``-m unit``.

Both rules are enforced at collection time, from the root conftest, so they run
on every pytest invocation rather than only where someone remembered a gate.
The vocabulary lives here rather than in that conftest so the enforcement can be
exercised by ordinary in-package tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = [
    "FAST_TIER",
    "GPU_MARKERS",
    "SLOW_TIERS",
    "SUBPROCESS_GPU",
    "TIER_MARKERS",
    "enforce_tiers",
    "group_gpu_items",
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


class GroupableItem(TieredItem, Protocol):
    """A collected item that can also be given a scheduling group."""

    def add_marker(self, marker: pytest.MarkDecorator) -> None: ...


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


def group_gpu_items(items: Sequence[GroupableItem]) -> None:
    """Put every GPU-bound test in one xdist group so they never co-schedule."""
    gpu_group = pytest.mark.xdist_group("gpu")
    for item in items:
        if _marker_names(item) & GPU_MARKERS:
            item.add_marker(gpu_group)
