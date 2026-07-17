"""Pure result-shaping helpers for the search pipeline.

Module-level, side-effect-free transforms extracted from ``_searcher`` so the
orchestration class stays focused on the stateful pipeline (GPU lock, reranker,
graph cache). Everything here maps raw store rows to ``SearchResult`` objects,
renders display locators, joins vault paths, groups chunks, merges domain
tokens, and records phase timings - none of it touches the GPU, the store, or
searcher state.
"""

from __future__ import annotations

import fnmatch
import time
from typing import TYPE_CHECKING

from ._postprocess import (
    PREFER_CATEGORIES,
    PREFER_SCORE_NUDGE,
    _classify_chunk_type,  # pyright: ignore[reportPrivateUsage]  # intra-package intentional re-export
)

if TYPE_CHECKING:
    from ._models import ParsedQuery, SearchResult


def format_locator(payload: dict[str, object]) -> str | None:
    """Render a preprocess result's split locator into a readable string (#185).

    Combines the ``locator_kind`` with whichever of ``locator_value_int`` /
    ``locator_value_str`` is present, e.g. ``"page 12"`` or ``"sheet Summary"``.
    Returns ``None`` for ordinary code chunks (no locator kind).
    """
    kind = payload.get("locator_kind")
    if not isinstance(kind, str) or not kind:
        return None
    value = locator_component(payload, "locator_value_int", "locator_value_str")
    if value is None:
        return kind
    end = locator_component(payload, "locator_end_int", "locator_end_str")
    if end is not None:
        return f"{kind} {value}-{end}"
    return f"{kind} {value}"


def locator_component(
    payload: dict[str, object], int_key: str, str_key: str
) -> str | None:
    """Return the int or str locator component as a display string, or None."""
    value_int = payload.get(int_key)
    if isinstance(value_int, int) and not isinstance(value_int, bool):
        return str(value_int)
    value_str = payload.get(str_key)
    if isinstance(value_str, str) and value_str:
        return value_str
    return None


def join_doc_path(docs_prefix: str, stored_path: str) -> str:
    """Return a vault doc's path relative to the project root.

    Vault chunks store their path relative to the docs directory
    (e.g. ``research/foo.md``); prepending the docs prefix
    (``.vault``) yields a path that resolves from the project root the
    same way code-result paths do. Idempotent if the prefix is already
    present.
    """
    if not docs_prefix:
        return stored_path
    normalised = stored_path.replace("\\", "/")
    prefix = docs_prefix.replace("\\", "/").rstrip("/")
    if normalised == prefix or normalised.startswith(prefix + "/"):
        return normalised
    return f"{prefix}/{normalised}"


def merge_domain_tokens(
    parsed: ParsedQuery, key: str, explicit: list[str] | None
) -> list[str] | None:
    """Union explicit domain kwargs with comma-split inline query tokens.

    The inline ``exclude:``/``only:``/``include:`` tokens are stored on
    ``parsed.filters`` as comma-joined strings; an explicit kwarg (from the api
    or MCP surface) adds to them. Returns ``None`` when neither is present so
    the policy resolver leaves that axis untouched.
    """
    merged = list(explicit or [])
    token = parsed.filters.get(key)
    if token:
        merged.extend(part for part in token.split(",") if part)
    return merged or None


def group_chunks_by_document(results: list[SearchResult]) -> list[SearchResult]:
    """Collapse chunk-level vault hits to one result per document.

    The vault collection stores one point per document chunk, so a
    single document can occupy several candidate slots. The
    best-scoring chunk represents its document (its snippet is the
    matched passage); duplicates drop. Order follows the surviving
    scores, descending.
    """
    best: dict[str, SearchResult] = {}
    for result in results:
        current = best.get(result.id)
        if current is None or result.score > current.score:
            best[result.id] = result
    return sorted(best.values(), key=lambda r: r.score, reverse=True)


def record_seconds(
    timings: dict[str, float] | None,
    key: str,
    started: float,
) -> None:
    if timings is not None:
        timings[key] = time.perf_counter() - started


def add_seconds(
    timings: dict[str, float] | None,
    key: str,
    seconds: float,
) -> None:
    if timings is not None:
        timings[key] = timings.get(key, 0.0) + seconds


def filter_raw_codebase_results(
    raw_results: list[dict[str, object]],
    include_norm: list[str],
    exclude_norm: list[str],
) -> list[dict[str, object]]:
    if not include_norm and not exclude_norm:
        return raw_results
    filtered: list[dict[str, object]] = []
    for r in raw_results:
        path_value = str(r.get("path", ""))
        if include_norm and not any(
            fnmatch.fnmatch(path_value, pat) for pat in include_norm
        ):
            continue
        if exclude_norm and any(
            fnmatch.fnmatch(path_value, pat) for pat in exclude_norm
        ):
            continue
        filtered.append(r)
    return filtered


def map_codebase_results(
    raw_results: list[dict[str, object]],
) -> list[SearchResult]:
    from ._models import SearchResult

    results: list[SearchResult] = []
    for r in raw_results:
        raw_score = r.get("_relevance_score", 0.0)
        score = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0
        r_id = str(r["id"])
        r_path = str(r["path"])
        content = str(r.get("content", ""))
        snippet = content[:200].strip()
        language = str(r.get("language", ""))
        line_start = r.get("line_start")
        line_end = r.get("line_end")
        node_type = r.get("node_type")
        function_name = r.get("function_name")
        class_name = r.get("class_name")
        source_path = r.get("source_path")
        preprocessor_id = r.get("preprocessor_id")
        anchor = r.get("anchor")
        results.append(
            SearchResult(
                id=r_id,
                path=r_path,
                title=r_path,
                score=score,
                snippet=snippet,
                source="codebase",
                language=language,
                line_start=int(line_start) if isinstance(line_start, int) else None,
                line_end=int(line_end) if isinstance(line_end, int) else None,
                node_type=str(node_type) if node_type is not None else None,
                function_name=(
                    str(function_name) if function_name is not None else None
                ),
                class_name=str(class_name) if class_name is not None else None,
                source_path=str(source_path) if source_path is not None else None,
                preprocessor_id=(
                    str(preprocessor_id) if preprocessor_id is not None else None
                ),
                anchor=str(anchor) if anchor is not None else None,
                locator=format_locator(r),
                rerank_text=content or None,
            ),
        )
    return results


def apply_prefer_nudge(results: list[SearchResult], prefer: str | None) -> None:
    if prefer not in PREFER_CATEGORIES:
        return
    for r in results:
        category = _classify_chunk_type(r.path)
        if category == prefer:
            r.score += PREFER_SCORE_NUDGE
        else:
            r.score -= PREFER_SCORE_NUDGE
    results.sort(key=lambda r: r.score, reverse=True)
