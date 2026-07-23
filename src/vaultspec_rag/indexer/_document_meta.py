"""Independent atomic metadata publication for the document collection."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .. import store_schema
from ._document_identity import normalize_document_source_path

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from ._file_state import FileState

__all__ = [
    "DOCUMENT_EMBED_SCHEMA",
    "DOCUMENT_META_FILENAME",
    "DOCUMENT_META_SCHEMA_VERSION",
    "DocumentFileMetadata",
    "DocumentIndexMetadata",
    "DocumentMetadataError",
    "document_meta_compatible",
    "document_metadata_path",
    "publish_document_meta_from_file_states",
    "read_document_meta",
    "write_document_meta",
]

DOCUMENT_META_FILENAME = "document_index_meta.json"
DOCUMENT_META_SCHEMA_VERSION = 2
DOCUMENT_EMBED_SCHEMA = 1


class DocumentMetadataError(ValueError):
    """Raised when a document sidecar cannot prove its declared state."""


@dataclass(frozen=True, slots=True)
class DocumentFileMetadata:
    """Published document state for one normalized source path."""

    source_path: str
    content_fingerprint: str
    point_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized = normalize_document_source_path(self.source_path)
        if normalized != self.source_path:
            raise ValueError("document metadata source path is not normalized")
        if not self.content_fingerprint:
            raise ValueError("document metadata content fingerprint must not be empty")
        if any(not point_id for point_id in self.point_ids):
            raise ValueError("document metadata point IDs must not be empty")
        if len(set(self.point_ids)) != len(self.point_ids):
            raise ValueError("document metadata point IDs must be unique")


@dataclass(frozen=True, slots=True)
class DocumentIndexMetadata:
    """Complete compatibility evidence for one published document generation."""

    membership_fingerprint: str
    content_fingerprint: str
    policy_snapshot: str
    files: tuple[DocumentFileMetadata, ...]
    generation_id: str | None = None
    meta_schema_version: int = DOCUMENT_META_SCHEMA_VERSION
    storage_schema_version: int = store_schema.STORAGE_SCHEMA_VERSION
    complete: bool = True

    def __post_init__(self) -> None:
        if self.meta_schema_version not in (1, DOCUMENT_META_SCHEMA_VERSION):
            raise ValueError("unsupported document metadata schema version")
        if self.storage_schema_version != store_schema.STORAGE_SCHEMA_VERSION:
            raise ValueError("unsupported document storage schema version")
        if not all(
            (
                self.membership_fingerprint,
                self.content_fingerprint,
                self.policy_snapshot,
            )
        ):
            raise ValueError("document metadata fingerprints must not be empty")
        if self.meta_schema_version == DOCUMENT_META_SCHEMA_VERSION:
            if self.generation_id is None or not self.generation_id.strip():
                raise ValueError("current document metadata requires a generation ID")
        elif self.generation_id is not None:
            raise ValueError("legacy document metadata cannot carry a generation ID")
        paths = tuple(file.source_path for file in self.files)
        if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
            raise ValueError("document metadata files must be uniquely path-sorted")

    def as_payload(self) -> dict[str, object]:
        """Return the deterministic JSON publication payload."""
        return {
            "meta_schema_version": self.meta_schema_version,
            "storage_schema_version": self.storage_schema_version,
            "content_kind": "document",
            "membership_fingerprint": self.membership_fingerprint,
            "content_fingerprint": self.content_fingerprint,
            "policy_snapshot": self.policy_snapshot,
            "generation_id": self.generation_id,
            "complete": self.complete,
            "files": [
                {
                    "source_path": file.source_path,
                    "content_fingerprint": file.content_fingerprint,
                    "point_ids": list(file.point_ids),
                }
                for file in self.files
            ],
        }


def document_metadata_path(root_dir: Path) -> Path:
    """Return the independently named document sidecar path for one root."""
    from ..config import get_config

    return root_dir.resolve() / get_config().data_dir / DOCUMENT_META_FILENAME


def _object_dict(value: object, message: str) -> dict[str, object]:
    """Narrow one decoded JSON object to string-keyed storage."""
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in cast("dict[object, object]", value)
    ):
        raise DocumentMetadataError(message)
    return cast("dict[str, object]", value)


def _required_str(payload: dict[str, object], key: str) -> str:
    """Read one required non-empty string from a sidecar object."""
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise DocumentMetadataError(f"document metadata {key} is invalid")
    return value


def _required_int(payload: dict[str, object], key: str) -> int:
    """Read one required non-boolean integer from a sidecar object."""
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DocumentMetadataError(f"document metadata {key} is invalid")
    return value


def _file_from_payload(value: object) -> DocumentFileMetadata:
    """Validate one decoded file entry."""
    payload = _object_dict(value, "document metadata file entry is invalid")
    raw_ids = payload.get("point_ids")
    if not isinstance(raw_ids, list) or not all(
        isinstance(point_id, str) for point_id in cast("list[object]", raw_ids)
    ):
        raise DocumentMetadataError("document metadata point IDs are invalid")
    return DocumentFileMetadata(
        _required_str(payload, "source_path"),
        _required_str(payload, "content_fingerprint"),
        tuple(cast("list[str]", raw_ids)),
    )


def _from_payload(value: object) -> DocumentIndexMetadata:
    """Validate one decoded sidecar payload into immutable metadata."""
    payload = _object_dict(value, "document metadata must be a JSON object")
    if payload.get("content_kind") != "document":
        raise DocumentMetadataError("document metadata carries the wrong content kind")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        raise DocumentMetadataError("document metadata files must be a list")
    try:
        files = tuple(
            _file_from_payload(raw_file) for raw_file in cast("list[object]", raw_files)
        )
        complete = payload.get("complete")
        if not isinstance(complete, bool):
            raise DocumentMetadataError("document metadata completeness is invalid")
        meta_schema_version = _required_int(payload, "meta_schema_version")
        raw_generation_id = payload.get("generation_id")
        generation_id = (
            _required_str(payload, "generation_id")
            if raw_generation_id is not None
            else None
        )
        return DocumentIndexMetadata(
            _required_str(payload, "membership_fingerprint"),
            _required_str(payload, "content_fingerprint"),
            _required_str(payload, "policy_snapshot"),
            files,
            generation_id=generation_id,
            meta_schema_version=meta_schema_version,
            storage_schema_version=_required_int(payload, "storage_schema_version"),
            complete=complete,
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, DocumentMetadataError):
            raise
        raise DocumentMetadataError("document metadata is malformed") from exc


def read_document_meta(meta_path: Path) -> DocumentIndexMetadata | None:
    """Read a document sidecar, returning ``None`` only when it is absent."""
    if not meta_path.exists():
        return None
    try:
        return _from_payload(json.loads(meta_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise DocumentMetadataError("document metadata cannot be read") from exc


def write_document_meta(meta_path: Path, metadata: DocumentIndexMetadata) -> None:
    """Publish document metadata and its explicit completeness state atomically."""
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = meta_path.with_name(f".{meta_path.name}.{os.getpid()}.tmp")
    encoded = json.dumps(
        metadata.as_payload(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, meta_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def publish_document_meta_from_file_states(
    meta_path: Path,
    states: Iterable[FileState],
    *,
    point_ids_for_path: Callable[[str], Iterable[str]],
    generation_id: str,
    membership_fingerprint: str,
    content_fingerprint: str,
    policy_snapshot: str,
) -> int:
    """Atomically publish one complete document manifest from ledger evidence."""
    from ._file_state import FileStateKind

    files: list[DocumentFileMetadata] = []
    previous_path: str | None = None
    for state in states:
        if not state.converged:
            raise ValueError(
                f"cannot publish unresolved file state for {state.rel_path}"
            )
        if previous_path is not None and state.rel_path <= previous_path:
            raise ValueError("ledger file states must be uniquely path-sorted")
        previous_path = state.rel_path
        if state.state is not FileStateKind.INDEXED:
            continue
        assert state.content_hash is not None
        point_ids = tuple(point_ids_for_path(state.rel_path))
        if not point_ids:
            raise ValueError(
                f"indexed document state has no retained points for {state.rel_path}"
            )
        files.append(
            DocumentFileMetadata(state.rel_path, state.content_hash, point_ids)
        )
    write_document_meta(
        meta_path,
        DocumentIndexMetadata(
            membership_fingerprint,
            content_fingerprint,
            policy_snapshot,
            tuple(files),
            generation_id=generation_id,
        ),
    )
    return len(files)


def document_meta_compatible(
    metadata: DocumentIndexMetadata | None,
    *,
    membership_fingerprint: str,
    content_fingerprint: str,
) -> bool:
    """Return whether published evidence matches the requested document policy."""
    return bool(
        metadata is not None
        and metadata.complete
        and metadata.generation_id is not None
        and metadata.membership_fingerprint == membership_fingerprint
        and metadata.content_fingerprint == content_fingerprint
        and metadata.meta_schema_version == DOCUMENT_META_SCHEMA_VERSION
        and metadata.storage_schema_version == store_schema.STORAGE_SCHEMA_VERSION
    )
