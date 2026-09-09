"""Generation-local evidence for one indexed document source."""

from __future__ import annotations

from dataclasses import dataclass

from ._document_identity import normalize_document_source_path

__all__ = ["DocumentFileMetadata"]


@dataclass(frozen=True, slots=True)
class DocumentFileMetadata:
    """Content identity and retained point IDs for one document path."""

    source_path: str
    content_fingerprint: str
    point_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if normalize_document_source_path(self.source_path) != self.source_path:
            raise ValueError("document source path is not normalized")
        if not self.content_fingerprint:
            raise ValueError("document content fingerprint must not be empty")
        if not self.point_ids or any(not point_id for point_id in self.point_ids):
            raise ValueError("document point IDs must not be empty")
        if len(set(self.point_ids)) != len(self.point_ids):
            raise ValueError("document point IDs must be unique")
