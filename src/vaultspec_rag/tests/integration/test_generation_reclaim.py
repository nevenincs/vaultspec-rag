"""Reclaiming superseded code generations against real Qdrant storage.

Every collection here is a real local Qdrant collection: created, listed and
dropped through the client the maintenance path uses. Nothing stands in for the
storage, because the question under test is what actually survives a drop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from qdrant_client import QdrantClient, models

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]

_DERIVED = "codebase_docs"
_NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
_LONG_AGO = "2026-07-01T00:00:00+00:00"


def _client(tmp_path: Path, *names: str) -> QdrantClient:
    """Return a real local client holding one real collection per name."""
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    for name in names:
        client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE),
        )
    return client


def _live(client: QdrantClient) -> set[str]:
    return {c.name for c in client.get_collections().collections}


class TestGenerationReclaimAgainstRealStorage:
    """The served collection survives every path; only earned drops happen."""

    def test_an_earned_window_drops_only_the_superseded_generation(
        self, tmp_path: Path
    ) -> None:
        """The one path that removes anything, and it must spare the served one.

        Proven able to fail: dropping the ``decision.droppable`` check and
        deleting every unreferenced candidate removes the collection under an
        unexpired window too, failing the pending assertion in the sibling test.
        """
        from ..._store_models import publish_served_code_collection
        from ...storage_ops import reclaim_superseded_generations

        served = f"{_DERIVED}_gnew"
        superseded = f"{_DERIVED}_gold"
        client = _client(tmp_path, served, superseded)
        publish_served_code_collection(tmp_path, served)
        try:
            results, stamps = reclaim_superseded_generations(
                client,
                roots={str(tmp_path): _DERIVED},
                stamps={superseded: _LONG_AGO},
                now=_NOW,
                grace_hours=24.0,
                reader_present=lambda _root: False,
                dry_run=False,
            )
            live = _live(client)
        finally:
            client.close()

        assert superseded not in live
        assert served in live
        assert [r.status for r in results] == ["removed"]
        # The dropped collection's clock is gone with it.
        assert superseded not in stamps

    def test_a_live_reader_lease_spares_the_generation(self, tmp_path: Path) -> None:
        """A reader in this process may still be resolving the old name.

        Proven able to fail: passing ``reader_present=lambda _r: False`` here
        drops the collection and fails the survival assertion.
        """
        from ..._store_models import publish_served_code_collection
        from ...storage_ops import reclaim_superseded_generations

        served = f"{_DERIVED}_gnew"
        superseded = f"{_DERIVED}_gold"
        client = _client(tmp_path, served, superseded)
        publish_served_code_collection(tmp_path, served)
        try:
            _results, stamps = reclaim_superseded_generations(
                client,
                roots={str(tmp_path): _DERIVED},
                stamps={superseded: _LONG_AGO},
                now=_NOW,
                grace_hours=24.0,
                reader_present=lambda _root: True,
                dry_run=False,
            )
            live = _live(client)
        finally:
            client.close()

        assert superseded in live
        # The clock restarted rather than being preserved: a held observation
        # means the window was not continuous, so the elapsed stamp must not
        # survive to license a drop on the very next cycle.
        assert stamps[superseded] == _NOW.isoformat()

    def test_an_unreadable_pointer_spares_every_generation_of_that_root(
        self, tmp_path: Path
    ) -> None:
        """An illegible pointer is not evidence that nothing points anywhere.

        Proven able to fail: reporting unreadable-pointer roots from
        ``survey_generations`` instead of omitting them lets this collection
        reach the gate and be dropped.
        """
        from ..._store_models import served_code_pointer_path
        from ...storage_ops import reclaim_superseded_generations

        superseded = f"{_DERIVED}_gold"
        client = _client(tmp_path, _DERIVED, superseded)
        path = served_code_pointer_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        try:
            _results, stamps = reclaim_superseded_generations(
                client,
                roots={str(tmp_path): _DERIVED},
                stamps={superseded: _LONG_AGO},
                now=_NOW,
                grace_hours=24.0,
                reader_present=lambda _root: False,
                dry_run=False,
            )
            live = _live(client)
        finally:
            client.close()

        assert superseded in live
        assert _DERIVED in live
        # Cleared outright rather than reset to now: this root was never
        # observed as unreferenced at all, because its pointer could not be
        # read. A held-and-observed collection gets a fresh stamp; one that was
        # never legibly observed gets none, and starts over when it is.
        assert superseded not in stamps

    def test_a_dry_run_removes_nothing(self, tmp_path: Path) -> None:
        """Planning must not mutate storage."""
        from ..._store_models import publish_served_code_collection
        from ...storage_ops import reclaim_superseded_generations

        served = f"{_DERIVED}_gnew"
        superseded = f"{_DERIVED}_gold"
        client = _client(tmp_path, served, superseded)
        publish_served_code_collection(tmp_path, served)
        try:
            results, _stamps = reclaim_superseded_generations(
                client,
                roots={str(tmp_path): _DERIVED},
                stamps={superseded: _LONG_AGO},
                now=_NOW,
                grace_hours=24.0,
                reader_present=lambda _root: False,
                dry_run=True,
            )
            live = _live(client)
        finally:
            client.close()

        assert superseded in live
        assert [r.status for r in results] == ["would_remove"]


class TestTheCycleRunsTheGenerationPass:
    """The scheduled cycle must actually reach the generation reclaim."""

    def test_a_cycle_plans_the_drop_of_a_superseded_generation(
        self, tmp_path: Path, isolated_status_dir: Path
    ) -> None:
        """Binding the wiring, not the gates - those are proven above.

        Without this the pass could be implemented, gated, tested in isolation
        and never invoked, which is precisely how two earlier steps on this
        plan came to be marked done while nothing called them.

        The root is recorded in the manifest so the survey attributes it, and
        the pointer is published so the generation is genuinely superseded. A
        weaker assertion - that ``generations`` is a list - passes with the
        call removed, because the field defaults to empty; that version was
        written, shown worthless by mutation, and replaced with this.

        The status dir is relocated through the shared fixture rather than a
        bare environment set: the manifest and the grace stamps both resolve
        through it, and a raw set leaks into whichever test runs next.

        Proven able to fail: removing the ``_reclaim_generations_for_cycle``
        call from ``run_maintenance_cycle`` leaves ``generations`` empty and
        fails the assertion below.
        """
        from ..._store_models import publish_served_code_collection
        from ...storage_manifest import record_root
        from ...storage_ops import ReclaimPolicy, run_maintenance_cycle

        _ = isolated_status_dir
        entry = record_root(tmp_path, backend="local")
        served = f"{entry.prefix}{_DERIVED}_gnew"
        superseded = f"{entry.prefix}{_DERIVED}_gold"
        client = _client(tmp_path, served, superseded)
        publish_served_code_collection(tmp_path, served)
        try:
            result = run_maintenance_cycle(
                client,
                now=_NOW,
                policy=ReclaimPolicy(),
                storage_dir=None,
                snapshots_dir=tmp_path / "snapshots",
                archive_dir=tmp_path / "archive",
                dry_run=True,
            )
            live = _live(client)
        finally:
            client.close()

        named = {r.prefix for r in result.generations}
        assert superseded in named
        assert served not in named
        # Dry run: the cycle planned and mutated nothing.
        assert superseded in live
