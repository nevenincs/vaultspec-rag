"""Exact vault audits validate the stored schema and canonical proof identities."""

from __future__ import annotations

import hashlib
from contextlib import nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, NotRequired, Required, TypedDict

import pytest

from .._index_integrity import (
    AuditVerdict,
    IndexAudit,
    _audit_payload_identity,
    _payload_value_matches,
    audit_index_integrity,
)
from .._markdown_passages import Passage
from .._source_types import PublicSourceType
from .._store_models import (
    CodeChunk,
    DocumentChunk,
    DocumentMetadata,
    DocumentPayload,
    VaultChunk,
    _code_chunk_payload,
    _vault_chunk_payload,
)
from ..config._types import EnvVar
from ..indexer._publication_proof import ProofEvidence
from ..indexer._run_ledger_models import RunAuthority, RunOperation
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..job_control import NO_RUN_CONTROL
from ..store_runtime import VaultStore
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


class _OptionalPayload(TypedDict, total=False):
    identity: Required[str]
    content: NotRequired[str]


@dataclass(frozen=True)
class _PublishedVault:
    root: Path
    store: VaultStore
    chunks: list[VaultChunk]

    def audit(self) -> IndexAudit:
        return audit_index_integrity(
            self.root,
            PublicSourceType.VAULT,
            RunAuthority.AUDIT_VERIFICATION,
            lambda: nullcontext(self.store),
        )


def _chunk(doc_id: str, ordinal: int, count: int) -> VaultChunk:
    text = f"Stored passage {ordinal}."
    return VaultChunk(
        doc_id=doc_id,
        ordinal=ordinal,
        chunk_count=count,
        text=text,
        path=f"{doc_id}.md",
        doc_type="adr",
        feature="storage",
        date="2026-09-01",
        tags=["#adr", "#storage"],
        related=[],
        title="Stored document",
        doc_content="Complete parent body." if ordinal == 0 else None,
        passages=(Passage(0, len(text), 1, 1, "Storage"),),
        vector=[0.1, 0.2, 0.3, 0.4],
    )


@pytest.fixture
def published_vault(tmp_path: Path) -> Iterator[_PublishedVault]:
    with (
        managed_env(
            **{
                EnvVar.QDRANT_URL.value: None,
                EnvVar.LOCAL_ONLY.value: "1",
                EnvVar.EMBEDDING_DIMENSION.value: "4",
            }
        ),
        VaultStore(tmp_path) as store,
    ):
        chunks = [_chunk("adr/stored.document", ordinal, 2) for ordinal in range(2)]
        checkpoint = VaultRunCheckpoint.open(
            tmp_path,
            backend_identity=store.backend_identity,
            authority=RunAuthority.REBUILD,
            operation=RunOperation.FULL,
            run_control=NO_RUN_CONTROL,
        )
        store.upsert_document_chunks(chunks, write_policy=None)
        checkpoint.record_confirmed_chunks(
            chunks, {chunks[0].doc_id: hashlib.blake2b(b"parent body").hexdigest()}
        )
        assert checkpoint.publish_proof_transition() == 1
        checkpoint.publish_generation()
        yield _PublishedVault(tmp_path, store, chunks)


def test_vault_audit_accepts_optional_content_and_nested_passages(
    published_vault: _PublishedVault,
) -> None:
    """Using display paths failed consistency; restoring doc_id identity passed."""
    result = published_vault.audit()

    assert result.verdict is AuditVerdict.CONSISTENT
    assert result.expected_identities == result.observed_identities == 1
    assert result.expected_points == result.scanned_points == result.matched_points == 2
    assert result.foreign_points == result.incompatible_points == 0


def test_resolved_typeddict_required_and_optional_fields() -> None:
    """Removing either field check failed rejection; restoring each passed."""
    assert _payload_value_matches({"identity": "document"}, _OptionalPayload)
    assert _payload_value_matches(
        {"identity": "document", "content": "body"}, _OptionalPayload
    )
    # Removing Required resolution admits the missing identity; removing the
    # optional field's validator admits a value its writer can never emit.
    assert not _payload_value_matches({"content": "body"}, _OptionalPayload)
    assert not _payload_value_matches(
        {"identity": "document", "content": None}, _OptionalPayload
    )


def test_code_audit_identity_accepts_nullable_schema_fields() -> None:
    chunk = CodeChunk(
        id="src/module.py:1",
        path="src/module.py",
        language="python",
        content="value = 1",
        line_start=1,
        line_end=1,
    )

    identity = _audit_payload_identity(
        PublicSourceType.CODE, {"payload": _code_chunk_payload(chunk)}
    )

    assert identity.point_id == "src/module.py:1"
    assert identity.rel_path == "src/module.py"
    assert identity.content_identity is None


