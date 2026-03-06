"""RAG unit test fixtures."""

import shutil

import pytest

from vaultspec_rag.tests.conftest import _build_rag_components
from vaultspec_rag.tests.constants import (
    QDRANT_SUFFIX_UNIT,
    TEST_PROJECT,
)


@pytest.fixture(scope="session")
def rag_components():
    """Set up real RAG components once for the entire test session.

    Indexes a 13-doc subset covering all 5 doc_types and key features.
    Uses .qdrant-fast-unit/ to avoid colliding with integration fixtures.
    """
    components = _build_rag_components(
        TEST_PROJECT, fast=True, qdrant_suffix=QDRANT_SUFFIX_UNIT
    )

    yield components

    db_dir = components["db_dir"]
    if db_dir.exists():
        shutil.rmtree(db_dir)
