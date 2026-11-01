"""Canonical vault paths and document IDs shared by producers and readers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, overload

if TYPE_CHECKING:
    from pathlib import Path


@overload
def vault_relative_path(
    path: Path,
    docs_dir: Path,
    *,
    allow_basename: Literal[True],
) -> str: ...


@overload
def vault_relative_path(
    path: Path,
    docs_dir: Path,
    *,
    allow_basename: Literal[False] = False,
) -> str | None: ...


def vault_relative_path(
    path: Path,
    docs_dir: Path,
    *,
    allow_basename: bool = False,
) -> str | None:
    """Name a path under the docs root without requiring that it still exists."""
    try:
        return str(path.relative_to(docs_dir)).replace("\\", "/")
    except ValueError:
        return path.name if allow_basename else None


def vault_document_id(relative_path: str) -> str:
    """Retain the established docs-relative ID with its final suffix removed."""
    return relative_path.rsplit(".", 1)[0] if "." in relative_path else relative_path
