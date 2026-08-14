"""Unit tests for the scheduled reclamation policy engine.

Pure logic and filesystem: no GPU, no Qdrant, no service. The grace
clocks persist through the real manifest under an isolated
``VAULTSPEC_RAG_STATUS_DIR`` (no monkeypatch), exactly how the manifest
suite isolates runtime state. The client-coupled paths
(``archive_prefix``, ``run_maintenance_cycle``) are covered at the
integration tier against a live daemon.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, TypedDict, Unpack, cast

import pytest

from .._store_models import root_collection_prefix
from ..job_models import JobOutcomeStatus
from ..storage_manifest import (
    load_manifest,
    record_root,
    update_activity_stamps,
    update_orphan_stamps,
)
from ..storage_reclamation import (
    MaintenanceCycleRequest,
    ReclaimPolicy,
    evaluate_reclaim,
    run_maintenance_cycle,
    sweep_archive,
)
from ..storage_reconciliation import ReconcileResult, plan_reconcile
from ..storage_survey import NamespaceSurvey, is_temp_rooted
from ..store_schema import (
    SERVER_SEGMENT_NUMBER,
    STORAGE_SCHEMA_VERSION,
    VAULT_COLLECTION,
    CollectionIdentity,
)

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
    models: dict[str, str] | None = None,
) -> NamespaceSurvey:
    return NamespaceSurvey(
        prefix=prefix,
        root=f"C:/gone/{prefix}",
        status=status,
        collections=[f"{prefix}vault_docs"],
        points=points,
        footprint_bytes=footprint,
        models=models or {},
    )


class _IdentityOverrides(TypedDict, total=False):
    """The subset of a :class:`CollectionIdentity`'s fields a test may override."""

    dense_model: str
    sparse_model: str | None
    dense_dim: int
    distance: str
    dense_vector_name: str
    sparse_vector_name: str
    storage_schema_version: int


def _identity(**overrides: Unpack[_IdentityOverrides]) -> CollectionIdentity:
    """Build a complete identity, overriding named fields."""
    base: _IdentityOverrides = {
        "dense_model": "acme/dense-v1",
        "sparse_model": "acme/sparse-v1",
        "dense_dim": 1024,
        "distance": "Cosine",
        "dense_vector_name": "dense",
        "sparse_vector_name": "sparse",
        "storage_schema_version": STORAGE_SCHEMA_VERSION,
    }
    base.update(overrides)
    return CollectionIdentity(**base)


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


