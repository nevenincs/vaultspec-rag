"""test storage ops: the reclaim half."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING, cast

import pytest

from .._store_models import root_collection_prefix
from ..storage_identity import load_identity, record_identity
from ..storage_migration import MigrateResult, carry_migrated_identity
from ..storage_reclamation import (
    ReclaimPolicy,
    evaluate_reclaim,
)
from ..storage_reconciliation import GeometryEntry, plan_reconcile
from ..store_schema import (
    SERVER_SEGMENT_NUMBER,
)
from .test_storage_ops import (
    _NOW,
    _POLICY,
    _identity,
    _ScriptedClient,
    _survey,
)

if TYPE_CHECKING:
    from pathlib import Path

    from qdrant_client import QdrantClient

pytestmark = [pytest.mark.unit]


class TestMigrateCarriesIdentity:
    """A copied namespace inherits provenance, or honestly inherits none.

    Pure filesystem: the carry only touches the two identity homes and the
    migrate results it is handed, so it needs no server. The real copy is
    covered against a live daemon at the integration tier.
    """

    @staticmethod
    def _migrated(source: str, target: str) -> list[MigrateResult]:
        return [MigrateResult(source, target, "migrated", 1)]

    def test_local_to_server_carries_the_source_stamp(self, tmp_path: Path) -> None:
        """The source's own record moves onto the remapped target name.

        Mutation it catches: stamping the destination with
        ``current_identity()`` instead of the loaded source identity, which
        asserts that this process produced vectors it only copied - the exact
        laundering that lets a namespace claim conformance it never
        established. The asserted model is one no running configuration would
        ever produce, so a restamp cannot accidentally satisfy it.
        """
        root = tmp_path / "proj"
        local_dir = root / ".vaultspec-rag" / "qdrant"
        local_dir.mkdir(parents=True)
        prefix = root_collection_prefix(root)
        target = f"{prefix}vault_docs"
        record_identity(
            root,
            backend="local",
            collection="vault_docs",
            identity=_identity(dense_model="superseded/dense"),
            local_dir=local_dir,
        )

        carried = carry_migrated_identity(
            root,
            name_map={"vault_docs": target},
            to_backend="server",
            local_dir=local_dir,
            results=self._migrated("vault_docs", target),
        )

        assert carried == [target]
        got = load_identity(root, backend="server", collection=target)
        assert got is not None
        assert got.dense_model == "superseded/dense"

    def test_server_to_local_carries_into_the_sidecar(self, tmp_path: Path) -> None:
        """The reverse direction lands in the other home, keyed by bare name.

        Mutation it catches: writing both directions to one home, which leaves
        the destination of a server-to-local migrate unverifiable because local
        reads never consult the manifest.
        """
        root = tmp_path / "proj"
        local_dir = root / ".vaultspec-rag" / "qdrant"
        local_dir.mkdir(parents=True)
        prefix = root_collection_prefix(root)
        source = f"{prefix}vault_docs"
        record_identity(
            root,
            backend="server",
            collection=source,
            identity=_identity(dense_model="superseded/dense"),
        )

        carried = carry_migrated_identity(
            root,
            name_map={source: "vault_docs"},
            to_backend="local",
            local_dir=local_dir,
            results=self._migrated(source, "vault_docs"),
        )

        assert carried == ["vault_docs"]
        got = load_identity(
            root, backend="local", collection="vault_docs", local_dir=local_dir
        )
        assert got is not None
        assert got.dense_model == "superseded/dense"

    def test_an_unstamped_source_leaves_the_target_unverifiable(
        self, tmp_path: Path
    ) -> None:
        """Copying provenance nobody recorded must invent none.

        Mutation it catches: falling back to ``current_identity()`` when the
        source carries no stamp, which manufactures the very claim the record
        exists to prove and scores a pre-stamping namespace as conforming the
        moment it is moved.
        """
        root = tmp_path / "proj"
        local_dir = root / ".vaultspec-rag" / "qdrant"
        local_dir.mkdir(parents=True)
        prefix = root_collection_prefix(root)
        target = f"{prefix}vault_docs"

        carried = carry_migrated_identity(
            root,
            name_map={"vault_docs": target},
            to_backend="server",
            local_dir=local_dir,
            results=self._migrated("vault_docs", target),
        )

        assert carried == []
        assert load_identity(root, backend="server", collection=target) is None

    def test_a_copy_that_did_not_happen_carries_nothing(self, tmp_path: Path) -> None:
        """Only an applied copy earns provenance.

        Mutation it catches: iterating ``name_map`` without consulting the
        migrate results, which stamps a target that a skipped or failed copy
        never wrote - a namespace claiming provenance for data that is not
        there.
        """
        root = tmp_path / "proj"
        local_dir = root / ".vaultspec-rag" / "qdrant"
        local_dir.mkdir(parents=True)
        prefix = root_collection_prefix(root)
        target = f"{prefix}vault_docs"
        record_identity(
            root,
            backend="local",
            collection="vault_docs",
            identity=_identity(),
            local_dir=local_dir,
        )

        carried = carry_migrated_identity(
            root,
            name_map={"vault_docs": target},
            to_backend="server",
            local_dir=local_dir,
            results=[
                MigrateResult("vault_docs", target, "skipped", 1, "target_exists")
            ],
        )

        assert carried == []
        assert load_identity(root, backend="server", collection=target) is None


class TestEvaluateReclaim:
    """The stacked safety gates, tier windows, and per-cycle cap."""

    def test_unstamped_orphan_is_pending(self) -> None:
        decisions = evaluate_reclaim(
            [_survey("r000000000001_")], {}, now=_NOW, policy=_POLICY
        )
        assert [d.action for d in decisions] == ["pending"]
        assert decisions[0].reason == "grace_started"

    def test_young_orphan_is_pending(self) -> None:
        stamp = (_NOW - timedelta(hours=23)).isoformat()
        decisions = evaluate_reclaim(
            [_survey("r000000000001_")],
            {"r000000000001_": stamp},
            now=_NOW,
            policy=_POLICY,
        )
        assert decisions[0].action == "pending"
        assert (decisions[0].reason or "").startswith("grace_remaining")

    def test_aged_empty_orphan_is_eligible(self) -> None:
        stamp = (_NOW - timedelta(hours=25)).isoformat()
        decisions = evaluate_reclaim(
            [_survey("r000000000001_")],
            {"r000000000001_": stamp},
            now=_NOW,
            policy=_POLICY,
        )
        assert decisions[0].action == "reclaim_empty"
        assert decisions[0].tier == "empty"

    def test_data_tier_needs_the_longer_window(self) -> None:
        # Old enough for the empty tier but not for the data tier.
        stamp = (_NOW - timedelta(hours=48)).isoformat()
        decisions = evaluate_reclaim(
            [_survey("r000000000001_", points=42)],
            {"r000000000001_": stamp},
            now=_NOW,
            policy=_POLICY,
        )
        assert decisions[0].action == "pending"
        old = (_NOW - timedelta(hours=169)).isoformat()
        decisions = evaluate_reclaim(
            [_survey("r000000000001_", points=42)],
            {"r000000000001_": old},
            now=_NOW,
            policy=_POLICY,
        )
        assert decisions[0].action == "reclaim_data"
        assert decisions[0].tier == "data"

    def test_non_orphaned_statuses_never_appear(self) -> None:
        surveys = [
            _survey("r000000000001_", status="live"),
            _survey("r000000000002_", status="unknown"),
            _survey("r000000000003_", status="unverifiable"),
        ]
        assert evaluate_reclaim(surveys, {}, now=_NOW, policy=_POLICY) == []

    def test_cycle_cap_defers_and_empties_go_first(self) -> None:
        old = (_NOW - timedelta(hours=1000)).isoformat()
        surveys = [
            _survey("r000000000001_", points=42),
            _survey("r000000000002_"),
            _survey("r000000000003_"),
        ]
        stamps = {s.prefix: old for s in surveys}
        policy = ReclaimPolicy(
            grace_hours=24.0,
            grace_hours_data=168.0,
            max_per_cycle=2,
            archive_retention_days=30.0,
            archive_max_bytes=10_000,
        )
        decisions = evaluate_reclaim(surveys, stamps, now=_NOW, policy=policy)
        by_prefix = {d.prefix: d for d in decisions}
        # The riskless empty tier fills the cap before the data tier.
        assert by_prefix["r000000000002_"].action == "reclaim_empty"
        assert by_prefix["r000000000003_"].action == "reclaim_empty"
        assert by_prefix["r000000000001_"].action == "deferred"
        assert by_prefix["r000000000001_"].reason == "over_cycle_cap"

    def test_garbage_stamp_restarts_the_window(self) -> None:
        decisions = evaluate_reclaim(
            [_survey("r000000000001_")],
            {"r000000000001_": "not-a-timestamp"},
            now=_NOW,
            policy=_POLICY,
        )
        assert decisions[0].action == "pending"

    def test_provenance_is_not_a_reclamation_input(self) -> None:
        """Reachability decides a reclaim; what produced the vectors never does.

        Two classifications share the word ``unverifiable`` and this pins them
        apart in both directions, because wiring either one into the other
        breaks something silently.

        Mutation the first assertion catches: gating a reclaim on the namespace
        carrying a stamped model. That reads as caution and is a leak - every
        namespace written before stamping existed would be exempt forever, and
        an orphan's root is already gone, so it can never be rebuilt into a
        stamp.

        Mutation the second catches: admitting a namespace whose root could not
        be confirmed absent because its provenance is known. Full provenance
        says nothing about whether the volume is merely offline.
        """
        aged = (_NOW - timedelta(hours=25)).isoformat()

        unstamped_orphan = _survey("r000000000001_", models={})
        decisions = evaluate_reclaim(
            [unstamped_orphan],
            {"r000000000001_": aged},
            now=_NOW,
            policy=_POLICY,
        )
        assert [d.action for d in decisions] == ["reclaim_empty"]

        stamped_unreachable = _survey(
            "r000000000002_",
            status="unverifiable",
            models={"r000000000002_vault_docs": "acme/dense-v1"},
        )
        assert (
            evaluate_reclaim(
                [stamped_unreachable],
                {"r000000000002_": aged},
                now=_NOW,
                policy=_POLICY,
            )
            == []
        )


class TestConvergenceDetection:
    """The convergence contract, driven deterministically.

    These pin the behaviour the whole feature rests on: a reclaim figure is
    published only for a merge that was watched from start to finish. The
    real-server integration tests prove reclamation happens; only a scripted
    timeline can prove the *timing* rules, because a live optimizer cannot be
    told to stall.
    """

    @staticmethod
    def _wait(client: object, path: Path, budget_s: float = 60.0):
        from ..storage_reconciliation import await_convergence

        clock = {"t": 0.0}

        def _monotonic() -> float:
            return clock["t"]

        def _sleep(seconds: float) -> None:
            clock["t"] += seconds

        return await_convergence(
            cast("QdrantClient", client),
            "rfeedfacefeed_vault_docs",
            path,
            budget_s=budget_s,
            poll_s=1.0,
            sleep=_sleep,
            monotonic=_monotonic,
        )

    def test_queued_merge_is_not_mistaken_for_a_converged_one(
        self, tmp_path: Path
    ) -> None:
        """A merge waiting on a busy optimizer is perfectly stable too.

        `optimizer_status` has no busy state, so if convergence were judged
        on stability alone, a collection sitting in the optimizer queue -
        unchanged segments, unchanged size - would be measured before it
        ever merged and its untouched footprint published as a reclaim.
        """
        path = tmp_path / "coll"
        # Pending forever: qdrant reports grey ("possible but not triggered").
        client = _ScriptedClient(path, [(8, "grey", 8)])

        assert self._wait(client, path, budget_s=30.0) is None

    def test_mid_merge_inflation_never_returns_early(self, tmp_path: Path) -> None:
        """The measurement must be the settled one, not the peak."""
        path = tmp_path / "coll"
        client = _ScriptedClient(
            path,
            [
                (8, "yellow", 8),  # merge starts
                (9, "yellow", 12),  # inflates past where it began
                (9, "yellow", 12),  # ... and holds there for a while
                (9, "yellow", 12),
                (9, "yellow", 12),
                (9, "yellow", 12),
                (2, "green", 3),  # merge lands
                (2, "green", 3),
                (2, "green", 3),
                (2, "green", 3),
                (2, "green", 3),
            ],
        )

        result = self._wait(client, path)

        assert result is not None
        segments, size = result
        assert segments == 2, "returned a mid-flight segment count"
        assert size is not None
        # 3 blocks * 2 MiB, not the 12-block inflated peak.
        assert size < 8 * 1024 * 1024, "published the inflated mid-merge size"

    def test_never_settling_collection_reports_no_measurement(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "coll"
        client = _ScriptedClient(path, [(9, "yellow", 12)])

        assert self._wait(client, path, budget_s=30.0) is None

    def test_collection_with_no_work_settles_without_waiting_out_the_budget(
        self, tmp_path: Path
    ) -> None:
        """Green throughout means there was no merge to watch.

        Reporting its unchanged size is honest - it reclaimed nothing - and
        it must not burn the whole budget to say so.
        """
        path = tmp_path / "coll"
        client = _ScriptedClient(path, [(2, "green", 2)])

        result = self._wait(client, path, budget_s=600.0)

        assert result is not None
        assert result[0] == 2
        # Bounded by the start window, not the full convergence budget.
        assert client.samples < 60

    def test_shutdown_event_abandons_the_wait(self, tmp_path: Path) -> None:
        import threading

        from ..storage_reconciliation import await_convergence

        path = tmp_path / "coll"
        client = _ScriptedClient(path, [(9, "yellow", 12)])
        stop = threading.Event()
        stop.set()

        result = await_convergence(
            cast("QdrantClient", client),
            "rfeedfacefeed_vault_docs",
            path,
            budget_s=600.0,
            poll_s=1.0,
            sleep=lambda _: None,
            monotonic=time.monotonic,
            stop=stop,
        )

        assert result is None
        assert client.samples == 0, "sampled despite shutdown"


class TestPlanReconcile:
    """Selection logic for the geometry reconcile pass.

    Pure decision logic, so it is exercised directly: which collections
    count as drifted, how the per-pass cap applies, and what is left over.
    The client-coupled reconcile itself is covered at the integration tier
    against a real server, because only a real optimizer can prove the
    reclamation and the convergence behaviour.
    """

    @staticmethod
    def _entry(
        name: str,
        *,
        target: int,
        segments: int = 8,
        size: int | None = 1000,
    ) -> GeometryEntry:
        return GeometryEntry(
            collection=name,
            segment_target=target,
            segments=segments,
            footprint_bytes=size,
        )

    def test_collection_already_at_target_is_not_drifted(self) -> None:
        entries = [self._entry("at_target", target=SERVER_SEGMENT_NUMBER)]

        selected, remaining = plan_reconcile(entries, cap=10)

        assert selected == []
        assert remaining == 0

    def test_actual_segment_count_does_not_imply_drift(self) -> None:
        """A big collection legitimately grows segments past the target.

        The setting is what drifts, not the outcome: the optimizer is
        supposed to add segments as real data arrives, and reconciling
        such a collection every cycle would be perpetual pointless work.
        """
        entries = [
            self._entry("busy", target=SERVER_SEGMENT_NUMBER, segments=32),
        ]

        selected, _ = plan_reconcile(entries, cap=10)

        assert selected == []

    def test_server_default_zero_target_is_drifted(self) -> None:
        """``0`` means derive-from-CPU-count - the pre-bound geometry."""
        entries = [self._entry("legacy", target=0)]

        selected, remaining = plan_reconcile(entries, cap=10)

        assert [e.collection for e in selected] == ["legacy"]
        assert remaining == 0

    def test_cap_defers_the_remainder(self) -> None:
        entries = [
            self._entry("a", target=0, size=300),
            self._entry("b", target=0, size=200),
            self._entry("c", target=0, size=100),
        ]

        selected, remaining = plan_reconcile(entries, cap=2)

        assert [e.collection for e in selected] == ["a", "b"]
        assert remaining == 1

    def test_largest_footprint_is_reconciled_first(self) -> None:
        """A capped pass should reclaim the most bytes it can."""
        entries = [
            self._entry("small", target=0, size=10),
            self._entry("huge", target=0, size=9_000),
            self._entry("mid", target=0, size=500),
        ]

        selected, _ = plan_reconcile(entries, cap=3)

        assert [e.collection for e in selected] == ["huge", "mid", "small"]

    def test_unmeasured_footprint_sorts_last_without_being_dropped(self) -> None:
        entries = [
            self._entry("unmeasured", target=0, size=None),
            self._entry("measured", target=0, size=5),
        ]

        selected, remaining = plan_reconcile(entries, cap=5)

        assert [e.collection for e in selected] == ["measured", "unmeasured"]
        assert remaining == 0

    def test_zero_cap_selects_nothing_and_defers_everything(self) -> None:
        entries = [self._entry("a", target=0), self._entry("b", target=0)]

        selected, remaining = plan_reconcile(entries, cap=0)

        assert selected == []
        assert remaining == 2
