"""Deterministic collection-local identities for document chunks."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .._store_models import DocumentLocator

__all__ = ["document_point_id", "normalize_document_source_path"]

DOCUMENT_ID_VERSION = 1


def normalize_document_source_path(source_path: str) -> str:
    """Return one canonical project-relative POSIX source identity.

    The identity is path-layout neutral: it normalizes separators and redundant
    ``.`` segments but assigns no meaning to any directory or filename.
    """
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValueError("document source path must be a non-empty string")
    normalized_input = source_path.replace("\\", "/")
    path = PurePosixPath(normalized_input)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError("document source path must remain project-relative")
    normalized = path.as_posix()
    if normalized in {"", "."}:
        raise ValueError("document source path must identify a file")
    return normalized


def _locator_identity(locator: DocumentLocator | None, unit_ordinal: int) -> object:
    """Return the native locator identity, falling back to the unit ordinal."""
    if isinstance(unit_ordinal, bool) or not isinstance(unit_ordinal, int):
        raise TypeError("document unit ordinal must be an integer")
    if unit_ordinal < 0:
        raise ValueError("document unit ordinal must be non-negative")
    if locator is None or locator.kind == "none":
        return {"unit_ordinal": unit_ordinal}
    return {
        "kind": locator.kind,
        "value": locator.value,
        "end": locator.end,
    }


def document_point_id(
    *,
    source_path: str,
    unit_ordinal: int,
    content_fingerprint: str,
    locator: DocumentLocator | None = None,
) -> str:
    """Derive a stable document point ID from collection-local semantics."""
    if not isinstance(content_fingerprint, str) or not content_fingerprint:
        raise ValueError("document content fingerprint must be a non-empty string")
    payload = {
        "version": DOCUMENT_ID_VERSION,
        "source_path": normalize_document_source_path(source_path),
        "location": _locator_identity(locator, unit_ordinal),
        "content_fingerprint": content_fingerprint,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.blake2b(canonical.encode("utf-8"), digest_size=20).hexdigest()
    return f"d_{digest}"
