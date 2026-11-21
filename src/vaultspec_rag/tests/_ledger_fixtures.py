"""Run-ledger reads the tests need and production does not.

Production follows a generation it already holds and takes a publication
snapshot in one step. A test asserting on what a run left behind reads the
latest generation, or a bare read token, straight from the ledger file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..indexer._publication_proof import ProofMissingError, ProofReadToken
from ..indexer._run_ledger_models import (
    SourceResetPhase,
    column_int,
    fetch_one,
    ledger_connection,
)
from ..indexer._run_ledger_publication_storage import (
    has_open_receipt,
    proof_snapshot_row,
    require_exact_key,
)

if TYPE_CHECKING:
    from ..indexer._content_policy import ContentKind
    from ..indexer._publication_proof import ProofCompatibilityKey
    from ..indexer._run_ledger_models import RunGeneration
    from ..indexer._run_ledger_runtime import RunLedger
    from ..indexer._run_ledger_schema import GenerationRow


def latest_generation(
    ledger: RunLedger,
    source_type: ContentKind,
    *,
    collection_identity: str | None = None,
) -> RunGeneration | None:
    """Return the latest typed generation without loading its file rows."""
    parameters: tuple[object, ...] = (source_type.value,)
    collection_clause = ""
    if collection_identity is not None:
        collection_clause = " AND collection_identity = ?"
        parameters = (*parameters, collection_identity)
    with ledger_connection(ledger.path) as connection:
        row: GenerationRow | None = fetch_one(
            connection,
            f"""
            SELECT * FROM generations
            WHERE source_type = ?{collection_clause}
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            parameters,
        )
    return ledger._generation_from_row(row) if row is not None else None


def acquire_publication_read_token(
    ledger: RunLedger,
    key: ProofCompatibilityKey,
) -> ProofReadToken:
    """Acquire one proof revision, reporting whether a receipt is open."""
    with ledger_connection(ledger.path) as connection:
        row = proof_snapshot_row(connection, key)
    if row is None:
        raise ProofMissingError("publication proof does not exist")
    actual = require_exact_key(row, key, subject="publication proof")
    return ProofReadToken.from_snapshot(
        compatibility_key=actual,
        revision=column_int(row, "revision"),
        reservation_sequence=column_int(row, "reservation_sequence"),
        has_open_receipt=has_open_receipt(row),
    )


def record_reset_over_empty_storage(
    ledger: RunLedger, generation: RunGeneration
) -> None:
    """Record *generation*'s own completed reset before any storage exists.

    A full rebuild resumes only work written after its own reset. A test
    whose source holds no points yet, or that drives checkpoints without a
    store, has nothing to discard, so the reset is recorded in the ledger
    alone.
    """
    signature = generation.signature
    state = ledger.begin_source_reset(
        signature.source_type,
        signature.root_identity,
        signature.backend_identity,
        generation.generation_id,
    )
    for phase in (SourceResetPhase.DISCARDED, SourceResetPhase.COMPLETE):
        state = ledger.advance_source_reset(state, phase)
