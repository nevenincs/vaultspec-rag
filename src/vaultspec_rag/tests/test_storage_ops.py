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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ..config import reset_config
from ..storage_manifest import load_manifest, record_root, update_orphan_stamps
from ..storage_ops import ReclaimPolicy, evaluate_reclaim, sweep_archive
from ..storage_survey import NamespaceSurvey

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

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
def isolated_status_dir(tmp_path: Path) -> Iterator[None]:
    """Point the manifest's managed dir at a temp path via the env seam."""
    key = "VAULTSPEC_RAG_STATUS_DIR"
    prev = os.environ.get(key)
    os.environ[key] = str(tmp_path / "managed")
    reset_config()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev
        reset_config()


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
        root=str(
            pathlib.Path(tempfile.gettempdir()) / f"vaultspec-livetest-{prefix}"
        ),
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
        last_indexed = {
            ephemeral_prefix: (_NOW - timedelta(hours=1000)).isoformat()
        }
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
