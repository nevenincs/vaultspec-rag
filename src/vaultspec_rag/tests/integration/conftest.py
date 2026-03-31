"""RAG integration test fixtures."""

import shutil

import pytest

from ..conftest import _build_rag_components
from ..constants import (
    QDRANT_SUFFIX_UNIT,
    TEST_PROJECT,
)

QDRANT_SUFFIX_CODE = "-fast-code"


@pytest.fixture(scope="session")
def rag_components(embedding_model):
    """Set up real RAG components once for the entire test session.

    Indexes a 13-doc subset covering all 5 doc_types and key features.
    Uses .qdrant-fast-unit/ to avoid colliding with integration fixtures.
    """
    components = _build_rag_components(
        TEST_PROJECT,
        fast=True,
        qdrant_suffix=QDRANT_SUFFIX_UNIT,
        model=embedding_model,
    )

    yield components

    components["store"].close()
    db_dir = components["db_dir"]
    if db_dir.exists():
        shutil.rmtree(db_dir)


@pytest.fixture(scope="session")
def rag_components_with_code(embedding_model):
    """RAG components with vault (fast subset) + real test-project/src/ code indexed.

    Uses .qdrant-fast-code/ to avoid colliding with other fixtures.
    Exercises the 6 Nexus Python source files in test-project/src/.
    """
    components = _build_rag_components(
        TEST_PROJECT,
        fast=True,
        qdrant_suffix=QDRANT_SUFFIX_CODE,
        model=embedding_model,
    )

    # Index the real test-project/src/ codebase
    code_indexer = components["code_indexer"]
    code_indexer.full_index()

    yield components

    components["store"].close()
    db_dir = components["db_dir"]
    if db_dir.exists():
        shutil.rmtree(db_dir)
