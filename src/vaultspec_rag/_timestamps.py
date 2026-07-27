"""Reading the ISO-8601 timestamps this project writes into its own files.

The writing side has been canonical for a while - one helper stamps both
discovery fields so their format and precision cannot drift. The reading side
had not caught up. Five sites parsed a stamp back, and among them the same
function had grown twice under the same name in two modules, one of which
imports the other.

Two rules were in play and only one was written down. Four readers treated a
stamp carrying no offset as UTC; the fifth handed it to ``astimezone``, which
reads a naive value as LOCAL time. The same string therefore named two
different instants depending on which reader saw it, and the gap between them
is exactly the machine's offset from UTC. Nothing failed, because the canonical
writer always emits an offset - the divergence only surfaces on a hand-edited
or pre-upgrade file, which is precisely when an operator is already debugging
something else.

UTC is the rule here, because it is the one the writer's own format implies and
the one four of the five readers already used.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["age_seconds", "parse_iso_timestamp"]

logger = logging.getLogger(__name__)


def parse_iso_timestamp(raw: object, *, field: str = "timestamp") -> datetime | None:
    """Return *raw* as an aware datetime, or ``None`` when it is not one.

    A value carrying no offset is read as UTC. Anything that is not a
    non-empty string, and anything the parser rejects, is ``None`` - callers
    read that as "no timestamp", never as "now" or "epoch".

    *field* names the thing being parsed so the debug line an operator reads
    says which stamp was unparseable rather than only that one was.

    A ``Z`` suffix needs no pre-substitution: the parser has accepted it since
    3.11, and this package requires later than that. One caller still carried
    the ``replace("Z", "+00:00")`` that used to be necessary.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        logger.debug("%s %r unparseable: %s", field, raw, exc)
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def age_seconds(payload: Mapping[str, object], field: str) -> float | None:
    """Return how many seconds ago *payload*'s *field* names, or ``None``.

    ``None`` covers every reason the age is unknown - the field absent (a
    record written before it existed, or a daemon that died before its first
    tick), or a value that will not parse. A caller deciding staleness treats
    that as "no data" rather than "fresh", because a missing heartbeat is
    exactly the shape a killed process leaves behind.
    """
    parsed = parse_iso_timestamp(payload.get(field), field=field)
    if parsed is None:
        return None
    return (datetime.now(UTC) - parsed).total_seconds()
