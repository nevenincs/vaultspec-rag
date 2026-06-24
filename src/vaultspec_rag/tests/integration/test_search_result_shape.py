"""Result-shape tests: enriched vault frontmatter in human and JSON output.

Pure (no GPU): the rendering helper and the JSON serialization of
``SearchResult`` are exercised directly, confirming that ``status`` and
``related`` reach both surfaces and that codebase results gain no vault
metadata line.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from ...cli._render import _display_search_results, _search_result_meta_line
from ...search import SearchResult

if TYPE_CHECKING:
    import pytest


class TestResultShape:
    """The enriched fields must render (human) and serialize (JSON)."""

    def test_meta_line_surfaces_status_and_related(self) -> None:
        line = _search_result_meta_line(
            {
                "doc_type": "adr",
                "feature": "service-concurrency",
                "status": "accepted",
                "date": "2026-06-12",
                "related": ["a", "b"],
            }
        )
        assert line is not None
        assert "adr" in line
        assert "status: accepted" in line
        assert "related: a, b" in line

    def test_meta_line_omits_empty_status(self) -> None:
        line = _search_result_meta_line(
            {"doc_type": "exec", "feature": "x", "status": "", "related": []}
        )
        assert line is not None
        assert "status:" not in line

    def test_codebase_result_has_no_meta_line(self) -> None:
        assert _search_result_meta_line({"language": "python"}) is None

    def test_searchresult_json_carries_fields(self) -> None:
        sr = SearchResult(
            id="adr/x",
            path=".vault/adr/x.md",
            title="t",
            score=0.5,
            snippet="s",
            source="vault",
            doc_type="adr",
            feature="svc",
            date="2026-06-12",
            status="accepted",
            related=["a", "b"],
        )
        payload = asdict(sr)
        assert payload["status"] == "accepted"
        assert payload["related"] == ["a", "b"]

    def test_human_render_includes_meta(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        results: list[dict[str, object]] = [
            {
                "path": ".vault/adr/x.md",
                "doc_type": "adr",
                "feature": "svc",
                "status": "accepted",
                "date": "2026-06-12",
                "related": ["a"],
                "snippet": "body text",
                "score": 0.5,
            }
        ]
        _display_search_results(results, "vault")
        out = capsys.readouterr().out
        assert "status: accepted" in out
        assert "feature: svc" in out
