"""Real-store public search checks for empty independent domains."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..._public_search import search_combined, search_documents

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def test_empty_document_and_combined_search_need_no_model(tmp_path: Path) -> None:
    assert search_documents(tmp_path, "query") == []
    combined = search_combined(tmp_path, "query")
    assert combined.results == []
    assert not combined.partial
    assert combined.vault.ok
    assert combined.code.ok
    assert combined.document.ok
