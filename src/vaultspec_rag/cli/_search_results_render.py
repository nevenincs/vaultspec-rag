"""Render a search answer for the operator, whichever process produced it.

The service and the in-process search hand the renderer the same shape, so the
warnings that qualify a result page - index shortfalls, partial domain failures,
readiness remediation - are written once here and read by both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import typer

import vaultspec_rag.cli as _cli

from .._source_types import PublicSourceType
from ._render import (
    MUTED,
    WARN,
    _display_search_results,
    _display_service_error,
    _emit_json,
    _plain,
    _styled,
)
from ._search_readiness_render import (
    render_drift_audits as _render_drift_audits_payload,
)
from ._search_readiness_render import (
    render_readiness as _render_readiness_payload,
)
from ._search_readiness_render import (
    render_string_remediation as _render_string_remediation_payload,
)

if TYPE_CHECKING:
    import pathlib

FILTER_ADVISORY = (
    "Filter with --type code --language python, --type vault --doc-type adr, "
    "or --type document; verify source/doc_type in --json (all: --type combined)."
)


@dataclass(frozen=True, slots=True)
class ServiceSearchRenderRequest:
    """Presentation inputs shared by every service-search outcome shape."""

    query: str
    search_type: str
    json_mode: bool
    show_scores: bool
    target: pathlib.Path | None = None


def handle_service_results(
    service_results: dict[str, object],
    request: ServiceSearchRenderRequest,
) -> None:
    if not request.json_mode:
        _render_drift_audits_payload(service_results, _plain)
    if service_results.get("ok") is False:
        _display_service_error(
            service_results,
            json_mode=request.json_mode,
            command="search",
        )
        if not request.json_mode:
            rendered_remediation = _render_readiness(service_results)
            _render_string_remediation(service_results, rendered_remediation)
        raise typer.Exit(code=1)
    if "results" in service_results:
        _handle_service_success(
            service_results,
            request,
        )
        return
    # The transport rejects non-dicts and empty/malformed dictionaries. Keep a
    # final dictionary-shape defense for direct callers of this private seam.
    _display_service_error(
        service_results,
        json_mode=request.json_mode,
        command="search",
    )
    raise typer.Exit(code=1)


def _handle_service_success(
    payload: dict[str, object],
    request: ServiceSearchRenderRequest,
) -> None:
    raw_results = payload.get("results")
    results = (
        list(cast("list[dict[str, object]]", raw_results))
        if isinstance(raw_results, list)
        else []
    )
    if request.json_mode:
        data = dict(payload)
        data["query"] = request.query
        data["search_type"] = request.search_type
        data["via"] = "service"
        data["advisory"] = FILTER_ADVISORY
        _emit_json(True, "search", data=data)
        return
    if not results:
        _render_empty_service_results(payload, request.query, request.search_type)
        _render_readiness(payload)
        render_shortfall_warnings(payload)
        render_partial_domain_failures(payload)
        return
    _display_search_results(
        results,
        request.search_type,
        via="service",
        show_scores=request.show_scores,
        root=request.target,
    )
    _render_readiness(payload, muted=True)
    render_shortfall_warnings(payload)
    render_partial_domain_failures(payload)


def muted_line(text: str) -> None:
    _styled((text, MUTED), soft_wrap=True)


def _render_readiness(payload: dict[str, object], *, muted: bool = False) -> set[str]:
    """Render the readiness block; muted when it trails results it qualifies."""
    return _render_readiness_payload(payload, muted_line if muted else _plain)


def _render_string_remediation(payload: dict[str, object], rendered: set[str]) -> None:
    _render_string_remediation_payload(payload, rendered, _plain)


def render_shortfall_warnings(payload: dict[str, object]) -> None:
    """Warn that the index answering this search is demonstrably incomplete.

    Walks whatever the shared reader found, so the point-count and file-count
    deficits cannot diverge on this surface: adding a third kind reaches the
    operator here without touching this function.
    """
    from .._index_breadth import (
        SHORTFALL_CONSEQUENCE,
        SHORTFALL_REMEDIATION,
        shortfall_warnings,
    )

    index_state = payload.get("index_state")
    if not isinstance(index_state, dict):
        return
    for warning in shortfall_warnings(cast("dict[str, object]", index_state)):
        _styled(
            ("Warning:", WARN),
            f" {warning.deficit}; {warning.missing}.",
            soft_wrap=True,
        )
        _plain(f"  {warning.why}, so {SHORTFALL_CONSEQUENCE}.", soft_wrap=True)
        _plain(f"  Next action: {SHORTFALL_REMEDIATION}")


def render_partial_domain_failures(payload: dict[str, object]) -> None:
    """Render visible failures from a canonical combined-search envelope."""
    if payload.get("partial") is not True and payload.get("ok") is not False:
        return
    raw_domains = payload.get("domains")
    if not isinstance(raw_domains, dict):
        return
    domains = cast("dict[object, object]", raw_domains)
    for source in PublicSourceType:
        if source is PublicSourceType.COMBINED:
            continue
        raw = domains.get(source.value)
        if not isinstance(raw, dict):
            continue
        outcome = cast("dict[str, object]", raw)
        if outcome.get("ok") is False:
            _plain(
                f"{search_type_result_label(source.value).capitalize()} search "
                f"failed ({outcome.get('error_kind')}): {outcome.get('detail')}"
            )


def _render_empty_service_results(
    payload: dict[str, object],
    query: str,
    search_type: str,
) -> None:
    _plain(f"No {search_type_result_label(search_type)} results found for: {query}")
    remediation: object = None
    empty = payload.get("empty")
    if isinstance(empty, dict):
        empty_map = cast("dict[str, object]", empty)
        message = str(empty_map.get("message", "No matching indexed items found."))
        _plain(f"Why: {message}")
        remediation = empty_map.get("remediation")
    index_state = payload.get("index_state")
    if isinstance(index_state, dict):
        _render_empty_index_state(cast("dict[str, object]", index_state), search_type)
    if isinstance(remediation, list) and remediation:
        remediation_items = cast("list[object]", remediation)
        _cli.console.print("Next actions:")
        for item in remediation_items:
            _cli.console.print(f"  - {item}")


def search_type_result_label(search_type: str) -> str:
    if search_type == "code":
        return "source code"
    if search_type == "vault":
        return "vault document"
    if search_type == "document":
        return "document"
    if search_type == "combined":
        return "combined"
    return search_type.replace("_", " ")


def search_type_count_label(search_type: str) -> str:
    if search_type == "code":
        return "source code sections"
    if search_type == "vault":
        return "vault documents"
    if search_type == "document":
        return "document sections"
    if search_type == "combined":
        return "combined results"
    return f"{search_type.replace('_', ' ')} items"


def _render_empty_index_state(
    index_state: dict[str, object],
    search_type: str,
) -> None:
    source = str(index_state.get("source") or search_type)
    indexed = index_state.get("indexed_count", "?")
    _plain(f"Indexed {search_type_count_label(source)}: {indexed}.")
    requested = str(index_state.get("requested_target_root", "")).strip()
    indexed_target = str(index_state.get("indexed_target_root", "")).strip()
    if not requested or not indexed_target:
        return
    if index_state.get("target_matches") is False and requested != indexed_target:
        _plain("Project mismatch: requested project differs from indexed project.")
        _plain(f"Requested project: {requested}", soft_wrap=True)
        _plain(f"Indexed project: {indexed_target}", soft_wrap=True)
        return
    _plain(f"Project: {requested}", soft_wrap=True)
