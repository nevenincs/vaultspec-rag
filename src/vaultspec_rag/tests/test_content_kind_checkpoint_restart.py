"""CPU-only real-ledger restart parity across code and document checkpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .integration._helpers import _document_policy

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("clean", [False, True])
def test_each_kind_replays_only_its_final_unconfirmed_unit(
    tmp_path: Path, clean: bool
) -> None:
    """Independent production checkpoints retain every confirmed kind-local unit."""
    import hashlib

    from .._store_models import CodeChunk
    from ..indexer._document_checkpoint import (
        DocumentRunCheckpoint,
        DocumentRunConfiguration,
        DocumentRunOpenRequest,
    )
    from ..indexer._resolved_policy import (
        IndexPolicyResolutionOptions,
        resolve_index_policy,
    )
    from ..indexer._run_checkpoint import (
        CodeRunCheckpoint,
        CodeRunConfiguration,
        CodeRunOpenRequest,
    )
    from ..indexer._run_ledger_models import (
        RunAuthority,
        RunOperation,
        RunTerminalState,
    )
    from ..indexer._run_policy import RunPolicy
    from ..indexer._streaming_types import CodeFileSegment

    policy = resolve_index_policy(
        tmp_path,
        IndexPolicyResolutionOptions(content_policy=_document_policy("guide.txt")),
    )
    run_policy = RunPolicy(no_progress_timeout_seconds=30.0)
    data_root = tmp_path / ".state"
    code_configuration = CodeRunConfiguration(
        segment_max_chunks=1,
        segment_max_bytes=4096,
        queue_max_chunks=2,
        queue_max_bytes=8192,
        slice_max_chunks=2,
        slice_max_bytes=8192,
        sparse_enabled=False,
        sparse_dimension=1,
        encode_batch_size=2,
        flush_slices=2,
    )
    document_configuration = DocumentRunConfiguration(
        slice_max_chunks=1,
        source_bytes=4096,
        generated_chunks=3,
        weighted_bytes=8192,
        sparse_enabled=False,
        sparse_dimension=1,
        encode_batch_size=2,
    )

    def _open_code() -> CodeRunCheckpoint:
        return CodeRunCheckpoint.open_generation(
            CodeRunOpenRequest(
                data_root=data_root,
                root_dir=tmp_path,
                policy=policy,
                run_policy=run_policy,
                operation=RunOperation.FULL,
                authority=RunAuthority.REBUILD,
                clean=clean,
                model_identity="restart-model-v1",
                backend_identity="test-backend:content-kind-restart",
                dense_dimensions=4,
                configuration=code_configuration,
            )
        )

    def _open_document() -> DocumentRunCheckpoint:
        return DocumentRunCheckpoint.open_generation(
            DocumentRunOpenRequest(
                data_root=data_root,
                root_dir=tmp_path,
                policy=policy,
                run_policy=run_policy,
                operation=RunOperation.FULL,
                authority=RunAuthority.REBUILD,
                clean=clean,
                model_identity="restart-model-v1",
                backend_identity="test-backend:content-kind-restart",
                dense_dimensions=4,
                configuration=document_configuration,
            )
        )

    code_digest = hashlib.blake2b(b"code restart input").hexdigest()
    code_segments = tuple(
        CodeFileSegment(
            "module.py",
            ordinal,
            (
                CodeChunk(
                    id=f"code-{ordinal}",
                    path="module.py",
                    language="python",
                    content=f"def unit_{ordinal}():\n    return {ordinal}\n",
                    line_start=ordinal * 2 + 1,
                    line_end=ordinal * 2 + 2,
                ),
            ),
            256,
            ordinal == 2,
        )
        for ordinal in range(3)
    )
    document_digest = hashlib.blake2b(b"document restart input").hexdigest()

    code = _open_code()
    document = _open_document()
    for segment in code_segments[:2]:
        assert (
            code.record_confirmed_segments((segment,), {segment.path: code_digest}) == 1
        )
    document_units = tuple(
        document.unit_for(
            "guide.txt",
            document_digest,
            ordinal,
            is_file_end=ordinal == 2,
            point_ids=(f"document-{ordinal}",),
        )
        for ordinal in range(3)
    )
    for unit in document_units[:2]:
        assert document.record_confirmed_slice(unit)
    code.ledger.finish_generation(
        code.generation_id,
        RunTerminalState.CANCELLED,
        detail="interrupted before final code segment",
    )
    document.ledger.finish_generation(
        document.generation_id,
        RunTerminalState.CANCELLED,
        detail="interrupted before final document slice",
    )

    resumed_code = _open_code()
    resumed_document = _open_document()
    assert resumed_code.generation_id == code.generation_id
    assert resumed_document.generation_id == document.generation_id
    assert tuple(
        segment
        for segment in code_segments
        if not resumed_code.segment_committed(segment, code_digest)
    ) == (code_segments[-1],)
    assert [resumed_document.slice_committed(unit) for unit in document_units] == [
        True,
        True,
        False,
    ]
    assert (
        resumed_code.record_confirmed_segments(
            (code_segments[-1],), {code_segments[-1].path: code_digest}
        )
        == 1
    )
    assert resumed_document.record_confirmed_slice(document_units[-1])
    assert all(
        resumed_code.segment_committed(segment, code_digest)
        for segment in code_segments
    )
    assert all(resumed_document.slice_committed(unit) for unit in document_units)


def test_vault_rebuild_keeps_its_confirmed_generation_after_interruption(
    tmp_path: Path,
) -> None:
    """Retained clean authority reopens the real ledger without discarding units."""
    from ..indexer._run_ledger_models import (
        CommitUnit,
        CommitUnitKind,
        RunAuthority,
        RunOperation,
        RunTerminalState,
    )
    from ..indexer._vault_checkpoint import VaultRunCheckpoint
    from ..job_control import NO_RUN_CONTROL

    def _open() -> VaultRunCheckpoint:
        return VaultRunCheckpoint.open(
            tmp_path,
            backend_identity="test-backend:vault-rebuild-restart",
            authority=RunAuthority.REBUILD,
            operation=RunOperation.FULL,
            run_control=NO_RUN_CONTROL,
        )

    checkpoint = _open()
    confirmed = CommitUnit(
        rel_path="notes",
        kind=CommitUnitKind.UPSERT,
        source_digest="3" * 128,
        segment_ordinal=0,
        is_file_end=False,
        point_ids=("notes#c0",),
    )
    checkpoint.ledger.record_storage_confirmed_unit(checkpoint.generation_id, confirmed)
    checkpoint.ledger.finish_generation(
        checkpoint.generation_id,
        RunTerminalState.CANCELLED,
        detail="paused after the first durable vault unit",
    )
    resumed = _open()
    assert resumed.generation_id == checkpoint.generation_id
    assert resumed.generation.signature.clean
    assert resumed.ledger.committed_unit_count(resumed.generation_id) == 1
    assert resumed.ledger.unit_committed(resumed.generation_id, confirmed)
    assert not resumed.ledger.file_complete(resumed.generation_id, confirmed.rel_path)
