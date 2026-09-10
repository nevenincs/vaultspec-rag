"""Read the sole committed publication authority without touching storage."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from . import store_schema
from ._source_types import PublicSourceType
from ._store_writes import workspace_volume_path
from .indexer._publication_proof import ProofIncompatibleError
from .indexer._run_ledger_models import index_run_ledger_path
from .indexer._run_ledger_runtime import RunLedger
from .store_runtime import configured_backend_identity

if TYPE_CHECKING:
    import pathlib

    from .indexer._publication_proof import ProofEvidence, ProofReadToken
    from .indexer._run_ledger_models import PublicationProof

__all__ = [
    "PublicationSnapshot",
    "acquire_publication_snapshot",
    "clear_publication_state",
    "read_all_publication_evidence",
]


class PublicationSnapshot(NamedTuple):
    """One committed proof and the token fencing a related backend read."""

    proof: PublicationProof
    ledger: RunLedger
    token: ProofReadToken

    def validate(self) -> None:
        """Reject a backend read concurrent with publication."""
        self.ledger.validate_publication_read_token(self.token)


def _collection(source: PublicSourceType) -> str:
    if source is PublicSourceType.CODE:
        return store_schema.CODE_COLLECTION
    if source is PublicSourceType.VAULT:
        return store_schema.VAULT_COLLECTION
    if source is PublicSourceType.DOCUMENT:
        return store_schema.DOCUMENT_COLLECTION
    raise ValueError("publication snapshots require one concrete source")


def acquire_publication_snapshot(
    root: pathlib.Path,
    source: PublicSourceType,
) -> PublicationSnapshot:
    """Acquire and validate the current proof for one storage projection."""
    resolved = root.resolve()
    ledger_path = index_run_ledger_path(workspace_volume_path(resolved))
    if not ledger_path.is_file():
        from .indexer._publication_proof import ProofMissingError

        raise ProofMissingError(
            "publication proof does not exist; an explicit rebuild is required"
        )
    ledger = RunLedger(ledger_path)
    proof, token = ledger.acquire_current_publication_snapshot(
        source_type=source,
        root_identity=str(resolved),
        backend_identity=configured_backend_identity(resolved),
    )
    key = proof.compatibility_key
    if (
        key.collection_identity != _collection(source)
        or key.storage_schema != store_schema.STORAGE_SCHEMA_VERSION
        or key.payload_schema != store_schema.STORAGE_SCHEMA_VERSION
    ):
        raise ProofIncompatibleError(
            "canonical publication proof does not match the current storage projection"
        )
    return PublicationSnapshot(proof=proof, ledger=ledger, token=token)


def read_all_publication_evidence(
    snapshot: PublicationSnapshot,
) -> dict[str, ProofEvidence]:
    """Read a complete canonical proof through bounded keyset pages."""
    evidence: dict[str, ProofEvidence] = {}
    after_path: str | None = None
    while True:
        page = snapshot.ledger.publication_evidence_page(
            snapshot.proof.compatibility_key,
            after_path=after_path,
        )
        if not page:
            return evidence
        evidence.update(page)
        after_path = next(reversed(page))


def clear_publication_state(
    root: pathlib.Path,
    source: PublicSourceType,
    backend_identity: str,
) -> None:
    """Remove canonical authority for one source before storage deletion."""
    resolved = root.resolve()
    ledger_path = index_run_ledger_path(workspace_volume_path(resolved))
    if not ledger_path.is_file():
        return
    RunLedger(ledger_path).clear_publication_source(
        source,
        str(resolved),
        backend_identity,
    )
