"""Unit tests for the scheduled reclamation policy engine.

Pure logic and filesystem: no GPU, no Qdrant, no service. The grace
clocks persist through the real manifest under an isolated
``VAULTSPEC_RAG_STATUS_DIR`` (no monkeypatch), exactly how the manifest
suite isolates runtime state. The client-coupled paths
(``archive_prefix``, ``run_maintenance_cycle``) are covered at the
integration tier against a live daemon.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from ..storage_manifest import load_manifest, record_root, update_orphan_stamps
from ..storage_ops import (
    GeometryEntry,
    ReclaimPolicy,
    ReconcileResult,
    evaluate_reclaim,
    plan_reconcile,
    sweep_archive,
)
from ..storage_survey import NamespaceSurvey
from ..store_schema import SERVER_SEGMENT_NUMBER

if TYPE_CHECKING:
    from pathlib import Path

    from qdrant_client import QdrantClient

pytestmark = [pytest.mark.unit]

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
_POLICY = ReclaimPolicy(
    grace_hours=24.0,
    grace_hours_data=168.0,
    max_per_cycle=16,
    archive_retention_days=30.0,
    archive_max_bytes=10_000,
)


@pytest.fixture(autouse=True)
def isolate_manifest_dir(isolated_status_dir: Path) -> None:
    """Resolve the manifest under a temp managed dir for every test here."""
    del isolated_status_dir


def _survey(
    prefix: str,
    status: str = "orphaned",
    points: int = 0,
    footprint: int = 100,
) -> NamespaceSurvey:
    return NamespaceSurvey(
        prefix=prefix,
        root=f"C:/gone/{prefix}",
        status=status,
        collections=[f"{prefix}vault_docs"],
        points=points,
        footprint_bytes=footprint,
    )


class TestOrphanStamps:
    """The persisted grace clock: stamp, preserve, reset."""

    def test_new_orphan_is_stamped(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        root.mkdir()
        entry = record_root(root, backend="server")
        stamps = update_orphan_stamps(
            {entry.prefix: "orphaned"}, now_iso=_NOW.isoformat()
        )
        assert stamps[entry.prefix] == _NOW.isoformat()
        assert load_manifest()[entry.prefix].first_seen_orphaned == _NOW.isoformat()

    def test_existing_stamp_survives_later_scans(self, tmp_path: Path) -> None:
        # The clock measures CONTINUOUS orphan-hood: a second observation
        # (e.g. after a daemon restart) must not reset it.
        root = tmp_path / "proj"
        root.mkdir()
        entry = record_root(root, backend="server")
        update_orphan_stamps({entry.prefix: "orphaned"}, now_iso=_NOW.isoformat())
        later = (_NOW + timedelta(hours=5)).isoformat()
        stamps = update_orphan_stamps({entry.prefix: "orphaned"}, now_iso=later)
        assert stamps[entry.prefix] == _NOW.isoformat()

    @pytest.mark.parametrize("status", ["live", "unverifiable"])
    def test_non_orphan_observation_clears_the_stamp(
        self, tmp_path: Path, status: str
    ) -> None:
        root = tmp_path / "proj"
        root.mkdir()
        entry = record_root(root, backend="server")
        update_orphan_stamps({entry.prefix: "orphaned"}, now_iso=_NOW.isoformat())
        stamps = update_orphan_stamps(
            {entry.prefix: status}, now_iso=(_NOW + timedelta(hours=1)).isoformat()
        )
        assert stamps[entry.prefix] == ""
        assert load_manifest()[entry.prefix].first_seen_orphaned == ""

    def test_unknown_prefix_is_ignored(self) -> None:
        stamps = update_orphan_stamps(
            {"rdeadbeef0000_": "orphaned"}, now_iso=_NOW.isoformat()
        )
        assert stamps == {}


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


class TestSweepArchive:
    """Age-based retention and oldest-first byte-cap eviction."""

    def _touch(self, path: Path, *, size: int, age_days: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        mtime = (_NOW - timedelta(days=age_days)).timestamp()
        os.utime(path, (mtime, mtime))

    def test_missing_dir_is_a_noop(self, tmp_path: Path) -> None:
        assert (
            sweep_archive(
                tmp_path / "absent",
                now=_NOW,
                retention_days=30.0,
                max_total_bytes=10_000,
            )
            == []
        )

    def test_expired_archives_are_deleted(self, tmp_path: Path) -> None:
        archive = tmp_path / "archive"
        self._touch(archive / "p1" / "old.snapshot", size=10, age_days=31)
        self._touch(archive / "p1" / "fresh.snapshot", size=10, age_days=1)
        deleted = sweep_archive(
            archive, now=_NOW, retention_days=30.0, max_total_bytes=10_000
        )
        assert [p.name for p in deleted] == ["old.snapshot"]
        assert (archive / "p1" / "fresh.snapshot").exists()

    def test_byte_cap_evicts_oldest_first(self, tmp_path: Path) -> None:
        archive = tmp_path / "archive"
        self._touch(archive / "a.snapshot", size=600, age_days=3)
        self._touch(archive / "b.snapshot", size=600, age_days=2)
        self._touch(archive / "c.snapshot", size=600, age_days=1)
        deleted = sweep_archive(
            archive, now=_NOW, retention_days=30.0, max_total_bytes=1300
        )
        assert [p.name for p in deleted] == ["a.snapshot"]
        assert not (archive / "a.snapshot").exists()
        assert (archive / "b.snapshot").exists()
        assert (archive / "c.snapshot").exists()


@pytest.fixture
def cold_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each snapshot test from a cold (unpublished) slot."""
    from ..server import _state

    monkeypatch.setattr(_state, "_survey_snapshot", None)


