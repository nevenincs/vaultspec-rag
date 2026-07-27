"""Shared predicates for narrowing untyped JSON-decoded field values.

Each predicate narrows one `object` to a concrete type and raises whatever
exception the caller's `on_invalid` factory constructs, so callers keep their
own exception type and message while sharing the narrowing logic.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable


def required_str(
    value: object, *, allow_empty: bool = False, on_invalid: Callable[[], BaseException]
) -> str:
    """Narrow one required string field."""
    if not isinstance(value, str) or (not allow_empty and not value):
        raise on_invalid()
    return value


def optional_str(
    value: object, *, on_invalid: Callable[[], BaseException]
) -> str | None:
    """Narrow one optional string field, allowing empty but not `None`-as-empty."""
    if value is None:
        return None
    return required_str(value, allow_empty=True, on_invalid=on_invalid)


def required_int(
    value: object,
    *,
    minimum: int | None = None,
    on_invalid: Callable[[], BaseException],
) -> int:
    """Narrow one required non-boolean integer field, floored at `minimum` if given."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise on_invalid()
    if minimum is not None and value < minimum:
        raise on_invalid()
    return value


def optional_int(
    value: object,
    *,
    minimum: int | None = None,
    on_invalid: Callable[[], BaseException],
) -> int | None:
    """Narrow one optional integer field."""
    if value is None:
        return None
    return required_int(value, minimum=minimum, on_invalid=on_invalid)


def required_bool(value: object, *, on_invalid: Callable[[], BaseException]) -> bool:
    """Narrow one required boolean field."""
    if not isinstance(value, bool):
        raise on_invalid()
    return value


def required_float(
    value: object,
    *,
    on_invalid: Callable[[], BaseException],
    on_not_finite: Callable[[], BaseException] | None = None,
) -> float:
    """Narrow one required finite numeric field.

    `on_not_finite` lets a caller raise a distinct exception for a non-finite
    value than for a wrong-shaped one; it defaults to `on_invalid`.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise on_invalid()
    resolved = float(value)
    if not math.isfinite(resolved):
        raise (on_not_finite or on_invalid)()
    return resolved


def optional_float(
    value: object,
    *,
    on_invalid: Callable[[], BaseException],
    on_not_finite: Callable[[], BaseException] | None = None,
) -> float | None:
    """Narrow one optional finite numeric field."""
    if value is None:
        return None
    return required_float(value, on_invalid=on_invalid, on_not_finite=on_not_finite)


def required_mapping(
    value: object, *, on_invalid: Callable[[], BaseException]
) -> dict[str, object]:
    """Narrow one required JSON object to a string-keyed mapping."""
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in cast("dict[object, object]", value)
    ):
        raise on_invalid()
    return cast("dict[str, object]", value)
