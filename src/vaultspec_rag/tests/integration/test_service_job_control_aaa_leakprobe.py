"""Temporary probe: leak two open project slots into the registry singleton."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...config._settings import get_config
from ...registry import get_registry

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel

pytestmark = pytest.mark.integration


def test_leaks_two_open_projects(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
) -> None:
    """Leave two open slots behind, exactly as a cut-short teardown would."""
    get_config(
        {
            "data_dir": ".leak-probe",
            "status_dir": str(tmp_path / "status"),
            "qdrant_url": None,
            "qdrant_server": False,
            "local_only": True,
            "index_support_profile": "embedded-local",
            "sparse_enabled": False,
            "reranker_enabled": False,
            "embedding_dimension": embedding_model.dimension,
        }
    )
    registry = get_registry()
    registry._model = embedding_model  # pyright: ignore[reportPrivateUsage]
    for name in ("leak-one", "leak-two"):
        root = tmp_path / name
        (root / ".vault").mkdir(parents=True)
        registry.peek_project(root)
    assert registry.health()["project_count"] == 2