@pytest.mark.usefixtures("cold_snapshot")
class TestSurveySnapshot:
    """The daemon-held snapshot slot: publish, read, replace."""

    def test_cold_slot_reads_none(self) -> None:
        from ..server._state import survey_snapshot

        assert survey_snapshot() is None

    def test_publish_then_read_roundtrip(self) -> None:
        from ..server._state import publish_survey_snapshot, survey_snapshot

        publish_survey_snapshot([_survey("r" + "a" * 12 + "_")], computed_at="t1")
        snapshot = survey_snapshot()
        assert snapshot is not None
        assert snapshot.computed_at == "t1"
        assert [s.prefix for s in snapshot.surveys] == ["r" + "a" * 12 + "_"]

    def test_republish_replaces_whole_snapshot(self) -> None:
        from ..server._state import publish_survey_snapshot, survey_snapshot

        publish_survey_snapshot([_survey("r" + "a" * 12 + "_")], computed_at="t1")
        publish_survey_snapshot(
            [_survey("r" + "b" * 12 + "_"), _survey("r" + "c" * 12 + "_")],
            computed_at="t2",
        )
        snapshot = survey_snapshot()
        assert snapshot is not None
        assert snapshot.computed_at == "t2"
        assert len(snapshot.surveys) == 2


@pytest.mark.usefixtures("cold_snapshot")
class TestGatherStorageSurveyCached:
    """The route helper answers from the snapshot and only walks on demand."""

    def _publish(self, surveys: list[NamespaceSurvey], computed_at: str) -> None:
        from ..server._state import publish_survey_snapshot

        publish_survey_snapshot(surveys, computed_at=computed_at)

    def test_cached_answer_never_opens_a_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ..server import _routes

        def _fail() -> list[NamespaceSurvey]:
            raise AssertionError("cache hit must not walk the store")

        monkeypatch.setattr(_routes, "_fetch_surveys", _fail)
        self._publish([_survey("r" + "a" * 12 + "_", status="live")], computed_at="t1")
        payload = _routes._gather_storage_survey(None, 200)
        assert payload["source"] == "cache"
        assert payload["computed_at"] == "t1"
        assert payload["returned"] == 1

    def test_filters_and_limit_apply_to_the_cached_list(self) -> None:
        from ..server import _routes

        self._publish(
            [
                _survey("r" + "a" * 12 + "_", status="orphaned"),
                _survey("r" + "b" * 12 + "_", status="orphaned"),
                _survey("r" + "c" * 12 + "_", status="live"),
            ],
            computed_at="t1",
        )
        payload = _routes._gather_storage_survey("orphaned", 1)
        assert payload["total"] == 2
        assert payload["returned"] == 1
        assert payload["namespaces"][0]["status"] == "orphaned"

    def test_fresh_recomputes_and_publishes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ..server import _routes
        from ..server._state import survey_snapshot

        self._publish([_survey("r" + "a" * 12 + "_")], computed_at="t1")
        fetched = [_survey("r" + "b" * 12 + "_", status="live")]
        monkeypatch.setattr(_routes, "_fetch_surveys", lambda: fetched)
        payload = _routes._gather_storage_survey(None, 200, fresh=True)
        assert payload["source"] == "fresh"
        assert payload["namespaces"][0]["prefix"] == "r" + "b" * 12 + "_"
        snapshot = survey_snapshot()
        assert snapshot is not None
        assert snapshot.computed_at == payload["computed_at"]
        assert [s.prefix for s in snapshot.surveys] == ["r" + "b" * 12 + "_"]

    def test_cold_cache_falls_back_to_fresh_compute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ..server import _routes

        monkeypatch.setattr(
            _routes, "_fetch_surveys", lambda: [_survey("r" + "d" * 12 + "_")]
        )
        payload = _routes._gather_storage_survey(None, 200)
        assert payload["source"] == "fresh"
        assert payload["returned"] == 1


