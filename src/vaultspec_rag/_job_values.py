"""Narrowing untyped JSON values into the shapes the job surfaces render.

Every reader of a job record faces the same problem: the value came off a wire
or a file, so it is ``object``, and the renderer needs a number, a mapping or a
string. These do that one narrowing each, and answer ``None`` where a value is
absent rather than substituting a zero - an absent measurement and a measured
zero are different facts, and a surface that conflates them reports work that
never happened.

They sit at the bottom of the job import graph on purpose: everything reads
them and they read nothing.
"""

from __future__ import annotations

import math
from typing import cast

__all__ = ["count", "flag", "mapping", "measurement", "text"]


def count(value: object) -> int | None:
    """Read one published value as a whole, non-negative count.

    The counted-work half of the reader pair :func:`measurement` completes,
    and it carries the same contract: a count is a published *quantity*, so
    ``bool`` and a negative are both malformed rather than readings. A
    ``float`` is refused outright rather than truncated, because a
    fractional count is a malformed reading and not a rounding question - a
    cap of ``3.7`` is a broken field, not "3".
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def measurement(value: object) -> float | None:
    """Read one published value as a NON-NEGATIVE measured quantity.

    The one reader every surface uses for a numeric field the service may
    not have measured: the evidence blocks here, the jobs presentation, the
    status pane, and the route projection all narrow the same way, so a
    value one of them would refuse can never read as a number in another.

    The contract is deliberately narrower than "a number", and the boundary
    is worth naming because this reader is general enough to reach for
    anywhere. It reads a quantity the service *measured and published*: a
    percentage, a size, an age, a duration, a rate, a tally, a timestamp.
    Every such quantity is non-negative, so a negative is a corrupt field
    and is refused. Do NOT route a signed figure through here - a delta
    between two readings, a clock offset, a drift, or anything else whose
    sign carries meaning - because this reader would silently discard the
    negative half of its range.

    A quantity *derived* by subtracting two of these readings is a separate
    case and is not this reader's job: it can legitimately come out negative
    from clock skew or an out-of-order stamp, and the treatment there is to
    clamp at zero, not to refuse. :func:`._routes_jobs._age_seconds` is that
    pattern.

    ``nan`` and the infinities are refused too, and they are the one shape
    that fails silently rather than loudly. A ``nan`` compares ``False``
    against every threshold, so a ``nan`` rate ratio would read as "not
    collapsed" and quietly suppress a degradation verdict instead of
    reporting an unreadable field; an infinity reaches the operator
    formatters, which convert to ``int`` and raise. JSON has no syntax for
    either, but Python's ``json`` both emits and accepts them by default, so
    a persisted job record can carry one.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return numeric


def mapping(value: object) -> dict[str, object]:
    """Read one published value as a sub-mapping, or an empty one.

    The structural member of the reader family: a job record arrives as an
    untyped mapping decoded from persisted JSON, and reaching a field nested
    inside it means narrowing the container first. Compose it with the
    scalar readers - ``measurement(mapping(record.get("progress")).get(key))``
    - so a malformed container reads as absent rather than raising.

    An absent or non-mapping value reads as an empty mapping rather than
    ``None``, so a caller can always ``.get`` the field it came for. A
    caller that has to tell "absent" from "present but empty" needs its own
    reader; this one deliberately cannot express that difference.
    """
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def flag(value: object) -> bool | None:
    """Read one published value as a signal; anything else is unreported.

    The three-state reader beside :func:`measurement` and :func:`count`:
    yes, no, and never reported stay distinct, so a signal the service
    never sent can never read as a denial.
    """
    return value if isinstance(value, bool) else None


def text(value: object) -> str:
    """Read one published value as a string, or as the empty string.

    The two-state member of the family, and deliberately so: an identity, a
    cause or a command that the service did not publish as a string cannot
    be shown, addressed or compared, and every caller already treats the
    empty string as that. Distinguishing "absent" from "published empty"
    would need a caller's own reader; nothing here needs the difference.

    Never reach for this to render a number. ``str(value)`` on a raw field
    would print ``True`` as a value; the numeric readers exist to refuse it.
    """
    return value if isinstance(value, str) else ""
