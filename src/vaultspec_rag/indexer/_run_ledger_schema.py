"""The run ledger's on-disk shape: typed row columns and the schema contract.

The row types name the columns each query reads, and the schema constants
declare the tables, columns and indexes a ledger must hold for this build to
trust it.
"""

from __future__ import annotations

from typing import Final, TypedDict

__all__ = [
    "ADDITIVE_UPGRADE_FROM_VERSION",
    "ADDITIVE_UPGRADE_TABLES",
    "PUBLICATION_PROOF_SCHEMA",
    "REQUIRED_INDEXES",
    "REQUIRED_INDEX_PREDICATES",
    "REQUIRED_SCHEMA",
    "SCHEMA_VERSION",
    "SOURCE_RESET_SCHEMA",
    "FileStateTombstoneRow",
    "GenerationRow",
    "PublicationEvidenceRow",
    "PublicationMutationPointRow",
    "PublicationMutationUnitRow",
    "PublicationPointRow",
    "PublicationProofRow",
    "PublicationReceiptDeltaRow",
    "PublicationReceiptPointRow",
    "PublicationReceiptRow",
    "SourceResetRow",
]


class GenerationRow(TypedDict):
    """The ``generations`` row columns :func:`RunLedger._generation_from_row` reads.

    Shared across the ledger's runtime and its mixins: every one of them reads
    or forwards a ``generations`` row and types it against this one shape
    rather than the untyped ``sqlite3.Row`` the cursor actually returns.
    """

    generation_id: str
    source_type: str
    collection_identity: str
    signature_fingerprint: str
    signature_json: str
    finalization_phase: str
    terminal_state: str
    destructive_intent: int
    created_at: float
    updated_at: float
    terminal_detail: str | None
    parent_generation_id: str | None
    consecutive_failures: int


class PublicationProofRow(TypedDict):
    """Flattened durable header for one current publication proof."""

    source_type: str
    root_identity: str
    backend_identity: str
    collection_identity: str
    storage_schema: int
    payload_schema: int
    embedding_schema_identity: str
    chunking_schema_identity: str
    membership_identity: str
    content_identity: str
    policy_identity: str
    generation_id: str
    revision: int
    reservation_sequence: int
    indexed_identities: int
    retained_points: int
    provenance: str
    committed_at: float
    verified_at: float | None


class PublicationEvidenceRow(TypedDict):
    """One normalized path evidence row in the current proof."""

    source_type: str
    root_identity: str
    backend_identity: str
    collection_identity: str
    rel_path: str
    content_identity: str
    evidence_generation_id: str


class PublicationPointRow(TypedDict):
    """One retained point identity belonging to normalized path evidence."""

    source_type: str
    root_identity: str
    backend_identity: str
    collection_identity: str
    rel_path: str
    point_ordinal: int
    point_id: str


class PublicationReceiptRow(TypedDict):
    """Durable state-machine header for one publication attempt."""

    receipt_id: str
    reservation_sequence: int
    source_type: str
    root_identity: str
    backend_identity: str
    collection_identity: str
    storage_schema: int
    payload_schema: int
    embedding_schema_identity: str
    chunking_schema_identity: str
    membership_identity: str
    content_identity: str
    policy_identity: str
    generation_id: str
    parent_revision: int
    target_revision: int
    next_mutation_ordinal: int
    state: str
    reserved_at: float
    sealed_at: float | None
    rollback_started_at: float | None
    committed_at: float | None
    rolled_back_at: float | None


class PublicationMutationUnitRow(TypedDict):
    """One receipt-bound deterministic storage mutation and its durable state."""

    receipt_id: str
    mutation_ordinal: int
    sealed_ordinal: int | None
    unit_id: str
    rel_path: str
    unit_kind: str
    source_digest: str | None
    segment_ordinal: int
    is_file_end: int
    state: str
    prepared_at: float
    applied_at: float | None
    confirmed_at: float | None


class PublicationMutationPointRow(TypedDict):
    """One exact point identity carried by a receipt mutation unit."""

    receipt_id: str
    mutation_ordinal: int
    point_ordinal: int
    point_id: str


class PublicationReceiptDeltaRow(TypedDict):
    """Deterministically ordered path transition retained for receipt replay."""

    receipt_id: str
    delta_ordinal: int
    outcome: str
    rel_path: str
    target_rel_path: str | None
    old_content_identity: str | None
    new_content_identity: str | None


class PublicationReceiptPointRow(TypedDict):
    """Exact old or new retained point membership for one receipt delta."""

    receipt_id: str
    delta_ordinal: int
    evidence_side: str
    point_ordinal: int
    point_id: str


class FileStateTombstoneRow(TypedDict):
    """One generation-local deletion that shadows inherited file state."""

    generation_id: str
    rel_path: str


class SourceResetRow(TypedDict):
    """The latest reset of one root, backend, and source, and how far it got."""

    source_type: str
    root_identity: str
    backend_identity: str
    epoch: int
    generation_id: str
    phase: str
    updated_at: float


SCHEMA_VERSION: Final = 10

#: The one prior format this build upgrades in place rather than refusing. It
#: differs from the current format only by tables added since, so creating
#: them leaves every existing generation, receipt, and proof exactly as valid
#: as it was: a root keeps serving and updating incrementally across the
#: upgrade instead of paying a full re-embed to gain an empty table.
ADDITIVE_UPGRADE_FROM_VERSION: Final = 9

