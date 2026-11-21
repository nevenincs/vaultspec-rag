"""Refuse a search option the operator spelled wrongly, before any search runs.

Each refusal converges on one wording, one error code and one exit status of 2,
whichever surface noticed it, and emits one JSON envelope in JSON mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from .._source_types import PublicSourceType, SourceTypeParseError, parse_source_type
from ._render import _emit_json_error_and_exit, _plain

if TYPE_CHECKING:
    from typing import NoReturn

    from ..search import InvalidFilterForSearchTypeError, InvalidPreferValueError


def fail_invalid_filter(
    exc: InvalidFilterForSearchTypeError, json_mode: bool
) -> NoReturn:
    """Render one refused filter and exit 2, with the refusal's own code."""
    msg = str(exc)
    if json_mode:
        _emit_json_error_and_exit(
            "search",
            exc.error_code,
            msg,
            2,
            filter_kind=exc.filter_kind,
            offending=exc.offending_filters,
        )
    _plain(f"Error: {msg}")
    raise typer.Exit(code=2) from None


def metadata_filters_option(
    assignments: list[str] | None, *, json_mode: bool
) -> dict[str, list[str]] | None:
    """Read repeated ``--meta key=v1,v2`` options into the metadata mapping."""
    from ..search import InvalidFilterForSearchTypeError
    from ..search._validation import metadata_filters_from_assignments

    try:
        return metadata_filters_from_assignments(assignments or [])
    except InvalidFilterForSearchTypeError as exc:
        fail_invalid_filter(exc, json_mode)


def fail_invalid_prefer(exc: InvalidPreferValueError, json_mode: bool) -> NoReturn:
    """Render one refusal for an unsupported ``--prefer`` value and exit 2.

    Both refusal points - the long-name normaliser below and the search
    validator's exception - converge here, so the operator sees one wording,
    one error code and one exit status whichever of the two fired.
    """
    msg = str(exc)
    if json_mode:
        _emit_json_error_and_exit(
            "search",
            "invalid_prefer_value",
            msg,
            2,
            value=exc.prefer_value,
        )
    _plain(f"Error: {msg}")
    raise typer.Exit(code=2) from None


def search_prefer_filter(prefer: str | None, *, json_mode: bool = False) -> str | None:
    from ..search import InvalidPreferValueError

    if prefer is None:
        return None
    values = {
        "production": "prod",
        "tests": "tests",
        "documentation": "docs",
    }
    normalized = prefer.strip().lower()
    if normalized in values:
        return values[normalized]
    fail_invalid_prefer(InvalidPreferValueError(prefer), json_mode)


def validate_search_type(search_type: str, *, json_mode: bool) -> PublicSourceType:
    try:
        return parse_source_type(search_type, allow_aliases=True)
    except SourceTypeParseError as exc:
        if json_mode:
            _emit_json_error_and_exit(
                "search",
                exc.error_kind,
                str(exc),
                2,
                **exc.as_payload(),
            )
        _plain(f"Error: {exc}")
        raise typer.Exit(code=2) from None
