"""Reading the service's replies to the jobs watch.

Each function turns one raw payload into either the value the watch renders,
or the error string shown in its place. Nothing here raises: a watch that dies
on a malformed reply tells an operator less than one that says which lane went
quiet and why.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..jobs import count, mapping
from ..service_quiesce import QUIESCE_ENVELOPE_FIELDS
from ._jobs_tui_cells import _search_id
from ._jobs_tui_constants import (
    _GONE_CODES,
    _PLAIN_ACTIONS,
    _STATE_ACTIONS,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


def _canonical_quiesce_block(raw: object) -> object | None:
    """Accept only the complete controller-owned quiesce vocabulary.

    The TUI is an observer: it neither repairs an incomplete block nor derives
    a lifecycle state from one of its fields. A daemon that omits or changes
    the canonical shape is therefore shown as unavailable rather than safe.
    """
    block = mapping(raw)
    if frozenset(block) != QUIESCE_ENVELOPE_FIELDS:
        return None
    return block


def _fetch_error(result: dict[str, object] | None) -> str | None:
    """Return why a fetch cannot be believed, or ``None`` when it can.

    The transport does not raise on a service that answers badly: a timeout
    comes back as an ``ok: false`` envelope and a non-200 body is returned as
    it stands. Neither carries a ``jobs`` key, so reading the payload without
    checking would paint a wedged, erroring or unauthenticated daemon as "no
    jobs, refreshed just now" - a confident, current-looking, entirely false
    frame, and with a thirty-second administrative timeout it is the *normal*
    rendering of a hung service.
    """
    if result is None:
        return "service not reachable"
    if result.get("ok") is False:
        message = result.get("message")
        if isinstance(message, str) and message:
            return message
        error = result.get("error")
        return f"service error: {error}" if error else "the service reported an error"
    if not isinstance(result.get("jobs"), list):
        return "the service did not return a job list"
    return None


def _search_activity_error(result: dict[str, object] | None) -> str | None:
    """Return why an activity response cannot be rendered truthfully."""
    if result is None:
        return "served-search activity unavailable: service not reachable"
    if result.get("ok") is False:
        message = result.get("message")
        return (
            f"served-search activity unavailable: {message}"
            if isinstance(message, str) and message
            else "served-search activity unavailable: service reported an error"
        )
    return _search_activity_payload_error(result)


def _search_activity_payload_error(result: dict[str, object]) -> str | None:
    """Validate the bounded active/recent response envelope."""
    active = result.get("active")
    recent = result.get("recent")
    counts = result.get("counts")
    returned = result.get("returned")
    filters = result.get("filters")
    if not isinstance(active, list) or not isinstance(recent, list):
        return "served-search activity unavailable: invalid record lists"
    if not isinstance(counts, dict) or not isinstance(filters, dict):
        return "served-search activity unavailable: invalid summary"
    if count(returned) is None:
        return "served-search activity unavailable: invalid returned count"
    for name in ("active", "recent", "total"):
        if count(cast("dict[str, object]", counts).get(name)) is None:
            return "served-search activity unavailable: invalid counts"
    return _search_activity_records_error(
        cast("list[object]", active), cast("list[object]", recent)
    )


def _search_activity_records_error(
    active: list[object], recent: list[object]
) -> str | None:
    """Validate record identity, lane, and query privacy invariants."""
    seen: set[str] = set()
    for records, state in ((active, "active"), (recent, "terminal")):
        for record in records:
            if not isinstance(record, dict):
                return "served-search activity unavailable: invalid record"
            entry = cast("dict[str, object]", record)
            request_id = _search_id(entry)
            # A record carries either the query or the service's own redaction
            # signal, never neither and never both. Requiring the text outright
            # made a supported service mode read as a broken service: the
            # serializer omits `query` and sets `query_redacted` whenever it is
            # asked not to disclose it, and this lane blanked entirely rather
            # than degrading to redacted rows.
            disclosed = isinstance(entry.get("query"), str)
            redacted = entry.get("query_redacted") is True
            if (
                not request_id
                or request_id in seen
                or entry.get("state") != state
                or disclosed == redacted
            ):
                return "served-search activity unavailable: invalid record"
            seen.add(request_id)
    return None


def _search_records(raw: object, state: str) -> list[dict[str, object]]:
    """Narrow a validated activity lane to production records.

    Callers only reach here once ``_search_activity_error`` has returned
    None, which means ``_search_activity_payload_error`` already confirmed
    *raw* is a list.
    """
    return [
        cast("dict[str, object]", record)
        for record in cast("list[object]", raw)
        if isinstance(record, dict)
        and cast("dict[str, object]", record).get("state") == state
    ]


def _is_gone(result: dict[str, object]) -> bool:
    """Report whether the service says the job the control named is absent."""
    return any(
        isinstance(value, str) and value in _GONE_CODES
        for value in (result.get("code"), result.get("error"))
    )


def _action_capability(action: str) -> str | None:
    """Map a binding action name to the capability flag that permits it."""
    name = action.removeprefix("job_")
    if name in _STATE_ACTIONS:
        return _STATE_ACTIONS[name][0]
    return _PLAIN_ACTIONS.get(name)


def _log_lines(result: dict[str, object]) -> Iterable[str]:
    """Yield raw log lines from a managed-log payload, group order preserved."""
    groups = result.get("groups")
    if not isinstance(groups, list):
        return []
    lines: list[str] = []
    for group in cast("list[object]", groups):
        if not isinstance(group, dict):
            continue
        raw = cast("dict[str, object]", group).get("lines")
        if isinstance(raw, list):
            lines.extend(str(line) for line in cast("list[object]", raw))
    return lines or ["No log lines matched this job."]