_BASE_LEDGER_SCHEMA: Final = {
    "generations": frozenset(
        {
            "generation_id",
            "source_type",
            "collection_identity",
            "signature_fingerprint",
            "signature_json",
            "finalization_phase",
            "terminal_state",
            "destructive_intent",
            "created_at",
            "updated_at",
            "terminal_detail",
            "parent_generation_id",
            "consecutive_failures",
        }
    ),
    "commit_units": frozenset(
        {
            "generation_id",
            "unit_id",
            "rel_path",
            "unit_kind",
            "source_digest",
            "segment_ordinal",
            "is_file_end",
            "point_ids_json",
            "committed_at",
        }
    ),
    "commit_point_ids": frozenset(
        {"generation_id", "unit_id", "point_ordinal", "point_id"}
    ),
    "file_states": frozenset(
        {
            "generation_id",
            "rel_path",
            "state",
            "content_kind",
            "content_hash",
            "admission_reason",
            "error_kind",
            "detail",
            "evidence_generation_id",
        }
    ),
}

PUBLICATION_PROOF_SCHEMA: Final = {
    "publication_proofs": frozenset(PublicationProofRow.__annotations__),
    "publication_evidence": frozenset(PublicationEvidenceRow.__annotations__),
    "publication_points": frozenset(PublicationPointRow.__annotations__),
    "publication_receipts": frozenset(PublicationReceiptRow.__annotations__),
    "publication_mutation_units": frozenset(PublicationMutationUnitRow.__annotations__),
    "publication_mutation_points": frozenset(
        PublicationMutationPointRow.__annotations__
    ),
    "publication_receipt_deltas": frozenset(PublicationReceiptDeltaRow.__annotations__),
    "publication_receipt_points": frozenset(PublicationReceiptPointRow.__annotations__),
    "file_state_tombstones": frozenset(FileStateTombstoneRow.__annotations__),
}

SOURCE_RESET_SCHEMA: Final = {
    "source_resets": frozenset(SourceResetRow.__annotations__),
}

#: Tables the additive upgrade creates. A ledger at the prior format must hold
#: every other current table exactly and none of these.
ADDITIVE_UPGRADE_TABLES: Final = frozenset(SOURCE_RESET_SCHEMA)

REQUIRED_SCHEMA: Final = {
    **_BASE_LEDGER_SCHEMA,
    **PUBLICATION_PROOF_SCHEMA,
    **SOURCE_RESET_SCHEMA,
}

# Named indexes are part of the durable schema contract, not optional tuning.
# Each tuple is ``(table, ordered columns, unique, partial)`` and is verified on
# every open of the exact current format.
REQUIRED_INDEXES: Final[dict[str, tuple[str, tuple[str, ...], bool, bool]]] = {
    "generations_active": (
        "generations",
        ("source_type", "terminal_state", "created_at"),
        False,
        False,
    ),
    "commit_units_path": (
        "commit_units",
        ("generation_id", "rel_path", "segment_ordinal"),
        False,
        False,
    ),
    "commit_point_ids_point": (
        "commit_point_ids",
        ("point_id",),
        False,
        False,
    ),
    "file_states_state": (
        "file_states",
        ("generation_id", "state", "rel_path"),
        False,
        False,
    ),
    "publication_proofs_generation": (
        "publication_proofs",
        ("generation_id",),
        False,
        False,
    ),
    "publication_evidence_generation": (
        "publication_evidence",
        ("evidence_generation_id",),
        False,
        False,
    ),
    "publication_points_point": (
        "publication_points",
        ("point_id",),
        False,
        False,
    ),
    "publication_receipts_generation": (
        "publication_receipts",
        ("generation_id", "state"),
        False,
        False,
    ),
    "publication_receipts_open": (
        "publication_receipts",
        (
            "source_type",
            "root_identity",
            "backend_identity",
            "collection_identity",
        ),
        True,
        True,
    ),
    "publication_mutation_units_state": (
        "publication_mutation_units",
        ("receipt_id", "state", "mutation_ordinal"),
        False,
        False,
    ),
    "publication_mutation_units_sealed": (
        "publication_mutation_units",
        ("receipt_id", "sealed_ordinal"),
        True,
        True,
    ),
    "publication_mutation_points_point": (
        "publication_mutation_points",
        ("point_id",),
        False,
        False,
    ),
    "publication_receipt_deltas_path": (
        "publication_receipt_deltas",
        ("receipt_id", "rel_path"),
        True,
        False,
    ),
    "publication_receipt_deltas_target": (
        "publication_receipt_deltas",
        ("receipt_id", "target_rel_path"),
        False,
        False,
    ),
    "publication_receipt_points_point": (
        "publication_receipt_points",
        ("point_id",),
        False,
        False,
    ),
    "file_state_tombstones_path": (
        "file_state_tombstones",
        ("rel_path", "generation_id"),
        False,
        False,
    ),
}

REQUIRED_INDEX_PREDICATES: Final = {
    "publication_receipts_open": (
        "where state in ('reserved', 'sealed', 'rolling_back')"
    ),
    "publication_mutation_units_sealed": "where sealed_ordinal is not null",
}
