"""Canonical receipt checkpoint for vault document publication."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from .. import store_schema
from .._source_types import PublicSourceType
from .._store_writes import workspace_volume_path
from ._checkpoint_common import RunCheckpointBase
from ._config_epoch import vault_content_epoch
from ._index_schema import VAULT_POINT_SCHEMA
from ._publication_proof import ProofEvidence
from ._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    RunAuthority,
    RunOperation,
    RunSignature,
    index_run_ledger_path,
)
from ._run_ledger_runtime import RunLedger
from ._run_policy import RunPolicy
from ._vault_fingerprint import SCHEME

if TYPE_CHECKING:
    import pathlib

    from .._store_models import VaultChunk
    from ..job_control import RunControl
    from ._content_policy import ContentKind
    from ._streaming_types import StoreMutationLifecycle

__all__ = ["VaultRunCheckpoint"]


@dataclass(slots=True)
class VaultRunCheckpoint(RunCheckpointBase):
    """One vault generation's durable storage and proof authority."""

    _content_kind: ClassVar[ContentKind | None] = None
    _kind_label: ClassVar[str] = "vault"

    @classmethod
    def open(
        cls,
        root: pathlib.Path,
        *,
        backend_identity: str,
        authority: RunAuthority,
        operation: RunOperation,
        run_control: RunControl,
    ) -> VaultRunCheckpoint:
        from ..config._settings import get_config

        cfg = get_config()
        model_identity = json.dumps(
            {
                "dense": str(cfg.embedding_model),
                "sparse": str(cfg.sparse_model) if cfg.sparse_enabled else None,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        content_identity = vault_content_epoch(
            vault_chunk_chars=int(cfg.vault_chunk_chars)
        )
        signature = RunSignature(
            root_identity=str(root.resolve()),
            collection_identity=store_schema.VAULT_COLLECTION,
            source_type=PublicSourceType.VAULT,
            operation=operation,
            clean=authority is RunAuthority.REBUILD,
            model_identity=model_identity,
            dense_dimensions=int(cfg.embedding_dimension),
            embedding_schema=VAULT_POINT_SCHEMA,
            payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
            content_epoch=content_identity,
            membership_epoch=SCHEME,
            preprocessing_identity=f"vault-chunks:{content_identity}",
            configuration_fingerprint=content_identity,
            policy_fingerprint=SCHEME,
            backend_identity=backend_identity,
        )
        ledger = RunLedger(index_run_ledger_path(workspace_volume_path(root.resolve())))
        generation = cls.start_compatible_generation(ledger, signature)
        receipt = cls.open_publication_receipt(ledger, generation, authority)
        return cls(
            ledger=ledger,
            generation=generation,
            policy=None,
            run_policy=RunPolicy.from_config(run_control=run_control),
            authority=authority,
            receipt=receipt,
        )

    @staticmethod
    def units_for_chunks(
        chunks: list[VaultChunk],
        content_identities: dict[str, str],
    ) -> tuple[CommitUnit, ...]:
        return tuple(
            CommitUnit(
                rel_path=chunk.doc_id,
                kind=CommitUnitKind.UPSERT,
                source_digest=content_identities[chunk.doc_id],
                segment_ordinal=chunk.ordinal,
                is_file_end=chunk.ordinal == chunk.chunk_count - 1,
                point_ids=(chunk.point_key,),
            )
            for chunk in chunks
        )

    def chunk_lifecycle(
        self,
        chunks: list[VaultChunk],
        content_identities: dict[str, str],
    ) -> StoreMutationLifecycle | None:
        return self.mutation_lifecycle_for_units(
            self.units_for_chunks(chunks, content_identities)
        )

    def record_confirmed_chunks(
        self,
        chunks: list[VaultChunk],
        content_identities: dict[str, str],
    ) -> None:
        units = self.units_for_chunks(chunks, content_identities)
        self.ledger.record_storage_confirmed_units(self.generation_id, units)

    def _verified_evidence(self) -> list[ProofEvidence]:
        """Build full vault proof evidence from confirmed chunk units."""
        evidence: list[ProofEvidence] = []
        current_path: str | None = None
        current_digest: str | None = None
        point_ids: list[str] = []
        for unit in self.ledger.iter_units(self.generation_id):
            if unit.kind is not CommitUnitKind.UPSERT:
                continue
            if current_path is not None and unit.rel_path != current_path:
                assert current_digest is not None
                evidence.append(
                    ProofEvidence(current_path, current_digest, tuple(point_ids))
                )
                point_ids = []
                current_digest = None
            current_path = unit.rel_path
            if current_digest is not None and unit.source_digest != current_digest:
                raise RuntimeError(f"vault chunks disagree for {unit.rel_path!r}")
            current_digest = unit.source_digest
            point_ids.extend(unit.point_ids)
        if current_path is not None:
            assert current_digest is not None
            evidence.append(
                ProofEvidence(current_path, current_digest, tuple(point_ids))
            )
        return evidence
