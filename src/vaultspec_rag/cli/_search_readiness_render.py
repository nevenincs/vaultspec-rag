"""Human rendering for canonical search-readiness envelopes."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .._search_state import MAX_SEARCH_EVIDENCE_ITEMS

if TYPE_CHECKING:
    from collections.abc import Callable

_IDENTIFIER_LIMIT = 256
_REMEDIATION_LIMIT = 1_024


def _bounded(value: object, *, limit: int = _IDENTIFIER_LIMIT) -> str | None:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    rendered = str(value)
    if not rendered:
        return None
    return rendered if len(rendered) <= limit else f"{rendered[: limit - 1]}…"


def _generation_details(source: dict[str, object]) -> list[str]:
    raw_generation = source.get("generation")
    if not isinstance(raw_generation, dict):
        return []
    generation = cast("dict[str, object]", raw_generation)
    details: list[str] = []
    for key in (
        "served_generation",
        "served_revision",
        "desired_generation",
        "desired_revision",
    ):
        value = _bounded(generation.get(key))
        if value is not None:
            details.append(f"{key}={value}")
    return details


def _render_source(
    source: dict[str, object],
    rendered_remediation: set[str],
    emit: Callable[[str], None],
) -> None:
    identity = _bounded(source.get("source"))
    details = [
        value
        for key in ("availability", "freshness")
        if isinstance((value := source.get(key)), str) and value
    ]
    reason = _bounded(source.get("reason_code"))
    if reason is not None:
        details.append(f"reason={reason}")
    details.extend(_generation_details(source))
    if identity is not None and details:
        emit(f"  {identity}: {', '.join(details)}")
    raw_evidence = source.get("evidence")
    if isinstance(raw_evidence, list):
        evidence = [
            value
            for item in cast("list[object]", raw_evidence)[:MAX_SEARCH_EVIDENCE_ITEMS]
            if (value := _bounded(item)) is not None
        ]
        if evidence:
            emit(f"    Evidence: {', '.join(evidence)}")
    remediation = source.get("remediation")
    if isinstance(remediation, str) and remediation not in rendered_remediation:
        bounded = _bounded(remediation, limit=_REMEDIATION_LIMIT)
        if bounded is not None:
            emit(f"    Next action: {bounded}")
            rendered_remediation.add(remediation)


def _render_waits(
    source: dict[str, object], remaining: int, emit: Callable[[str], None]
) -> int:
    raw_waits = source.get("waits")
    if not isinstance(raw_waits, list):
        return remaining
    source_id = _bounded(source.get("source"))
    for raw_wait in cast("list[object]", raw_waits):
        if remaining == 0:
            break
        if not isinstance(raw_wait, dict):
            continue
        wait = cast("dict[str, object]", raw_wait)
        cause = _bounded(wait.get("cause"))
        if cause is None:
            continue
        prefix = f"{source_id} " if source_id is not None else ""
        emit(
            f"  Wait {prefix}{cause}: {wait.get('waited_seconds')}s / "
            f"{wait.get('configured_bound_seconds')}s "
            f"({wait.get('remaining_bound_seconds')}s remaining)"
        )
        remaining -= 1
    return remaining


def render_readiness(
    payload: dict[str, object], emit: Callable[[str], None]
) -> set[str]:
    """Render canonical readiness fields without deriving a new verdict."""
    rendered_remediation: set[str] = set()
    raw_readiness = payload.get("readiness")
    if not isinstance(raw_readiness, dict):
        return rendered_remediation
    readiness = cast("dict[str, object]", raw_readiness)
    raw_aggregate = readiness.get("aggregate")
    if isinstance(raw_aggregate, dict):
        aggregate = cast("dict[str, object]", raw_aggregate)
        state = [
            value
            for key in ("availability", "freshness", "absence_authority")
            if isinstance((value := aggregate.get(key)), str) and value
        ]
        if state:
            emit(f"Readiness: {' / '.join(state)}")
    raw_sources = readiness.get("sources")
    if not isinstance(raw_sources, list):
        return rendered_remediation
    remaining = MAX_SEARCH_EVIDENCE_ITEMS
    for raw_source in cast("list[object]", raw_sources)[:MAX_SEARCH_EVIDENCE_ITEMS]:
        if isinstance(raw_source, dict):
            source = cast("dict[str, object]", raw_source)
            _render_source(source, rendered_remediation, emit)
            remaining = _render_waits(source, remaining, emit)
    return rendered_remediation


def render_string_remediation(
    payload: dict[str, object], rendered: set[str], emit: Callable[[str], None]
) -> None:
    """Render the canonical scalar remediation form used by search failures."""
    remediation = payload.get("remediation")
    if isinstance(remediation, str) and remediation not in rendered:
        bounded = _bounded(remediation, limit=_REMEDIATION_LIMIT)
        if bounded is not None:
            emit(f"Next action: {bounded}")
