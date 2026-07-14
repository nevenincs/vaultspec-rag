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
