"""Shared bounds and ordering for service operator list projections."""

from __future__ import annotations

from typing import Literal

DEFAULT_OPERATOR_LIST_LIMIT = 200
MAX_OPERATOR_LIST_LIMIT = 5_000


def list_offset(raw: object = None) -> int:
    """Normalize an offset without allowing negative indexing."""
    if isinstance(raw, bool) or not isinstance(raw, str | int):
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def list_limit(raw: object = None) -> int:
    """Keep operator pages finite, including explicitly empty pages."""
    if isinstance(raw, bool) or not isinstance(raw, str | int):
        return DEFAULT_OPERATOR_LIST_LIMIT
    try:
        return min(MAX_OPERATOR_LIST_LIMIT, max(0, int(raw)))
    except ValueError:
        return DEFAULT_OPERATOR_LIST_LIMIT


def list_order(
    raw: str | None, *, default: Literal["asc", "desc"] = "desc"
) -> Literal["asc", "desc"]:
    """Return one supported display order."""
    normalized = raw.strip().lower() if raw else default
    if normalized == "asc":
        return "asc"
    if normalized == "desc":
        return "desc"
    return default