def _temp_survey(
    prefix: str,
    points: int = 0,
    footprint: int = 2_100,
) -> NamespaceSurvey:
    import pathlib
    import tempfile

    return NamespaceSurvey(
        prefix=prefix,
        root=str(pathlib.Path(tempfile.gettempdir()) / f"vaultspec-livetest-{prefix}"),
        status="live",
        collections=[f"{prefix}vault_docs"],
        points=points,
        footprint_bytes=footprint,
    )


class TestEphemeralIdleTier:
    """Live temp-rooted namespaces reclaim on the persisted idle TTL."""

    def _decide(
        self,
        surveys: list[NamespaceSurvey],
        last_indexed: dict[str, str] | None,
        policy: ReclaimPolicy = _POLICY,
    ):
        return evaluate_reclaim(
            surveys, {}, now=_NOW, policy=policy, last_indexed=last_indexed
        )

    def test_idle_empty_temp_namespace_reclaims(self) -> None:
        prefix = "raaaaaaaaaaa1_"
        stamp = (_NOW - timedelta(hours=100)).isoformat()
        decisions = self._decide([_temp_survey(prefix)], {prefix: stamp})
        assert [d.action for d in decisions] == ["reclaim_empty"]
        assert decisions[0].reason == "ephemeral_idle"

    def test_idle_data_temp_namespace_takes_archive_path(self) -> None:
        prefix = "raaaaaaaaaaa2_"
        stamp = (_NOW - timedelta(hours=100)).isoformat()
        decisions = self._decide([_temp_survey(prefix, points=10)], {prefix: stamp})
        assert [d.action for d in decisions] == ["reclaim_data"]
        assert decisions[0].tier == "data"

    def test_fresh_activity_is_pending(self) -> None:
        prefix = "raaaaaaaaaaa3_"
        stamp = (_NOW - timedelta(hours=1)).isoformat()
        decisions = self._decide([_temp_survey(prefix)], {prefix: stamp})
        assert [d.action for d in decisions] == ["pending"]
        assert decisions[0].reason is not None
        assert decisions[0].reason.startswith("ephemeral_idle_remaining_h=")

    def test_missing_activity_stamp_is_pending(self) -> None:
        prefix = "raaaaaaaaaaa4_"
        decisions = self._decide([_temp_survey(prefix)], {})
        assert [d.action for d in decisions] == ["pending"]
        assert decisions[0].reason == "ephemeral_no_activity_stamp"

    def test_non_temp_live_namespace_is_untouched(self) -> None:
        stamp = (_NOW - timedelta(hours=1000)).isoformat()
        survey = _survey("raaaaaaaaaaa5_", status="live")
        decisions = self._decide([survey], {"raaaaaaaaaaa5_": stamp})
        assert decisions == []

    def test_zero_ttl_disables_the_tier(self) -> None:
        prefix = "raaaaaaaaaaa6_"
        stamp = (_NOW - timedelta(hours=1000)).isoformat()
        policy = ReclaimPolicy(ephemeral_idle_hours=0.0)
        decisions = self._decide([_temp_survey(prefix)], {prefix: stamp}, policy)
        assert decisions == []

    def test_absent_last_indexed_mapping_skips_the_tier(self) -> None:
        decisions = self._decide([_temp_survey("raaaaaaaaaaa7_")], None)
        assert decisions == []

    def test_orphans_keep_priority_under_the_shared_cap(self) -> None:
        policy = ReclaimPolicy(grace_hours=24.0, max_per_cycle=1)
        orphan = _survey("raaaaaaaaaaa8_")
        ephemeral_prefix = "raaaaaaaaaaa9_"
        stamps = {"raaaaaaaaaaa8_": (_NOW - timedelta(hours=48)).isoformat()}
        last_indexed = {ephemeral_prefix: (_NOW - timedelta(hours=1000)).isoformat()}
        decisions = evaluate_reclaim(
            [orphan, _temp_survey(ephemeral_prefix)],
            stamps,
            now=_NOW,
            policy=policy,
            last_indexed=last_indexed,
        )
        by_prefix = {d.prefix: d for d in decisions}
        assert by_prefix["raaaaaaaaaaa8_"].action == "reclaim_empty"
        assert by_prefix[ephemeral_prefix].action == "deferred"
        assert by_prefix[ephemeral_prefix].reason == "over_cycle_cap"


