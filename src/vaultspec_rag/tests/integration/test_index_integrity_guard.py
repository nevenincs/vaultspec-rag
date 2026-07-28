"""The serve-time integrity guard against a real shrunken local store.

The one failure mode this guards is a collection that silently loses points
and keeps answering searches as though it were whole. These tests reproduce
the serve-time symptom honestly: a real local collection, a real manifest
written by the production publication writer, real deletions, and the same
count call the search path takes - then assert the guard degrades loudly
instead of staying quiet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..._index_breadth import code_meta_path
from ..._index_integrity import (
    VERDICT_CONSISTENT,
    VERDICT_SHRUNKEN,
    evaluate_index_integrity,
)
from ..._source_types import PublicSourceType

if TYPE_CHECKING:
    from pathlib import Path

    from ...store_runtime import VaultStore

pytestmark = [pytest.mark.integration]


def _seed_code_chunks(
    store: VaultStore,
    ids: tuple[str, ...],
    *,
    collection: str | None = None,
) -> None:
    """Upsert one real zero-vector chunk per id - no model involved."""
    from ..._store_models import CodeChunk
    from ...config._settings import get_config

    dimension = int(get_config().embedding_dimension)
    store.upsert_code_chunks(
        [
            CodeChunk(
                id=chunk_id,
                path=f"src/{chunk_id}.py",
                language="python",
                content=f"value_{chunk_id} = True",
                line_start=1,
                line_end=1,
                vector=[0.0] * dimension,
            )
            for chunk_id in ids
        ],
        write_policy=None,
        collection=collection,
    )


def _publish_breadth(root: Path, store: VaultStore, *, generation_id: str) -> None:
    """Publish the sidecar claim exactly as a finished run does: counted from
    the store immediately before the write, through the production writer."""
    from ...indexer._code_meta import publish_meta_from_file_states

    publish_meta_from_file_states(
        code_meta_path(root),
        [],
        generation_id=generation_id,
        membership_epoch="membership-epoch",
        content_epoch="content-epoch",
        published_points_count=store.count_code(),
    )


class TestServeTimeIntegrityGuard:
    def test_shrunken_collection_under_a_real_manifest_degrades_loudly(
        self, tmp_path: Path
    ) -> None:
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            _seed_code_chunks(store, ("c1", "c2", "c3", "c4", "c5"))
            assert store.count_code() == 5
            _publish_breadth(tmp_path, store, generation_id="generation-live")

            healthy = evaluate_index_integrity(
                tmp_path,
                PublicSourceType.CODE,
                store.count_code(),
                claim_ttl_seconds=0.0,
            )
            assert healthy.verdict == VERDICT_CONSISTENT

            # The shrink: real points deleted out from under a manifest that
            # still claims them - the shape a torn replacement leaves behind.
            store.delete_code_chunks(["c2", "c4"])
            live = store.count_code()
            assert live == 3

            verdict = evaluate_index_integrity(
                tmp_path, PublicSourceType.CODE, live, claim_ttl_seconds=0.0
            )
            # Catches the guard being neutered (comparison widened or removed):
            # with it broken this collection reads "consistent" and the search
            # keeps serving three-fifths of the corpus in silence.
            assert verdict.verdict == VERDICT_SHRUNKEN
            block = verdict.as_block()
            assert block["claimed_count"] == 5
            assert block["live_count"] == 3
            assert block["missing_count"] == 2
            assert block["generation_id"] == "generation-live"

            # The verdict reaches the response through the one canonical
            # envelope builder every entry point renders.
            from ..._search_state import BreadthFindings, search_index_state

            state = search_index_state(
                indexed_count=live,
                requested_root=tmp_path,
                search_type=PublicSourceType.CODE,
                findings=BreadthFindings(integrity=verdict),
            )
            # Catches the envelope wiring being dropped: a loud verdict that
            # never reaches the response degrades nothing.
            assert state["index_integrity"] == block
        finally:
            store.close()

    def test_guard_tracks_the_served_generation_collection(
        self, tmp_path: Path
    ) -> None:
        """A published generation shrinks; the guard sees it through the pointer.

        Reproduces the full publication flow: build into a generation-named
        collection beside the served one, record breadth, flip the served
        pointer, reopen the store the way a serving process would - then
        shrink the now-served generation and assert the verdict follows the
        collection the pointer names, not the derived base name.
        """
        from ..._store_models import (
            generation_code_collection,
            publish_generation_as_served,
        )
        from ...store_runtime import VaultStore

        store = VaultStore(tmp_path)
        try:
            derived = store.CODE_TABLE_NAME
            generation = generation_code_collection(derived, "a" * 32)
            store.ensure_code_table()
            store.ensure_code_table(generation)
            _seed_code_chunks(store, ("g1", "g2", "g3", "g4"), collection=generation)

            def _record_breadth() -> None:
                from ...indexer._code_meta import publish_meta_from_file_states

                publish_meta_from_file_states(
                    code_meta_path(tmp_path),
                    [],
                    generation_id="a" * 32,
                    membership_epoch="membership-epoch",
                    content_epoch="content-epoch",
                    published_points_count=store.count_code(generation),
                )

            publish_generation_as_served(
                tmp_path, collection=generation, record_breadth=_record_breadth
            )
        finally:
            store.close()

        serving = VaultStore(tmp_path)
        try:
            # The reopened store resolves reads through the served pointer.
            assert generation == serving.CODE_TABLE_NAME
            live = serving.count_code()
            assert live == 4
            healthy = evaluate_index_integrity(
                tmp_path, PublicSourceType.CODE, live, claim_ttl_seconds=0.0
            )
            assert healthy.verdict == VERDICT_CONSISTENT

            serving.delete_code_chunks(["g3"])
            shrunk_live = serving.count_code()
            assert shrunk_live == 3
            verdict = evaluate_index_integrity(
                tmp_path, PublicSourceType.CODE, shrunk_live, claim_ttl_seconds=0.0
            )
            # Catches the guard comparing against the wrong collection: only
            # the served generation lost a point, so a count taken anywhere
            # else keeps this verdict "consistent".
            assert verdict.verdict == VERDICT_SHRUNKEN
            assert verdict.as_block()["missing_count"] == 1
        finally:
            serving.close()
