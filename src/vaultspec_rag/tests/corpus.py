"""Synthetic corpora for tests.

The single-vault generator lives in ``vaultspec_rag.synthetic`` because the
product's own quality command builds one. The multi-project builder exists
only for tests, so it lives here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..synthetic import CorpusManifest, GeneratedDoc, build_synthetic_vault

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CorpusManifest",
    "GeneratedDoc",
    "build_multi_project_fixture",
    "build_synthetic_vault",
]


def build_multi_project_fixture(
    base: Path,
    *,
    n_projects: int = 2,
    docs_per_project: int = 12,
    seed: int = 42,
) -> list[CorpusManifest]:
    """Create project roots with distinct, non-overlapping corpora.

    Args:
        base: Parent directory; each project is a subdirectory.
        n_projects: Number of project roots to create.
        docs_per_project: Documents per project.
        seed: Base random seed, incremented per project.

    Returns:
        One manifest per project.
    """
    manifests: list[CorpusManifest] = []
    for i in range(n_projects):
        project_root = base / f"project-{i}"
        project_root.mkdir(parents=True, exist_ok=True)
        manifests.append(
            build_synthetic_vault(project_root, n_docs=docs_per_project, seed=seed + i)
        )
    return manifests