def test_document_audit_identity_accepts_nullable_fields_and_metadata() -> None:
    chunk = DocumentChunk(
        id="document-point",
        payload=DocumentPayload(
            source_path="docs/guide.txt",
            unit_ordinal=0,
            content_fingerprint="document-digest",
            content="Document body.",
            document_metadata=DocumentMetadata.from_mapping({"revision": 3}),
            unit_metadata=DocumentMetadata.from_mapping({"source": ["page", 1]}),
        ),
    )

    identity = _audit_payload_identity(
        PublicSourceType.DOCUMENT,
        {"payload": VaultStore._document_chunk_payload(chunk)},
    )

    assert identity.point_id == "document-point"
    assert identity.rel_path == "docs/guide.txt"
    assert identity.content_identity == "document-digest"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        pytest.param("doc_content", None, id="optional-null"),
        pytest.param("doc_content", 7, id="optional-integer"),
        pytest.param("passages", ["passage"], id="nested-object-required"),
        pytest.param(
            "passages",
            [{"start": 0, "end": 5, "line_start": 1, "line_end": 1}],
            id="nested-required-field",
        ),
        pytest.param(
            "passages",
            [{"start": True, "end": 5, "line_start": 1, "line_end": 1, "section": ""}],
            id="nested-boolean-integer",
        ),
        pytest.param(
            "passages",
            [{"start": 0, "end": 5, "line_start": 1, "line_end": "1", "section": ""}],
            id="nested-field-type",
        ),
        pytest.param("tags", [7], id="list-element-type"),
        pytest.param("path", "../foreign.md", id="escaping-display-path"),
    ],
)
def test_vault_audit_rejects_malformed_payloads(
    published_vault: _PublishedVault,
    field_name: str,
    value: object,
) -> None:
    """Bypassing each check failed incompatible-point counts; restoring passed."""
    tail = published_vault.chunks[1]
    published_vault.store.client.set_payload(
        collection_name=published_vault.store.TABLE_NAME,
        points=[published_vault.store._stable_id(tail.point_key)],
        payload={field_name: value},
    )

    result = published_vault.audit()

    assert result.incompatible_points == 1
    assert result.matched_points == 1
    assert result.missing_points == 1
    assert result.verdict is AuditVerdict.DRIFT


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        pytest.param(
            "chunk_ordinal",
            True,
            "audit payload field 'chunk_ordinal' has an incompatible type",
            id="ordinal-boolean",
        ),
        pytest.param(
            "chunk_ordinal",
            -1,
            "audit payload field 'chunk_ordinal' must be a non-negative integer",
            id="ordinal-negative",
        ),
        pytest.param(
            "doc_id",
            "../foreign",
            "rel_path must be canonical project-relative POSIX syntax",
            id="escaping-proof-identity",
        ),
    ],
)
def test_vault_payload_identity_rejects_invalid_addresses(
    field_name: str, value: object, message: str
) -> None:
    """Bypassing each address check failed raises assertions; restoring passed."""
    payload = dict(_vault_chunk_payload(_chunk("adr/a", 0, 1)))
    payload[field_name] = value

    with pytest.raises(ValueError, match=f"^{message}$"):
        _audit_payload_identity(PublicSourceType.VAULT, {"payload": payload})


def test_vault_audit_rejects_missing_required_payload_fields(
    published_vault: _PublishedVault,
) -> None:
    """Removing required-key checks failed the count assertion; restoring passed."""
    tail = published_vault.chunks[1]
    payload = dict(_vault_chunk_payload(tail))
    del payload["title"]
    published_vault.store.client.overwrite_payload(
        collection_name=published_vault.store.TABLE_NAME,
        points=[published_vault.store._stable_id(tail.point_key)],
        payload=payload,
    )

    # Removing the required-key check admits the corrupted point as complete.
    assert published_vault.audit().incompatible_points == 1


def test_vault_audit_rejects_extra_document_identities(
    published_vault: _PublishedVault,
) -> None:
    """Omitting extra-point classification failed its count; restoring passed."""
    published_vault.store.upsert_document_chunks(
        [_chunk("adr/foreign", 0, 1)], write_policy=None
    )

    result = published_vault.audit()

    # Bypassing retained membership loses the independent extra-point count.
    assert result.extra_points == 1
    assert result.matched_points == 2
    assert result.observed_identities == 2
    assert result.verdict is AuditVerdict.DRIFT


def test_vault_audit_rejects_points_attributed_to_another_identity(
    published_vault: _PublishedVault,
) -> None:
    """Omitting foreign-point classification failed its count; restoring passed."""
    checkpoint = VaultRunCheckpoint.open(
        published_vault.root,
        backend_identity=published_vault.store.backend_identity,
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    checkpoint.ledger.establish_verified_publication(
        checkpoint.generation_id,
        RunAuthority.REBUILD,
        (
            ProofEvidence(
                "adr/another-document",
                hashlib.blake2b(b"parent body").hexdigest(),
                tuple(chunk.point_key for chunk in published_vault.chunks),
            ),
        ),
    )

    result = published_vault.audit()

    # Checking retained IDs alone would certify both foreign identities.
    assert result.foreign_points == 2
    assert result.extra_points == result.incompatible_points == 0
    assert result.matched_points == 0
    assert result.verdict is AuditVerdict.DRIFT