class TestSweepArchive:
    """Age-based retention and oldest-first whole-archive eviction."""

    def _touch(self, path: Path, *, size: int, age_days: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        mtime = (_NOW - timedelta(days=age_days)).timestamp()
        os.utime(path, (mtime, mtime))

    def _stamp_archive(self, path: Path, *, age_days: float) -> None:
        """Set one completed archive directory's retention clock."""
        path.mkdir(parents=True, exist_ok=True)
        completed_at = _NOW - timedelta(days=age_days)
        (path / "snapshot-manifest.json").write_text(
            json.dumps({"completed_at": completed_at.isoformat()}),
            encoding="utf-8",
        )

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

    def test_expired_archive_is_deleted_as_a_complete_directory(
        self, tmp_path: Path
    ) -> None:
        archive = tmp_path / "archive"
        expired = archive / "p1"
        self._touch(expired / "old.snapshot", size=10, age_days=31)
        self._touch(expired / "snapshot-manifest.json", size=10, age_days=1)
        self._stamp_archive(expired, age_days=31)
        fresh = archive / "p2"
        self._touch(fresh / "fresh.snapshot", size=10, age_days=31)
        self._stamp_archive(fresh, age_days=1)
        deleted = sweep_archive(
            archive, now=_NOW, retention_days=30.0, max_total_bytes=10_000
        )
        assert deleted == [expired]
        assert not expired.exists()
        assert (fresh / "fresh.snapshot").exists()

    def test_byte_cap_evicts_oldest_complete_archive_first(
        self, tmp_path: Path
    ) -> None:
        archive = tmp_path / "archive"
        oldest = archive / "a"
        self._touch(oldest / "a.snapshot", size=600, age_days=1)
        self._touch(oldest / "snapshot-manifest.json", size=20, age_days=1)
        self._stamp_archive(oldest, age_days=3)
        middle = archive / "b"
        self._touch(middle / "b.snapshot", size=600, age_days=1)
        self._touch(middle / "snapshot-manifest.json", size=20, age_days=1)
        self._stamp_archive(middle, age_days=2)
        newest = archive / "c"
        self._touch(newest / "c.snapshot", size=600, age_days=1)
        self._touch(newest / "snapshot-manifest.json", size=20, age_days=1)
        self._stamp_archive(newest, age_days=1)
        deleted = sweep_archive(
            archive, now=_NOW, retention_days=30.0, max_total_bytes=1_300
        )
        assert deleted == [oldest]
        assert not oldest.exists()
        assert (middle / "snapshot-manifest.json").exists()
        assert (newest / "snapshot-manifest.json").exists()

    def test_missing_completion_stamp_is_never_guessed_from_file_mtime(
        self, tmp_path: Path
    ) -> None:
        archive = tmp_path / "archive"
        legacy = archive / "legacy"
        self._touch(legacy / "copied-metadata.json", size=600, age_days=365)
        deleted = sweep_archive(
            archive, now=_NOW, retention_days=30.0, max_total_bytes=0
        )
        assert deleted == []
        assert legacy.exists()


class TestSurveySnapshot:
    """The daemon-held snapshot slot: publish, read, replace."""

    def test_cold_slot_reads_none(self) -> None:
        """A daemon that has published nothing reads no snapshot.

        Run in a fresh interpreter rather than by resetting the global here.
        The slot is process state, so "never published" is a property of a
        process that has not published - setting it back to its initial value
        asserts against a value the test wrote, in an interpreter where
        something may already have published.

        Proven able to fail: initialising the slot to anything but None makes
        the subprocess print a value and the assertion below reports it.
        """
        import subprocess
        import sys

        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "from vaultspec_rag.server._state import survey_snapshot;"
                "from vaultspec_rag.server._routes_storage import"
                " _serve_survey_from_snapshot as serve;"
                "print(survey_snapshot(),"
                " serve(None, 200, None, fresh=False))",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )

        # Both halves of "nothing published": the slot reads empty, and the
        # route refuses to serve from it and defers to a walk.
        assert probe.stdout.strip() == "None None"

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


class TestGatherStorageSurveyCached:
    """The route helper answers from the snapshot and only walks on demand."""

    def _publish(self, surveys: list[NamespaceSurvey], computed_at: str) -> None:
        from ..server._state import publish_survey_snapshot

        publish_survey_snapshot(surveys, computed_at=computed_at)

    def test_cached_answer_never_opens_a_client(
        self,
    ) -> None:
        """A cache hit must answer from the snapshot, never walk the store.

        Proved by observation rather than by forbidding the walk: the published
        snapshot names a prefix that exists in no storage anywhere. A miss would
        walk the real store, which cannot invent that name, so seeing it back is
        the evidence the cache answered.

        Proven able to fail: making ``_gather_storage_survey`` always recompute
        returns a payload without this prefix, failing the identity assertion.
        """
        from ..server import _routes_storage as _routes

        phantom = "r" + "a" * 12 + "_"
        self._publish([_survey(phantom, status="live")], computed_at="t1")
        payload = _routes._gather_storage_survey(None, 200)
        assert payload["source"] == "cache"
        assert payload["computed_at"] == "t1"
        assert payload["returned"] == 1
        namespaces = cast("list[dict[str, object]]", payload["namespaces"])
        assert [n["prefix"] for n in namespaces] == [phantom]

    def test_filters_and_limit_apply_to_the_cached_list(self) -> None:
        from ..server import _routes_storage as _routes

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

    def test_a_walked_result_replaces_the_snapshot_it_answers_from(self) -> None:
        """A fresh walk is adopted whole, and the answer carries its stamp.

        The stale entry is not merged away or aged out: republishing swaps
        the entire slot, so a namespace the walk no longer sees is gone
        from the next reader's view. The stamp equality is what makes the
        payload and the slot the same observation rather than two.

        Proven able to fail: dropping the publish leaves the stale ``t1``
        snapshot in the slot, so the assertion that the slot now names the
        walked prefix reports the stale one instead. Restored, it passes.
        """
        from ..server import _routes_storage as _routes
        from ..server._state import survey_snapshot

        stale = "r" + "a" * 12 + "_"
        walked = "r" + "b" * 12 + "_"
        self._publish([_survey(stale)], computed_at="t1")

        payload = _routes._publish_and_shape_survey(
            [_survey(walked, status="live")], None, 200, None
        )

        assert payload["source"] == "fresh"
        assert payload["namespaces"][0]["prefix"] == walked
        snapshot = survey_snapshot()
        assert snapshot is not None
        assert snapshot.computed_at == payload["computed_at"]
        assert [s.prefix for s in snapshot.surveys] == [walked]

    def test_a_fresh_request_refuses_the_snapshot_it_would_otherwise_serve(
        self,
    ) -> None:
        """``fresh=true`` must walk the store even with a warm slot.

        ``None`` is the instruction to walk. The cold half of that rule moved
        to the fresh-interpreter test, where "nothing published" is a property
        of the process rather than a value this test wrote into the slot. What
        is left is the case that matters: a published snapshot is exactly what
        a caller passing ``fresh`` is trying to get past.

        Proven able to fail: dropping the ``fresh`` arm returns the warm
        snapshot's shaped payload, so the assertion that a fresh request
        yields no cached answer reports a dict instead of None. Restored,
        it passes.
        """
        from ..server import _routes_storage as _routes

        self._publish([_survey("r" + "d" * 12 + "_")], computed_at="t1")
        assert _routes._serve_survey_from_snapshot(None, 200, None, fresh=True) is None
        warm = _routes._serve_survey_from_snapshot(None, 200, None, fresh=False)
        assert warm is not None
        assert warm["source"] == "cache"


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
        from ..storage_survey_ops import debris_surveys

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
        from ..storage_survey_ops import debris_surveys

        assert debris_surveys(["a"], None) == []

    def test_backend_totals_roll_up_all_statuses(self) -> None:
        from ..storage_survey_ops import backend_totals

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
        from ..storage_survey_ops import prune_debris

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
        from ..storage_survey_ops import prune_debris

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
        from ..storage_survey_ops import prune_debris

        storage = tmp_path / "collections"
        storage.mkdir()
        result = prune_debris(
            cast("QdrantClient", _FakeClient([])), storage, dry_run=False
        )
        assert result.results == []
        assert result.reclaimed_bytes == 0


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
    exist on disk at that moment - so ``directory_size_bytes`` measures a real directory
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
        from ..storage_reconciliation import read_geometry

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
        from ..storage_reconciliation import read_geometry

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


