"""Unit tests for the safety properties destruction is never allowed to lose.

Two of them, kept together because they answer the same question about two
different subjects.

The first is path containment. Pure filesystem logic: no GPU, no Qdrant, no
service. Escapes are tested through parent traversal and absolute
out-of-base paths, which exercise the resolve-then-compare logic that also
closes symlink escapes (both resolve out of the base) without depending on
symlink-creation privilege.

The second is that the shorter window a temp-rooted orphan draws buys only
time. A namespace of that class is reclaimed sooner than a deleted worktree,
and everything the reclamation contract promises about how it is reclaimed -
the archive that must complete before any point-bearing drop, the point
re-count taken immediately before acting, and the refusal to touch a
namespace that is not provably a dead orphan - is unchanged by it. Those
three are the ones a shorter window would be tempting to trade away, so each
has been broken deliberately and observed to fail on the assertion it names.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ..storage_reclamation import ReclaimPolicy, evaluate_reclaim
from ..storage_safety import StorageSafetyError, is_within, resolve_within
from ..storage_survey import is_temp_rooted
from .test_storage_ops import (
    _NOW,
    _collection_of,
    _CycleClient,
    _orphaned_namespace,
    _outcome_for,
    _run_cycle,
    _temp_survey,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: Hours the ephemeral-orphan tests age their grace stamp by: past the
#: ephemeral window and far short of either tiered one.
_AGED_HOURS = 25.0

#: Both tiered windows pushed well past ``_AGED_HOURS``, so a namespace that
#: is eligible under this policy can only have been admitted by the ephemeral
#: window. A gate test that would also have passed under the ordinary orphan
#: windows proves nothing about the ephemeral path, and the shipped empty
#: window happens to equal the ephemeral one, which is exactly the coincidence
#: that would make a loose test look convincing.
_EPHEMERAL_ONLY = ReclaimPolicy(
    grace_hours=1000.0,
    grace_hours_data=1000.0,
    grace_hours_ephemeral=24.0,
    reconcile=False,
)


def _ephemeral_orphan(tmp_path: Path, *, name: str) -> str:
    """Return an aged orphan whose vanished root was under the OS temp dir.

    The precondition is asserted rather than assumed. These tests are only
    about the ephemeral class, and every one of them would still pass while
    silently exercising an ordinary orphan if the temporary directory the
    harness hands out ever stopped resolving under the OS temp directory.
    A guard that has quietly stopped guarding is worse than no guard.
    """
    assert is_temp_rooted(str(tmp_path)), (
        "these tests need a root under the OS temp directory to reach the "
        f"ephemeral class at all, and {tmp_path} is not one"
    )
    return _orphaned_namespace(tmp_path, now=_NOW, name=name, aged_hours=_AGED_HOURS)


def test_descendant_is_allowed(tmp_path: Path) -> None:
    base = tmp_path / "managed"
    target = base / "qdrant" / "storage"
    target.mkdir(parents=True)
    assert resolve_within(target, base) == target.resolve()
    assert is_within(target, base) is True


def test_base_itself_is_allowed(tmp_path: Path) -> None:
    base = tmp_path / "managed"
    base.mkdir()
    assert resolve_within(base, base) == base.resolve()


def test_parent_traversal_is_rejected(tmp_path: Path) -> None:
    base = tmp_path / "managed"
    base.mkdir()
    escape = base / ".." / ".." / "etc"
    with pytest.raises(StorageSafetyError):
        resolve_within(escape, base)
    assert is_within(escape, base) is False


def test_sibling_outside_base_is_rejected(tmp_path: Path) -> None:
    base = tmp_path / "managed"
    sibling = tmp_path / "other"
    base.mkdir()
    sibling.mkdir()
    with pytest.raises(StorageSafetyError):
        resolve_within(sibling, base)
    assert is_within(sibling, base) is False


def test_deeply_nested_descendant_is_allowed(tmp_path: Path) -> None:
    base = tmp_path / "managed"
    target = base / "a" / "b" / "c" / "d"
    target.mkdir(parents=True)
    assert is_within(target, base) is True


def test_prefix_lookalike_sibling_is_rejected(tmp_path: Path) -> None:
    # `managed-evil` shares a string prefix with `managed` but is not
    # contained: a naive prefix check would wrongly allow it.
    base = tmp_path / "managed"
    lookalike = tmp_path / "managed-evil"
    base.mkdir()
    lookalike.mkdir()
    assert is_within(lookalike, base) is False


@pytest.mark.usefixtures("isolated_status_dir")
class TestEphemeralWindowKeepsEveryDestructionGate:
    """A shorter wait, and nothing else, for the temp-rooted orphan class.

    The manifest these carry their grace clocks in is machine-global state, so
    the class relocates it per test. It is requested here rather than made
    autouse for the module because the path-containment tests above build
    their own fixtures under the same temporary directory.
    """

    def test_the_short_window_does_not_shorten_the_archive_gate(
        self, tmp_path: Path
    ) -> None:
        """A point-bearing ephemeral orphan archives first, or is not dropped.

        Two mutations, each run alone against this test and each observed to
        fail on the assertion named beside it.

        Neutralising the ``reclaim_data`` archive branch in ``_apply_reclaim``
        so the namespace is dropped without a snapshot fails
        ``assert client.snapshotted == [collection]`` - the drop itself still
        happens and still reports ``archived_removed``, so nothing but the
        recorded snapshot distinguishes an archived reclaim from a bare one.

        Swallowing the archive failure there - binding an empty archive list
        instead of returning the ``failed`` decision - fails
        ``assert torn.deleted == []``. The second namespace's archive breaks on
        a missing artifact rather than on a moved point count precisely so that
        no later gate can rescue it: the count is stable, so the drop proceeds
        and the data is destroyed with no archive behind it.
        """
        prefix = _ephemeral_orphan(tmp_path, name="sandbox-archived")
        collection = _collection_of(prefix)
        client = _CycleClient({collection: 10}, snapshots_dir=tmp_path / "snapshots")

        result = _run_cycle(client, tmp_path, policy=_EPHEMERAL_ONLY)

        decision = _outcome_for(result, prefix)
        assert decision.tier == "data"
        assert decision.action == "archived_removed"
        assert client.snapshotted == [collection]
        assert client.deleted == [collection]

        torn_prefix = _ephemeral_orphan(tmp_path, name="sandbox-unarchivable")
        torn_collection = _collection_of(torn_prefix)
        # The stand-in writes its snapshot where the cycle is not looking, so
        # the archive fails on a missing artifact while the point count never
        # moves. Nothing but the archive gate stands between this namespace
        # and the drop.
        torn = _CycleClient(
            {torn_collection: 10}, snapshots_dir=tmp_path / "unreachable"
        )

        torn_result = _run_cycle(torn, tmp_path, policy=_EPHEMERAL_ONLY)

        assert torn.deleted == []
        torn_decision = _outcome_for(torn_result, torn_prefix)
        assert torn_decision.action == "failed"
        assert torn_decision.reason is not None
        # Asserted to the failing cause, not to the ``archive_failed:`` prefix
        # a torn snapshot shares: a prefix match would pass on whichever of
        # the two branches fired.
        assert torn_decision.reason.startswith(
            "archive_failed: snapshot file not found:"
        )

    def test_the_short_window_does_not_skip_the_pre_drop_recount(
        self, tmp_path: Path
    ) -> None:
        """The count is re-read immediately before acting, on this path too.

        Two mutations, each run alone against this test.

        Reading an unverifiable count as a number - replacing the
        ``observed is None`` deferral in ``_pre_drop_reclaim_gate`` with
        ``observed = decision.points`` - fails
        ``assert unverifiable.deleted == []``. A count that could not be
        established agrees with the survey by construction once it is allowed
        to borrow the survey's own number, so the namespace is destroyed on a
        reading nobody took.

        Dropping the ``observed != decision.points`` comparison fails
        ``assert moved.deleted == []``: a writer that landed points between the
        survey and this namespace's turn is invisible to a gate that never
        compares.
        """
        unverifiable_prefix = _ephemeral_orphan(tmp_path, name="sandbox-uncountable")
        unverifiable = _CycleClient(
            {_collection_of(unverifiable_prefix): 10},
            snapshots_dir=tmp_path / "snapshots",
            uncountable=True,
        )

        unverifiable_result = _run_cycle(unverifiable, tmp_path, policy=_EPHEMERAL_ONLY)

        assert unverifiable.deleted == []
        unverifiable_decision = _outcome_for(unverifiable_result, unverifiable_prefix)
        assert unverifiable_decision.action == "deferred"
        # The only reason meaning the count could not be established; the
        # movement branches report their own strings and a loose match would
        # accept a namespace deferred for having been counted successfully.
        assert unverifiable_decision.reason == "points_unverifiable"

        moved_prefix = _ephemeral_orphan(tmp_path, name="sandbox-written-to")
        moved_collection = _collection_of(moved_prefix)
        moved = _CycleClient(
            {moved_collection: 10},
            snapshots_dir=tmp_path / "snapshots",
            counts_after_survey={moved_collection: 25},
        )

        moved_result = _run_cycle(moved, tmp_path, policy=_EPHEMERAL_ONLY)

        assert moved.deleted == []
        # The gate precedes the archive, so a namespace held by it is never
        # snapshotted either: an archive taken across a live writer is torn.
        assert moved.snapshotted == []
        moved_decision = _outcome_for(moved_result, moved_prefix)
        assert moved_decision.action == "deferred"
        assert moved_decision.reason == "points_changed_since_survey"

    def test_the_short_window_never_reaches_an_unattributable_namespace(
        self, tmp_path: Path
    ) -> None:
        """Only a provable orphan draws it; the other classifications cannot.

        Mutation it catches: widening the ``status == "orphaned"`` candidate
        filter in ``evaluate_reclaim`` to admit ``unknown`` and
        ``unverifiable`` as well. Observed to fail
        ``assert [d.prefix for d in decisions] == [reclaimable.prefix]``,
        naming the two namespaces that must never have been decided about.

        The two excluded namespaces are given the same temp root as the
        reclaimable one, which no real ``unknown`` would have - an
        unattributable namespace has no recorded root at all. Handing them one
        anyway isolates the classification as the only thing keeping them out,
        so the test cannot pass merely because a rootless namespace fails the
        temp-rootedness check for an unrelated reason.

        ``unverifiable`` is the one that matters most and the one the shorter
        window makes no allowance for: a root absent because its volume is
        offline is classified here, never as an orphan, and the ephemeral
        window is not a tolerance for that case.
        """
        aged = (_NOW - timedelta(hours=_AGED_HOURS)).isoformat()
        reclaimable = _temp_survey("rccccccccccc1_", points=42, status="orphaned")
        unknown = _temp_survey("rccccccccccc2_", points=42, status="unknown")
        offline = _temp_survey("rccccccccccc3_", points=42, status="unverifiable")
        surveys = [reclaimable, unknown, offline]

        decisions = evaluate_reclaim(
            surveys,
            {survey.prefix: aged for survey in surveys},
            now=_NOW,
            policy=_EPHEMERAL_ONLY,
        )

        assert [d.prefix for d in decisions] == [reclaimable.prefix]
        # The positive control: the path is live under this policy, so the two
        # absences above are exclusions rather than an inert evaluation.
        assert decisions[0].action == "reclaim_data"

        # And at cycle level, where an unattributable namespace is what it
        # really is: a temp-rooted collection with no manifest entry behind it.
        stray = "r0123456789ab_vault_docs"
        client = _CycleClient({stray: 42}, snapshots_dir=tmp_path / "snapshots")

        result = _run_cycle(client, tmp_path, policy=_EPHEMERAL_ONLY)

        assert client.deleted == []
        assert [d.prefix for d in result.decisions] == []
