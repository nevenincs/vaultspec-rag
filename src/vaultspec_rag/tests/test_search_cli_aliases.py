"""CLI parser aliases for search."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from ..cli import app

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def test_search_type_docs_alias_uses_document_search_language() -> None:
    result = runner.invoke(
        app,
        [
            "search",
            "anything",
            "--type",
            "docs",
            "--function-name",
            "foo",
        ],
    )

    output = " ".join(result.output.split())
    assert result.exit_code == 2
    assert "require --type code" in output
    assert "got --type docs" in output
    assert "Invalid value for '--type'" not in output


def test_docs_search_type_accepts_document_filters() -> None:
    from ..search import validate_search_filters

    validate_search_filters("docs", doc_type="adr")