class _CycleClient:
    """Qdrant stand-in exercising the maintenance cycle's destruction path.

    Real enough for the gates under test: it enumerates collections, counts
    points, writes an actual snapshot file where ``archive_prefix`` expects
    one, and records every delete. The two count-switching hooks model the
    races the gates exist to catch - ``counts_after_survey`` is a writer
    landing points between the survey and the drop, ``counts_after_snapshot``
    is one landing points during the archive, tearing it.
    """

    def __init__(
        self,
        counts: dict[str, int],
        *,
        snapshots_dir: Path | None = None,
        counts_after_survey: dict[str, int] | None = None,
        counts_after_snapshot: dict[str, int] | None = None,
        uncountable: bool = False,
    ) -> None:
        self._counts = dict(counts)
        self._snapshots_dir = snapshots_dir
        self._after_survey = counts_after_survey
        self._after_snapshot = counts_after_snapshot
        self._uncountable = uncountable
        self._survey_calls = len(counts)
        self._count_calls = 0
        self.deleted: list[str] = []
        self.snapshotted: list[str] = []

    def get_collections(self) -> object:
        return SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in sorted(self._counts)]
        )

    def count(self, *, collection_name: str) -> object:
        if self._uncountable:
            raise RuntimeError("collection count unavailable")
        value = self._counts[collection_name]
        self._count_calls += 1
        # The survey counts once per collection; anything after that is a
        # pre-drop re-count, which is where the switched values must land.
        if self._after_survey is not None and self._count_calls >= self._survey_calls:
            self._counts = dict(self._after_survey)
            self._after_survey = None
        return SimpleNamespace(count=value)

    def create_snapshot(self, *, collection_name: str, wait: bool = True) -> object:
        del wait
        assert self._snapshots_dir is not None, "snapshots_dir required to archive"
        self.snapshotted.append(collection_name)
        name = f"{collection_name}.snapshot"
        holder = self._snapshots_dir / collection_name
        holder.mkdir(parents=True, exist_ok=True)
        (holder / name).write_bytes(b"snapshot")
        if self._after_snapshot is not None:
            self._counts = dict(self._after_snapshot)
            self._after_snapshot = None
        return SimpleNamespace(name=name)

    def delete_collection(self, *, collection_name: str) -> None:
        self.deleted.append(collection_name)
        self._counts.pop(collection_name, None)