class TestLastIndexedStamping:
    """record_root's last_indexed stamp is the ephemeral activity clock."""

    def test_fresh_stamp_overwrites_and_persists(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        root.mkdir()
        record_root(root, backend="server")
        record_root(root, backend="server", last_indexed="2026-07-21T10:00:00+00:00")
        entry = next(iter(load_manifest().values()))
        assert entry.last_indexed == "2026-07-21T10:00:00+00:00"


class _FakeCollections:
    def __init__(self, names: list[str]) -> None:
        import types

        self.collections = [types.SimpleNamespace(name=n) for n in names]


class _FakeClient:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    def get_collections(self) -> _FakeCollections:
        return _FakeCollections(self._names)


class TestDebrisVisibility:
    """Config-less collection dirs surface as debris and are reclaimable."""

    def _make_debris(self, storage: Path) -> Path:
        debris_dir = storage / "rdeadbeef0000_codebase_docs"
        (debris_dir / "segments").mkdir(parents=True)
        (debris_dir / "segments" / "seg.dat").write_bytes(b"x" * 2048)
        return debris_dir

    def test_debris_dirs_surface_with_footprint(self, tmp_path: Path) -> None:
        from ..storage_ops import debris_surveys

        storage = tmp_path / "collections"
        storage.mkdir()
        live_dir = storage / "rlive00000000_vault_docs"
        live_dir.mkdir()
        self._make_debris(storage)
        surveys = debris_surveys(["rlive00000000_vault_docs"], storage)
        assert len(surveys) == 1
        assert surveys[0].status == "debris"
        assert surveys[0].collections == ["rdeadbeef0000_codebase_docs"]
        assert surveys[0].footprint_bytes == 2048
        assert surveys[0].points == 0

    def test_no_storage_dir_yields_no_debris(self) -> None:
        from ..storage_ops import debris_surveys

        assert debris_surveys(["a"], None) == []

    def test_backend_totals_roll_up_all_statuses(self) -> None:
        from ..storage_ops import backend_totals

        surveys = [
            _survey("raaaaaaaaaaa1_", status="live", footprint=100),
            _survey("raaaaaaaaaaa2_", status="orphaned", footprint=50),
            NamespaceSurvey(
                prefix="rdeadbeef0000_",
                root=None,
                status="debris",
                collections=["rdeadbeef0000_codebase_docs"],
                footprint_bytes=25,
            ),
        ]
        totals = backend_totals(surveys)
        assert totals["total_bytes"] == 175
        assert totals["namespaces"] == 3
        assert totals["by_status_bytes"] == {
            "live": 100,
            "orphaned": 50,
            "debris": 25,
        }

    def test_prune_debris_dry_run_removes_nothing(self, tmp_path: Path) -> None:
        from ..storage_ops import prune_debris

        storage = tmp_path / "collections"
        storage.mkdir()
        debris_dir = self._make_debris(storage)
        result = prune_debris(
            cast("QdrantClient", _FakeClient([])), storage, dry_run=True
        )
        assert [r.status for r in result.results] == ["would_remove"]
        assert result.reclaimed_bytes == 2048
        assert debris_dir.exists()

    def test_prune_debris_removes_only_unlisted_dirs(self, tmp_path: Path) -> None:
        from ..storage_ops import prune_debris

        storage = tmp_path / "collections"
        storage.mkdir()
        live_dir = storage / "rlive00000000_vault_docs"
        live_dir.mkdir()
        debris_dir = self._make_debris(storage)
        result = prune_debris(
            cast("QdrantClient", _FakeClient(["rlive00000000_vault_docs"])),
            storage,
            dry_run=False,
        )
        assert [r.status for r in result.results] == ["removed"]
        assert not debris_dir.exists()
        assert live_dir.exists()

    def test_prune_debris_with_nothing_to_do_is_success(self, tmp_path: Path) -> None:
        from ..storage_ops import prune_debris

        storage = tmp_path / "collections"
        storage.mkdir()
        result = prune_debris(
            cast("QdrantClient", _FakeClient([])), storage, dry_run=False
        )
        assert result.results == []
        assert result.reclaimed_bytes == 0


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


class TestReconcileResultReclaim:
    """A reclaim figure exists only for a converged measurement."""

    def test_converged_result_reports_the_delta(self) -> None:
        result = ReconcileResult(
            "c",
            "reconciled",
            segments_before=8,
            segments_after=1,
            bytes_before=1_000_000,
            bytes_after=200_000,
        )

        assert result.reclaimed_bytes == 800_000

    def test_converging_result_reports_no_reclaim(self) -> None:
        """Mid-flight sizes are meaningless and must never be reported.

        The optimizer transiently inflates size while restructuring, so a
        still-converging collection has no honest reclaim figure to give.
        """
        result = ReconcileResult(
            "c",
            "converging",
            segments_before=8,
            bytes_before=1_000_000,
            reason="convergence_budget_expired",
        )

        assert result.reclaimed_bytes == 0
        assert result.bytes_after is None

    def test_apparent_growth_never_reports_a_negative_reclaim(self) -> None:
        result = ReconcileResult(
            "c",
            "reconciled",
            segments_before=8,
            segments_after=2,
            bytes_before=100,
            bytes_after=500,
        )

        assert result.reclaimed_bytes == 0


class _ScriptedCollection:
    """One scripted `get_collection` reply."""

    def __init__(self, segments: int, status: str) -> None:
        self.segments_count = segments
        self.status = status
        self.optimizer_status = "ok"


class _ScriptedClient:
    """Replays a scripted optimizer timeline and drives real directory size.

    Convergence depends on *when* readings stop moving, which a live server
    cannot be made to reproduce on demand. Each scripted step names the
    segment count, the collection status, and how many filler blocks should
    exist on disk at that moment - so `_dir_bytes` measures a real directory
    that really inflates and then shrinks, exactly as a merge does.
    """

    def __init__(self, path: Path, steps: list[tuple[int, str, int]]) -> None:
        self._path = path
        self._steps = steps
        self._index = 0
        self.samples = 0

    def _apply_disk(self, blocks: int) -> None:
        self._path.mkdir(parents=True, exist_ok=True)
        for existing in self._path.glob("block_*"):
            existing.unlink()
        for i in range(blocks):
            (self._path / f"block_{i}").write_bytes(b"x" * (2 * 1024 * 1024))

    def get_collection(self, collection_name: str) -> _ScriptedCollection:
        del collection_name  # one scripted timeline; the name is not a key
        step = self._steps[min(self._index, len(self._steps) - 1)]
        segments, status, blocks = step
        self._index += 1
        self.samples += 1
        self._apply_disk(blocks)
        return _ScriptedCollection(segments, status)


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
        from ..storage_ops import _await_convergence

        clock = {"t": 0.0}

        def _monotonic() -> float:
            return clock["t"]

        def _sleep(seconds: float) -> None:
            clock["t"] += seconds

        return _await_convergence(
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

        from ..storage_ops import _await_convergence

        path = tmp_path / "coll"
        client = _ScriptedClient(path, [(9, "yellow", 12)])
        stop = threading.Event()
        stop.set()

        result = _await_convergence(
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


class _GeometryClient(_FakeClient):
    """Answers `get_collection` for every name it lists."""

    def __init__(self, names: list[str], *, target: int = 0) -> None:
        super().__init__(names)
        self._target = target
        self.inspected: list[str] = []

    def get_collection(self, collection_name: str) -> object:
        self.inspected.append(collection_name)
        optimizer = type("_Opt", (), {"default_segment_number": self._target})()
        config = type("_Cfg", (), {"optimizer_config": optimizer})()
        return type(
            "_Info",
            (),
            {"config": config, "segments_count": 8, "status": "green"},
        )()


class TestGeometryScope:
    """Reconcile mutates only namespaces this project owns."""

    def test_foreign_collections_are_never_read_or_reconciled(
        self, tmp_path: Path
    ) -> None:
        """A shared qdrant may hold collections that are not ours.

        Reconcile triggers a multi-GB background merge, so touching a
        foreign collection is an unauthorised mutation of someone else's
        data - the same reason every destructive verb is prefix-guarded.
        """
        from ..storage_ops import read_geometry

        client = _GeometryClient(
            [
                "rfeedfacefeed_vault_docs",
                "some_other_app_collection",
                "not_a_namespace",
                "rNOTHEX000000_vault_docs",
            ]
        )

        names = [
            e.collection for e in read_geometry(cast("QdrantClient", client), tmp_path)
        ]

        assert names == ["rfeedfacefeed_vault_docs"]
        # The guard rejects before inspection, so a foreign collection is
        # never even queried, let alone reconciled.
        assert client.inspected == ["rfeedfacefeed_vault_docs"]

    def test_owned_collection_at_target_is_not_drifted(self, tmp_path: Path) -> None:
        from ..storage_ops import plan_reconcile, read_geometry

        client = _GeometryClient(
            ["rfeedfacefeed_vault_docs"], target=SERVER_SEGMENT_NUMBER
        )

        entries = read_geometry(cast("QdrantClient", client), tmp_path)
        selected, remaining = plan_reconcile(entries, cap=10)

        assert selected == []
        assert remaining == 0


class TestKindPointsCountGenerations:
    """A kind's points must include the generation currently serving it.

    A rebuild publishes into ``<declared>_g<token>`` and moves a pointer, so a
    healthy root is routinely served by a collection whose name does not end
    with the declared suffix. Counting on the suffix alone reported zero code
    points for exactly those roots - a complete index reading as empty on the
    surface an operator checks first.
    """

    def test_a_generation_counts_toward_its_kind(self) -> None:
        """Proven able to fail: restoring the bare ``endswith`` match returns 0."""
        from .. import store_schema
        from ..storage_survey import _kind_points

        suffix = store_schema.CODE_COLLECTION
        generation = f"r0123456789ab_{suffix}_gaaaaaaaaaaaaaaaa"

        assert _kind_points([generation], {generation: 24}, suffix) == 24

    def test_the_declared_collection_still_counts(self) -> None:
        from .. import store_schema
        from ..storage_survey import _kind_points

        suffix = store_schema.CODE_COLLECTION
        declared = f"r0123456789ab_{suffix}"

        assert _kind_points([declared], {declared: 12}, suffix) == 12

    def test_another_kind_never_counts(self) -> None:
        """The widened match must not start absorbing other kinds.

        Proven able to fail: matching on the ``_g`` split alone, without
        requiring the base to end with the kind suffix, counts a vault
        generation toward the code total and fails this.
        """
        from .. import store_schema
        from ..storage_survey import _kind_points

        code = store_schema.CODE_COLLECTION
        vault_generation = f"r0123456789ab_{store_schema.VAULT_COLLECTION}_gbbbb"

        assert _kind_points([vault_generation], {vault_generation: 9}, code) == 0
