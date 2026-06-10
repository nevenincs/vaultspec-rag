"""Vault document preparation and the shared :class:`IndexResult` type.

Reads markdown vault files, parses frontmatter via vaultspec-core, and
builds :class:`~vaultspec_rag.store.VaultDocument` instances ready for
embedding. Also defines the :class:`IndexResult` dataclass returned by
both indexers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vaultspec_core.vaultcore import (  # pyright: ignore[reportMissingTypeStubs]  # no stubs for vaultspec_core
    DocType,
    get_doc_type,
    parse_vault_metadata,
)

from ..store import VaultDocument

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)

__all__ = [
    "IndexResult",
    "_extract_feature",
    "_extract_title",
    "prepare_document",
]


@dataclass
class IndexResult:
    """Result of an indexing operation.

    Attributes:
        total: Total number of items in the index after the operation.
        added: Number of newly indexed items.
        updated: Number of re-indexed (modified) items.
        removed: Number of items removed from the index.
        duration_ms: Wall-clock time for the operation in milliseconds.
        device: Compute device used for embeddings (e.g. ``"cuda"``).
        files: Number of files processed (for codebase indexing).
    """

    total: int
    added: int
    updated: int
    removed: int
    duration_ms: int
    device: str
    files: int = 0


def _extract_title(body: str) -> str:
    """Extract first H1 heading from markdown body, or return empty string.

    Args:
        body: Raw markdown text to scan.

    Returns:
        The heading text (without the leading ``# ``), or ``""`` if none found.
    """
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _extract_feature(metadata_tags: list[str]) -> str:
    """Extract the feature tag (non-directory tag) from the tag list.

    Args:
        metadata_tags: List of frontmatter tag strings (e.g. ``["#plan", "#rag"]``).

    Returns:
        The feature tag value without the leading ``#``, or ``""`` if none found.
    """
    for tag in metadata_tags:
        if not DocType.from_tag(tag):
            return tag.lstrip("#")
    return ""


def prepare_document(
    path: pathlib.Path,
    root_dir: pathlib.Path,
) -> VaultDocument | None:
    """Prepare a single vault document for indexing (without vector).

    Reads the file, parses metadata, and constructs a VaultDocument
    with all fields except the vector (which is filled during embedding).

    Args:
        path: Absolute path to the markdown document file.
        root_dir: Workspace root directory used to compute the relative path.

    Returns:
        A ``VaultDocument`` with an empty vector, or ``None`` if the file
        cannot be read or has no recognised doc type.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Cannot read %s: %s", path, e)
        return None

    metadata, body = parse_vault_metadata(content)
    doc_type_enum = get_doc_type(path, root_dir)

    if doc_type_enum is None:
        return None

    from ..config import get_config

    docs_dir = root_dir / get_config().docs_dir
    try:
        rel_path = str(path.relative_to(docs_dir)).replace("\\", "/")
    except ValueError as exc:
        logger.debug(
            "relative_to(%s) failed for %s: %s; using basename",
            docs_dir,
            path,
            exc,
        )
        rel_path = path.name

    title = _extract_title(body)
    if not title:
        title = path.stem

    feature = _extract_feature(metadata.tags)

    # Use relative path (without extension) as ID to avoid collisions
    # e.g., "adr/overview" instead of just "overview"
    doc_id = rel_path.rsplit(".", 1)[0] if "." in rel_path else rel_path

    return VaultDocument(
        id=doc_id,
        path=rel_path,
        doc_type=doc_type_enum.value,
        feature=feature,
        date=metadata.date or "",
        tags=metadata.tags,
        related=metadata.related,
        title=title,
        content=body.strip(),
        vector=[],  # filled during embedding step
    )