def _collection_of(prefix: str) -> str:
    """Return one canonically-named collection for *prefix*."""
    return prefix + VAULT_COLLECTION


def _orphaned_namespace(tmp_path: Path, *, now: datetime) -> str:
    """Record a root, remove it, and age its orphan clock past both windows.

    Uses the orphan tier rather than the ephemeral one so the pre-drop gates
    can be exercised without also depending on temp-rootedness.
    """
    root = tmp_path / "vanished-root"
    root.mkdir()
    entry = record_root(root, backend="server")
    root.rmdir()
    update_orphan_stamps(
        {entry.prefix: "orphaned"},
        now_iso=(now - timedelta(hours=1000)).isoformat(),
    )
    return entry.prefix


def _run_cycle(
    client: _CycleClient,
    tmp_path: Path,
    *,
    now: datetime = _NOW,
    active: frozenset[str] = frozenset(),
    policy: ReclaimPolicy | None = None,
):
    """Run one real maintenance cycle against *client*, reconcile disabled."""
    return run_maintenance_cycle(
        MaintenanceCycleRequest(
            client=cast("QdrantClient", client),
            now=now,
            policy=policy or ReclaimPolicy(reconcile=False),
            storage_dir=None,
            snapshots_dir=tmp_path / "snapshots",
            archive_dir=tmp_path / "archive",
            active_prefixes=lambda: active,
        )
    )


class TestPreDropRecount:
    """Both tiers re-count immediately before destroying anything.

    An archive makes loss recoverable, never prevented, so the data tier
    needs this check at least as much as the empty tier - and a snapshot torn
    by a concurrent write cannot even offer recovery of the delta it missed.
    """

    def test_data_tier_defers_when_points_moved_since_the_survey(
        self, tmp_path: Path
    ) -> None:
        prefix = _orphaned_namespace(tmp_path, now=_NOW)
        collection = _collection_of(prefix)
        client = _CycleClient(
            {collection: 10},
            snapshots_dir=tmp_path / "snapshots",
            counts_after_survey={collection: 25},
        )
        result = _run_cycle(client, tmp_path)
        decision = next(d for d in result.decisions if d.prefix == prefix)
        assert decision.action == "deferred"
        assert decision.reason == "points_changed_since_survey"
        # The gate must precede the archive, not merely the delete: a torn
        # snapshot of a live namespace is not a safety net.
        assert client.snapshotted == []
        assert client.deleted == []

    def test_data_tier_fails_when_the_completed_archive_is_torn(
        self, tmp_path: Path
    ) -> None:
        prefix = _orphaned_namespace(tmp_path, now=_NOW)
        collection = _collection_of(prefix)
        client = _CycleClient(
            {collection: 10},
            snapshots_dir=tmp_path / "snapshots",
            counts_after_snapshot={collection: 40},
        )
        result = _run_cycle(client, tmp_path)
        decision = next(d for d in result.decisions if d.prefix == prefix)
        assert decision.action == "failed"
        assert decision.reason is not None
        assert decision.reason.startswith("archive_failed:")
        assert client.snapshotted == [collection]
        assert client.deleted == []

    def test_uncountable_namespace_defers_rather_than_dropping(
        self, tmp_path: Path
    ) -> None:
        prefix = _orphaned_namespace(tmp_path, now=_NOW)
        collection = _collection_of(prefix)
        client = _CycleClient({collection: 10}, uncountable=True)
        result = _run_cycle(client, tmp_path)
        decision = next(d for d in result.decisions if d.prefix == prefix)
        assert decision.action == "deferred"
        assert decision.reason == "points_unverifiable"
        assert client.deleted == []

    def test_a_settled_data_namespace_is_still_archived_and_removed(
        self, tmp_path: Path
    ) -> None:
        """Positive control: the gates must not disable reclamation itself."""
        prefix = _orphaned_namespace(tmp_path, now=_NOW)
        collection = _collection_of(prefix)
        client = _CycleClient(
            {collection: 10},
            snapshots_dir=tmp_path / "snapshots",
        )
        result = _run_cycle(client, tmp_path)
        decision = next(d for d in result.decisions if d.prefix == prefix)
        assert decision.action == "archived_removed"
        assert client.snapshotted == [collection]
        assert client.deleted == [collection]


