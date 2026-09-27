"""Compatibility identity projections for publication proofs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import store_schema
from .._source_types import PublicSourceType
from ._publication_proof import ProofCompatibilityKey

if TYPE_CHECKING:
    import sqlite3

    from ._run_ledger_models import RunGeneration, RunSignature

from ._run_ledger_models import column_int, column_text


def stable_parameters(
    key: ProofCompatibilityKey,
) -> tuple[object, object, object, object]:
    return (
        key.source_type.value,
        key.root_identity,
        key.backend_identity,
        key.collection_identity,
    )


def compatibility_for_signature(signature: RunSignature) -> ProofCompatibilityKey:
    """Project one generation signature onto canonical proof identity."""
    return ProofCompatibilityKey(
        source_type=PublicSourceType(signature.source_type.value),
        root_identity=signature.root_identity,
        backend_identity=signature.backend_identity,
        collection_identity=signature.collection_identity,
        storage_schema=store_schema.STORAGE_SCHEMA_VERSION,
        payload_schema=signature.payload_schema,
        embedding_schema_identity=(
            f"{signature.model_identity}:{signature.dense_dimensions}:"
            f"{signature.embedding_schema}"
        ),
        chunking_schema_identity=signature.preprocessing_identity,
        membership_identity=signature.membership_epoch,
        content_identity=signature.content_epoch,
        policy_identity=signature.policy_fingerprint,
    )


def compatibility_for_generation(
    generation: RunGeneration,
) -> ProofCompatibilityKey:
    return compatibility_for_signature(generation.signature)


def publication_compatibility_from_row(row: sqlite3.Row) -> ProofCompatibilityKey:
    return ProofCompatibilityKey(
        source_type=PublicSourceType(column_text(row, "source_type")),
        root_identity=column_text(row, "root_identity"),
        backend_identity=column_text(row, "backend_identity"),
        collection_identity=column_text(row, "collection_identity"),
        storage_schema=column_int(row, "storage_schema"),
        payload_schema=column_int(row, "payload_schema"),
        embedding_schema_identity=column_text(row, "embedding_schema_identity"),
        chunking_schema_identity=column_text(row, "chunking_schema_identity"),
        membership_identity=column_text(row, "membership_identity"),
        content_identity=column_text(row, "content_identity"),
        policy_identity=column_text(row, "policy_identity"),
    )
