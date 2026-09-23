"""Real-payload tests for document-native result shaping."""

from __future__ import annotations

import pytest

from ..search._models import DocumentSearchResult, ResultPassage, SearchResult
from ..search._result_shaping import (
    MAX_PASSAGES_PER_RESULT,
    PASSAGE_PAIRS_PER_PAGE,
    map_document_results,
    passage_pairs,
    select_combined_results,
    vault_row_passages,
)

pytestmark = pytest.mark.unit


def test_document_result_retains_identity_locator_metadata_and_rerank_text() -> None:
    content = "Full extracted content used for reranking"
    results = map_document_results(
        [
            {
                "id": "chunk-1",
                "source_path": "manuals/guide.bin",
                "title": "Guide",
                "section": "Setup",
                "anchor": "page-4",
                "content": content,
                "locator_kind": "page",
                "locator_value_int": 4,
                "document_metadata": {"owner": "docs"},
                "unit_metadata": {"language": "en"},
                "extractor_id": "extractor",
                "extractor_version": "2",
                "_relevance_score": 0.75,
            }
        ]
    )
    assert len(results) == 1
    result = results[0]
    assert result.path == "manuals/guide.bin"
    assert result.locator is not None
    assert result.locator.kind == "page"
    assert result.locator.value == 4
    assert result.document_metadata.materialize() == {"owner": "docs"}
    assert result.unit_metadata.materialize() == {"language": "en"}
    assert result.rerank_text == content


def test_invalid_document_metadata_does_not_escape_as_mis_shaped_hit() -> None:
    assert (
        map_document_results(
            [
                {
                    "id": "chunk-1",
                    "source_path": "manuals/guide.bin",
                    "content": "content",
                    "document_metadata": "invalid",
                    "unit_metadata": {},
                }
            ]
        )
        == []
    )


def test_combined_selection_is_stable_across_equal_domain_scores() -> None:
    vault = SearchResult("v", "z.md", "Vault", 0.5, "v", "vault")
    code = SearchResult("c", "a.py", "Code", 0.5, "c", "codebase")
    document = DocumentSearchResult("d", "a.bin", "Document", 0.8, "d")
    assert select_combined_results([code, vault, document], 2) == [document, vault]


def test_vault_row_passages_read_text_at_their_stored_offsets() -> None:
    content = "## Options\n\nFirst option text.\n\nSecond option text."
    first = content.index("First")
    second = content.index("Second")
    passages = vault_row_passages(
        {
            "passages": [
                {
                    "start": first,
                    "end": first + len("First option text."),
                    "line_start": 12,
                    "line_end": 12,
                    "section": "Options",
                },
                {
                    "start": second,
                    "end": len(content),
                    "line_start": 14,
                    "line_end": 14,
                    "section": "Options",
                },
            ]
        },
        content,
    )
    assert [passage.text for passage in passages] == [
        "First option text.",
        "Second option text.",
    ]
    assert [passage.line_start for passage in passages] == [12, 14]


def test_vault_row_passages_skip_entries_that_do_not_fit_the_content() -> None:
    content = "short"
    passages = vault_row_passages(
        {
            "passages": [
                {"start": 0, "end": 99, "line_start": 1, "line_end": 1, "section": ""},
                {"start": 0, "end": 5, "line_start": 1, "section": ""},
                "not an entry",
                {"start": 0, "end": 5, "line_start": 3, "line_end": 3, "section": ""},
            ]
        },
        content,
    )
    assert [(p.text, p.line_start) for p in passages] == [("short", 3)]


def test_a_vault_row_without_passages_yields_none() -> None:
    assert vault_row_passages({"content": "legacy"}, "legacy") == ()


def _located(result_id: str, candidates: int) -> SearchResult:
    result = SearchResult(
        id=result_id,
        path=f".vault/adr/{result_id}.md",
        title=result_id,
        score=0.5,
        snippet="chunk head",
        source="vault",
    )
    result.passages = tuple(
        ResultPassage(f"{result_id} passage {n}", 10 + n, 10 + n, "Options")
        for n in range(candidates)
    )
    return result


def test_passage_pairs_spend_the_page_budget_in_rank_order() -> None:
    page = [_located(f"r{rank}", MAX_PASSAGES_PER_RESULT) for rank in range(6)]
    pairs, owners = passage_pairs("query", page)
    scored = {owner.id for owner, _ in owners}
    whole_results = PASSAGE_PAIRS_PER_PAGE // MAX_PASSAGES_PER_RESULT
    # Dropping the budget scores every result on the page, and this fails.
    assert scored == {f"r{rank}" for rank in range(whole_results)}
    assert len(pairs) == whole_results * MAX_PASSAGES_PER_RESULT
    assert all(query == "query" for query, _ in pairs)
    assert [result.snippet for result in page] == [
        f"r{rank} passage 0" for rank in range(6)
    ]


def test_passage_pairs_never_split_a_result_across_the_budget() -> None:
    full, leftover = divmod(PASSAGE_PAIRS_PER_PAGE - 2, MAX_PASSAGES_PER_RESULT)
    page = [_located(f"r{rank}", MAX_PASSAGES_PER_RESULT) for rank in range(full)]
    page.append(_located("tail", leftover))
    # Two pairs of budget remain: the next result needs three, and the one
    # after it, which would fit, is still not scored out of rank order.
    page += [_located("overruns", 3), _located("later", 2)]
    _pairs, owners = passage_pairs("query", page)
    assert {owner.id for owner, _ in owners} == {
        *(f"r{rank}" for rank in range(full)),
        "tail",
    }


def test_a_single_candidate_is_shown_without_being_scored() -> None:
    page = [_located("single", 1)]
    pairs, _owners = passage_pairs("query", page)
    assert pairs == []
    assert page[0].snippet == "single passage 0"
    assert (page[0].line_start, page[0].section) == (10, "Options")