class TestLivenessGate:
    """An active index job's namespace is never destroyed under it."""

    def test_active_index_job_defers_before_the_archive(self, tmp_path: Path) -> None:
        prefix = _orphaned_namespace(tmp_path, now=_NOW)
        collection = _collection_of(prefix)
        client = _CycleClient(
            {collection: 10},
            snapshots_dir=tmp_path / "snapshots",
        )
        result = _run_cycle(client, tmp_path, active=frozenset({prefix}))
        decision = next(d for d in result.decisions if d.prefix == prefix)
        assert decision.action == "deferred"
        assert decision.reason == "active_index_job"
        assert client.snapshotted == []
        assert client.deleted == []

    def test_an_unrelated_active_job_does_not_shield_the_namespace(
        self, tmp_path: Path
    ) -> None:
        """The gate must key on the prefix, not on any job existing at all."""
        prefix = _orphaned_namespace(tmp_path, now=_NOW)
        collection = _collection_of(prefix)
        client = _CycleClient(
            {collection: 10},
            snapshots_dir=tmp_path / "snapshots",
        )
        result = _run_cycle(client, tmp_path, active=frozenset({"rffffffffffff_"}))
        decision = next(d for d in result.decisions if d.prefix == prefix)
        assert decision.action == "archived_removed"


class TestActiveIndexPrefixes:
    """The liveness probe reads the real job registry, not a parallel view."""

    def test_an_admitted_index_job_reports_its_namespace_prefix(
        self, tmp_path: Path
    ) -> None:
        from .. import jobs
        from ..job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec
        from ..storage_reclamation import _active_index_prefixes

        jobs.reset()
        try:
            root = tmp_path / "indexing-root"
            root.mkdir()
            assert _active_index_prefixes() == frozenset()
            outcome = jobs.get_job_manager().create(
                JobSpec(
                    operation=JobOperation.INDEX,
                    source=JobSource.DOCUMENT,
                    project_root=str(root),
                    mode=JobMode.INCREMENTAL,
                ),
                JobInitiator(
                    kind="cli",
                    command="reindex_documents",
                    project_root=str(root),
                ),
            )
            assert outcome.status is not JobOutcomeStatus.ERROR, outcome.message
            assert _active_index_prefixes() == frozenset({root_collection_prefix(root)})
        finally:
            jobs.reset()


class TestActivityClock:
    """The ephemeral idle clock advances on observation, not only on stamps."""

    def _record(self, tmp_path: Path, *, stale_hours: float) -> str:
        root = tmp_path / "harness-root"
        root.mkdir(exist_ok=True)
        entry = record_root(
            root,
            backend="server",
            last_indexed=(_NOW - timedelta(hours=stale_hours)).isoformat(),
        )
        return entry.prefix

    def test_a_moved_point_count_resets_the_clock(self, tmp_path: Path) -> None:
        prefix = self._record(tmp_path, stale_hours=1000)
        update_activity_stamps({prefix: ("live", 10)}, now_iso=_NOW.isoformat())
        later = (_NOW + timedelta(hours=1)).isoformat()
        stamps = update_activity_stamps({prefix: ("live", 11)}, now_iso=later)
        assert stamps[prefix] == later
        assert load_manifest()[prefix].last_indexed == later

    def test_a_settled_point_count_leaves_the_clock_alone(self, tmp_path: Path) -> None:
        """Without this the tier could never fire: every cycle would reset it."""
        prefix = self._record(tmp_path, stale_hours=1000)
        stale = load_manifest()[prefix].last_indexed
        update_activity_stamps({prefix: ("live", 10)}, now_iso=_NOW.isoformat())
        stamps = update_activity_stamps(
            {prefix: ("live", 10)},
            now_iso=(_NOW + timedelta(hours=1)).isoformat(),
        )
        assert stamps[prefix] == _NOW.isoformat()
        assert stamps[prefix] != stale

    def test_a_first_observation_resets_the_clock(self, tmp_path: Path) -> None:
        # One reading confirms nothing held still - there is no earlier
        # reading it could have agreed with - so it restarts the window.
        prefix = self._record(tmp_path, stale_hours=1000)
        stamps = update_activity_stamps(
            {prefix: ("live", 10)}, now_iso=_NOW.isoformat()
        )
        assert stamps[prefix] == _NOW.isoformat()
        assert load_manifest()[prefix].observed_points == 10

    def test_an_unverifiable_observation_resets_the_clock(self, tmp_path: Path) -> None:
        prefix = self._record(tmp_path, stale_hours=1000)
        update_activity_stamps({prefix: ("live", 10)}, now_iso=_NOW.isoformat())
        later = (_NOW + timedelta(hours=1)).isoformat()
        stamps = update_activity_stamps({prefix: ("unverifiable", 10)}, now_iso=later)
        assert stamps[prefix] == later

    def test_the_observed_count_persists_across_a_reload(self, tmp_path: Path) -> None:
        prefix = self._record(tmp_path, stale_hours=1000)
        update_activity_stamps({prefix: ("live", 7)}, now_iso=_NOW.isoformat())
        # A fresh load is what a restarted daemon sees; the clock must not
        # restart just because the process did.
        assert load_manifest()[prefix].observed_points == 7

    def test_an_unknown_prefix_is_ignored(self) -> None:
        assert (
            update_activity_stamps(
                {"rdeadbeef0000_": ("live", 5)}, now_iso=_NOW.isoformat()
            )
            == {}
        )


