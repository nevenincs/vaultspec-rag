"""Unit tests for VaultStore helper functions.

Extracted from tests/test_rag_store.py.
Tests updated for Qdrant-backed store (replacing LanceDB).
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]


class TestStoreHelpers:
    """Tests for store utility functions and edge cases."""

    def test_build_filter_returns_qdrant_filter(self):
        """_build_filter should return a Qdrant Filter with correct conditions."""
        from qdrant_client import models

        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter({"doc_type": "adr"})
        assert result is not None
        assert isinstance(result, models.Filter)
        assert len(result.must) == 1
        assert result.must[0].key == "doc_type"

    def test_build_filter_multiple_conditions(self):
        """_build_filter with multiple keys should produce multiple conditions."""
        from qdrant_client import models

        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter({"doc_type": "adr", "feature": "rag"})
        assert result is not None
        assert isinstance(result, models.Filter)
        assert len(result.must) == 2

    def test_build_filter_empty_returns_none(self):
        """_build_filter with empty dict should return None."""
        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter({})
        assert result is None

    def test_build_filter_none_returns_none(self):
        """_build_filter with None should return None."""
        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter(None)
        assert result is None

    def test_build_filter_date_uses_match_text(self):
        """_build_filter date key should use MatchText for prefix matching."""
        from qdrant_client import models

        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter({"date": "2026-02"})
        assert result is not None
        assert isinstance(result.must[0].match, models.MatchText)

    def test_build_filter_ignores_unknown_keys(self):
        """_build_filter should ignore keys not in (doc_type, feature, date)."""
        from vaultspec_rag.store import VaultStore

        result = VaultStore._build_filter({"unknown_key": "value"})
        assert result is None

    def test_stable_id_deterministic(self):
        """_stable_id should return the same integer for the same input."""
        from vaultspec_rag.store import VaultStore

        id1 = VaultStore._stable_id("test-doc")
        id2 = VaultStore._stable_id("test-doc")
        assert id1 == id2
        assert isinstance(id1, int)

    def test_stable_id_different_inputs(self):
        """_stable_id should return different integers for different inputs."""
        from vaultspec_rag.store import VaultStore

        id1 = VaultStore._stable_id("doc-a")
        id2 = VaultStore._stable_id("doc-b")
        assert id1 != id2
