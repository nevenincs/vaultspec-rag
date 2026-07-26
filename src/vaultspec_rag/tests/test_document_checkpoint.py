"""Production slice-to-ledger checkpoint behavior for the document indexer.

The document checkpoint shares a base class with the code one, and most of
what it does is inherited and parameterised by a single content-kind
attribute. That attribute is the whole risk: set it wrong and the document
side silently records code-kind state. Before these tests existed the
document side had no direct unit coverage at all, so that mistake could only
surface in integration, far from its cause.

MUTATION PROOF, run in one uninterrupted sequence: flipping the document
checkpoint's content kind to the code kind fails
``test_record_processing_failure_records_the_document_content_kind`` and
``test_record_indexed_file_is_reachable_through_a_confirmed_slice`` on their
own kind assertions, and fails nothing else here. Restoring it returns all
nine to green. Re-run that mutation before loosening any assertion below.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from ..indexer._content_policy import (
    ContentKind,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._document_checkpoint import (
    DocumentRunCheckpoint,
    DocumentRunConfiguration,
)
from ..indexer._file_state import FileStateKind
from ..indexer._resolved_policy import resolve_index_policy
from ..indexer._run_ledger import (
    CommitUnit,
    FinalizationPhase,
    RunLedgerStateError,
    RunOperation,
    RunTerminalState,
)
from ..indexer._run_policy import RunPolicy

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _digest(value: str) -> str:
    return hashlib.blake2b(value.encode("utf-8")).hexdigest()


def _open(
    tmp_path: Path,
    *,
    configuration: DocumentRunConfiguration | None = None,
    operation: RunOperation = RunOperation.FULL,
) -> DocumentRunCheckpoint:
    policy = resolve_index_policy(
        tmp_path,
        content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1),
    )
    return DocumentRunCheckpoint.open(
        data_root=tmp_path / ".state",
        root_dir=tmp_path,
        policy=policy,
        run_policy=RunPolicy(no_progress_timeout_seconds=30.0),
        operation=operation,
        clean=False,
        model_identity="model-v1",
        dense_dimensions=8,
        configuration=configuration or _configuration(),
    )


def _configuration() -> DocumentRunConfiguration:
    return DocumentRunConfiguration(
        slice_max_chunks=2,
        source_bytes=1024,
        generated_chunks=2,
        weighted_bytes=1024,
        sparse_enabled=False,
        sparse_dimension=1,
        encode_batch_size=2,
    )


def _slice_unit(
    checkpoint: DocumentRunCheckpoint,
    rel_path: str,
    digest: str,
    *,
    point_ids: tuple[str, ...] = ("point-1",),
) -> CommitUnit:
    return checkpoint.unit_for(
        rel_path,
        digest,
        0,
        is_file_end=True,
        point_ids=point_ids,
    )


def test_generation_id_matches_the_open_generation(tmp_path: Path) -> None:
    checkpoint = _open(tmp_path)
    assert checkpoint.generation_id == checkpoint.generation.generation_id


def test_ingestion_complete_is_false_while_ingesting_and_true_once_reconciled(
    tmp_path: Path,
) -> None:
    checkpoint = _open(tmp_path)
    assert checkpoint.ingestion_complete is False

    checkpoint.generation = checkpoint.ledger.advance_finalization(
        checkpoint.generation_id,
        FinalizationPhase.STALE_RECONCILED,
    )
    assert checkpoint.ingestion_complete is True


def test_preserve_incomplete_generation_classifies_and_reraises(tmp_path: Path) -> None:
    checkpoint = _open(tmp_path)
    assert not checkpoint.generation.destructive_intent

    with (
        pytest.raises(RuntimeError, match="disk went away"),
        checkpoint.preserve_incomplete_generation(),
    ):
        raise RuntimeError("disk went away")

    # A non-destructive document run left published data intact, so it is
    # merely FAILED - REBUILD_INCOMPLETE would wrongly bar a later run from
    # resuming against a valid parent.
    assert checkpoint.generation.terminal_state is RunTerminalState.FAILED
    assert checkpoint.ledger.generation(checkpoint.generation_id).terminal_state is (
        RunTerminalState.FAILED
    )


def test_record_confirmed_deletion_is_idempotent_and_clears_the_indexed_state(
    tmp_path: Path,
) -> None:
    checkpoint = _open(tmp_path)
    digest = _digest("doc content")
    checkpoint.record_confirmed_slice(_slice_unit(checkpoint, "docs/a.md", digest))
    assert checkpoint.current_files() == {"docs/a.md": (digest, ("point-1",))}

    # The deletion evidence names points this path owned before this run, not
    # the points its own upsert unit just claimed.
    assert checkpoint.record_confirmed_deletion("docs/a.md", ("removed-1",)) is True
    assert checkpoint.record_confirmed_deletion("docs/a.md", ("removed-1",)) is False

    assert checkpoint.current_files() == {}


def test_record_confirmed_stale_deletion_keeps_the_path_indexed(
    tmp_path: Path,
) -> None:
    checkpoint = _open(tmp_path)
    digest = _digest("doc content")
    checkpoint.record_confirmed_slice(_slice_unit(checkpoint, "docs/b.md", digest))
    assert checkpoint.current_files() == {"docs/b.md": (digest, ("point-1",))}

    assert checkpoint.record_confirmed_stale_deletion("docs/b.md", ("stale-1",)) is True
    assert (
        checkpoint.record_confirmed_stale_deletion("docs/b.md", ("stale-1",)) is False
    )

    # Unlike a path deletion, a stale-points deletion leaves the path's
    # indexed convergence state untouched.
    assert checkpoint.current_files() == {"docs/b.md": (digest, ("point-1",))}


def test_record_processing_failure_records_the_document_content_kind(
    tmp_path: Path,
) -> None:
    checkpoint = _open(tmp_path)
    checkpoint.record_processing_failure(
        "docs/broken.md",
        FileStateKind.DECODE_FAILED,
        "could not decode as utf-8",
        content_hash=_digest("broken bytes"),
    )

    (state,) = list(checkpoint.ledger.iter_file_states(checkpoint.generation_id))
    assert state.state is FileStateKind.DECODE_FAILED
    assert state.kind is ContentKind.DOCUMENT
    assert state.detail == "could not decode as utf-8"


def test_record_indexed_file_is_reachable_through_a_confirmed_slice(
    tmp_path: Path,
) -> None:
    checkpoint = _open(tmp_path)
    digest = _digest("doc content")

    checkpoint.record_confirmed_slice(_slice_unit(checkpoint, "docs/d.md", digest))

    (state,) = list(checkpoint.ledger.iter_file_states(checkpoint.generation_id))
    assert state.rel_path == "docs/d.md"
    assert state.state is FileStateKind.INDEXED
    assert state.kind is ContentKind.DOCUMENT
    assert state.content_hash == digest


def test_publish_generation_certifies_and_compacts(tmp_path: Path) -> None:
    checkpoint = _open(tmp_path)
    digest = _digest("doc content")
    checkpoint.record_confirmed_slice(_slice_unit(checkpoint, "docs/c.md", digest))
    meta_path = tmp_path / ".state" / "document_meta.json"
    checkpoint.publish_metadata(meta_path)

    published = checkpoint.publish_generation()

    assert published.complete
    assert published.finalization_phase is FinalizationPhase.COMPACTED
    assert meta_path.exists()


def test_publish_generation_refuses_before_metadata_is_durable(tmp_path: Path) -> None:
    checkpoint = _open(tmp_path)

    with pytest.raises(
        RunLedgerStateError, match=r"metadata must be.*before generation publication"
    ):
        checkpoint.publish_generation()