class TestEphemeralTierNeedsObservedStability:
    """A temp-rooted namespace survives until observations agree for a TTL."""

    def _live_temp_namespace(self, tmp_path: Path) -> str:
        root = tmp_path / "temp-harness-root"
        root.mkdir()
        assert is_temp_rooted(str(root)), (
            "this suite needs pytest's tmp_path to be OS-temp-rooted; "
            "the ephemeral tier only considers temp-rooted namespaces"
        )
        entry = record_root(
            root,
            backend="server",
            last_indexed=(_NOW - timedelta(hours=1000)).isoformat(),
        )
        return entry.prefix

    def test_a_stale_stamp_alone_no_longer_reclaims(self, tmp_path: Path) -> None:
        """The defect: a stale stamp plus points was enough to archive and drop.

        An indexer that writes without stamping leaves exactly this state, so
        the first cycle to see the namespace must restart the window rather
        than destroy it.
        """
        prefix = self._live_temp_namespace(tmp_path)
        collection = _collection_of(prefix)
        client = _CycleClient(
            {collection: 10},
            snapshots_dir=tmp_path / "snapshots",
        )
        result = _run_cycle(client, tmp_path)
        decision = next(d for d in result.decisions if d.prefix == prefix)
        assert decision.action == "pending"
        assert decision.reason is not None
        assert decision.reason.startswith("ephemeral_idle_remaining_h=")
        assert client.snapshotted == []
        assert client.deleted == []

    def test_the_tier_still_reclaims_once_observations_agree_for_a_ttl(
        self, tmp_path: Path
    ) -> None:
        """Positive control: the protection must not neuter the tier."""
        prefix = self._live_temp_namespace(tmp_path)
        collection = _collection_of(prefix)
        policy = ReclaimPolicy(reconcile=False, ephemeral_idle_hours=72.0)
        first = _CycleClient({collection: 10}, snapshots_dir=tmp_path / "snapshots")
        _run_cycle(first, tmp_path, now=_NOW, policy=policy)
        # A whole TTL later, with the count never having moved, the namespace
        # is genuinely idle and the tier acts.
        settled = _NOW + timedelta(hours=100)
        second = _CycleClient({collection: 10}, snapshots_dir=tmp_path / "snapshots")
        result = _run_cycle(second, tmp_path, now=settled, policy=policy)
        decision = next(d for d in result.decisions if d.prefix == prefix)
        assert decision.action == "archived_removed"
        assert second.deleted == [collection]

    def test_a_write_between_cycles_restarts_the_window(self, tmp_path: Path) -> None:
        prefix = self._live_temp_namespace(tmp_path)
        collection = _collection_of(prefix)
        policy = ReclaimPolicy(reconcile=False, ephemeral_idle_hours=72.0)
        first = _CycleClient({collection: 10}, snapshots_dir=tmp_path / "snapshots")
        _run_cycle(first, tmp_path, now=_NOW, policy=policy)
        # A TTL passes, but an unstamped indexer wrote in the meantime, so the
        # count disagrees with the last observation and the window restarts.
        settled = _NOW + timedelta(hours=100)
        second = _CycleClient({collection: 60}, snapshots_dir=tmp_path / "snapshots")
        result = _run_cycle(second, tmp_path, now=settled, policy=policy)
        decision = next(d for d in result.decisions if d.prefix == prefix)
        assert decision.action == "pending"
        assert decision.reason is not None
        assert decision.reason.startswith("ephemeral_idle_remaining_h=")
        assert second.deleted == []
