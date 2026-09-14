"""Result-shape tests: enriched vault frontmatter in human and JSON output.

Pure (no GPU): the rendering helper and the JSON serialization of
``SearchResult`` are exercised directly, confirming that ``status`` and
``related`` reach both surfaces and that codebase results gain no vault
metadata line.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from ...cli._render import _display_search_results, _search_result_meta_line
from ...search import SearchResult
from ...server._models import SearchResultItem

pytestmark = [pytest.mark.unit]


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

    def test_service_serialization_preserves_rank_order_and_exact_shape(self) -> None:
        """Readiness wrapping must not reorder hits or erase result metadata.

        Mutation proof: removing ``status`` and ``related`` from the transport model
        failed on the exact ``payload[0]["status"]`` assertion (exit 1); restoring
        both fields passed this test (exit 0).
        """
        ranked = [
            SearchResult(
                id="first",
                path=".vault/adr/first.md",
                title="First",
                score=0.91,
                snippet="first body",
                source="vault",
                doc_type="adr",
                feature="readiness",
                date="2026-09-08",
                status="accepted",
                related=["decision", "plan"],
                rerank_text="private full content",
            ),
            SearchResult(
                id="second",
                path="src/second.py",
                title="second",
                score=0.73,
                snippet="def second(): ...",
                source="codebase",
                language="python",
                line_start=4,
                line_end=7,
            ),
        ]

        payload = [
            SearchResultItem.model_validate(result, from_attributes=True).model_dump(
                mode="json"
            )
            for result in ranked
        ]

        assert [item["id"] for item in payload] == ["first", "second"]
        assert [item["score"] for item in payload] == [0.91, 0.73]
        assert payload[0]["status"] == "accepted"
        assert payload[0]["related"] == ["decision", "plan"]
        assert payload[1]["language"] == "python"
        assert payload[1]["line_start"] == 4
        assert payload[1]["line_end"] == 7
        assert set(payload[0]) == {
            "id",
            "path",
            "title",
            "score",
            "snippet",
            "source",
            "doc_type",
            "feature",
            "date",
            "status",
            "related",
            "language",
            "line_start",
            "line_end",
            "node_type",
            "function_name",
            "class_name",
            "source_path",
            "preprocessor_id",
            "anchor",
            "locator",
            "section",
            "document_metadata",
            "unit_metadata",
            "extractor_id",
            "extractor_version",
        }
        assert "rerank_text" not in payload[0]
