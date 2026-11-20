"""The CLI, MCP and service-client surfaces for document metadata filters.

Each adapter passes the filters through unchanged and renders the search
domain's refusal; none of them decides which keys a root declares.
"""

from __future__ import annotations

import json

import pytest

from .._source_types import PublicSourceType
from ..mcp._tools import _validated_search_result
from ..serviceclient._search_transport import _build_http_search_payload
from ..serviceclient._transport import DocumentSearchFilters, SearchCallRequest
from ._cli_helpers import app, runner

pytestmark = pytest.mark.unit


def test_client_sends_the_metadata_mapping_and_prefix_unchanged() -> None:
    payload = _build_http_search_payload(
        SearchCallRequest(
            query="manual",
            search_type="document",
            top_k=5,
            port=1,
            project_root="/tmp/proj",
            document_filters=DocumentSearchFilters(
                extractor_id="pdf.text,pdf.ocr",
                extractor_prefix="pdf",
                metadata_filters={"lang": ["en", "de, at"]},
            ),
        ),
        PublicSourceType.DOCUMENT,
        freshness_policy="immediate",
        freshness_wait_seconds=None,
    )
    assert payload["extractor_id"] == "pdf.text,pdf.ocr"
    assert payload["extractor_prefix"] == "pdf"
    # A value holding a comma survives the mapping form intact.
    assert payload["metadata_filters"] == {"lang": ["en", "de, at"]}


@pytest.mark.parametrize("source", [PublicSourceType.VAULT, PublicSourceType.CODE])
def test_client_sends_document_filters_on_any_search_for_the_service_to_judge(
    source: PublicSourceType,
) -> None:
    # Guard. Proven to fail: gating the document-filter copy in
    # _build_http_search_payload on a document or combined source drops the
    # filters here, failing the first assertion below.
    payload = _build_http_search_payload(
        SearchCallRequest(
            query="manual",
            search_type=source.value,
            top_k=5,
            port=1,
            project_root="/tmp/proj",
            document_filters=DocumentSearchFilters(
                source_path="docs/manual.pdf",
                metadata_filters={"lang": ["en"]},
            ),
        ),
        source,
        freshness_policy="immediate",
        freshness_wait_seconds=None,
    )
    assert payload.get("metadata_filters") == {"lang": ["en"]}
    assert payload.get("source_path") == "docs/manual.pdf"


@pytest.mark.parametrize("code", ["unknown_filter_key", "extractor_prefix_unbounded"])
def test_mcp_raises_a_tool_error_for_a_refused_filter(code: str) -> None:
    with pytest.raises(ValueError, match=rf"^{code}: refused"):
        _validated_search_result({"ok": False, "error": code, "message": "refused"})


@pytest.mark.parametrize(
    "meta",
    [["lang"], ["lang=en", "lang=de"]],
)
def test_cli_refuses_a_malformed_meta_option_with_one_envelope(
    meta: list[str],
) -> None:
    argv = ["search", "manual", "--type", "document", "--json"]
    for assignment in meta:
        argv += ["--meta", assignment]
    result = runner.invoke(app, argv)
    assert result.exit_code == 2
    envelope = json.loads(result.output)
    assert envelope["ok"] is False
    assert envelope["error"] == "invalid_filter_for_search_type"
    assert envelope["filter_kind"] == "document"
