"""Pure presentation helpers shared across the ``server`` CLI renderers.

Stateless number, size, and path formatting used by more than one lifecycle
renderer. ``_counted_unit`` is the singular/plural rule every operator-facing
count goes through, and it lives here once: the status, jobs, index, projects,
watcher, and install renderers all import it back rather than restating it.

Restating it is the failure mode this module exists to prevent - the copies
drift silently, because a pluralisation bug reads as a typo rather than as a
defect, and no test compares two renderers' wording against each other.

``_duration_phrase`` is the same arrangement for the whole-second cascade an
ELAPSED duration renders: seconds, then minutes, then hours, each tier naming
its largest one or two units. Both elapsed surfaces route through it, and the
two places they legitimately differ - whether the cascade continues past hours
into days, and what a sub-second or missing value reads as - stay with the
callers as explicit arguments and guard clauses rather than as a second copy
of the cascade.

Delay formatting is deliberately NOT centralised here, and must not be folded
into ``_duration_phrase``. The vocabularies differ by subject and are not
interchangeable: an elapsed duration reports ``less than 1 second`` and counts
whole seconds, while a configured delay (the watcher renderers) reports
``immediately``, carries a millisecond tier, and keeps a fractional
``1.5 seconds``. Collapsing those would silently restate one surface's
contract in the other's words.
"""

from __future__ import annotations

__all__ = [
    "NOT_REPORTED",
    "_counted_unit",
    "_duration_phrase",
    "_format_mb",
    "_format_milliseconds",
    "_format_seconds",
    "_path_label",
    "_project_name",
]

#: What an operator row says when the service did not report the field it
#: describes. One definition for the same reason ``_counted_unit`` is one: the
#: phrase is asserted verbatim by tests and read across adjacent rows, so a copy
#: that drifts reads as two different conditions when it is one.
NOT_REPORTED = "not reported by service"


def _counted_unit(value: int, singular: str, plural: str | None = None) -> str:
    unit = singular if value == 1 else plural or f"{singular}s"
    return f"{value} {unit}"


def _unit_pair(major: int, major_unit: str, minor: int, minor_unit: str) -> str:
    """Render the larger unit, appending the smaller only when it is non-zero."""
    if minor:
        return f"{_counted_unit(major, major_unit)} {_counted_unit(minor, minor_unit)}"
    return _counted_unit(major, major_unit)


def _duration_phrase(total_seconds: int, *, days: bool) -> str:
    """Render a whole-second duration as its largest one or two units.

    ``days`` selects whether the cascade continues past hours, and the two
    operator surfaces genuinely differ there: the service-status rows roll 48
    hours into "2 days", while the generic duration rows report "48 hours".
    That is visible in operator text and asserted by tests, so it is a required
    argument rather than a default either caller could drift onto silently.

    Sub-second and miss-value handling stay with the callers, which also
    disagree: one reports "less than 1 second" where the other floors to
    "0 seconds", and their miss sentinels differ.
    """
    if total_seconds < 60:
        return _counted_unit(total_seconds, "second")
    minutes, seconds = divmod(total_seconds, 60)
    if minutes < 60:
        return _unit_pair(minutes, "minute", seconds, "second")
    hours, minutes = divmod(minutes, 60)
    if not days or hours < 24:
        return _unit_pair(hours, "hour", minutes, "minute")
    day_count, hours = divmod(hours, 24)
    return _unit_pair(day_count, "day", hours, "hour")


def _format_seconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported"
    raw_seconds = max(0.0, float(raw))
    if raw_seconds < 1:
        return "less than 1 second"
    return _duration_phrase(int(raw_seconds), days=False)


def _compact_duration(raw: object) -> str:
    """Render a duration for a fixed-width column, largest two units.

    The prose phrase is unusable in a table: "3 minutes 20 seconds" is wider
    than the column that has to hold it, and its width changes with the value.
    This is the same cascade in a bounded form, and it is a display choice
    rather than a second opinion about the duration.

    Returns an em dash for a missing measure, so an absent estimate reads as
    absent instead of as zero.
    """
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        return "—"
    total = int(max(0.0, float(raw)))
    if total < 60:
        return f"{total}s"
    minutes, seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h"


def _format_milliseconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported"
    return _format_seconds(float(raw) / 1000.0)


def _format_mb(raw: object) -> str:
    """Render a mebibyte measurement in operator units.

    The value arrives already divided by 1024**2, so it is mebibytes. Labelling
    it "MB" understated every figure it printed - by ~5% at this scale and ~7%
    once a reader converts to gigabytes - which is the mislabel the shared byte
    vocabulary exists to prevent. Routed through that vocabulary rather than
    given a corrected suffix here, so there is one renderer for a size in this
    CLI and a large value promotes to the unit a reader would have reached for
    anyway.
    """
    if not isinstance(raw, int | float):
        return "not reported"
    from .._units import human_bytes, mib_to_bytes

    return human_bytes(mib_to_bytes(float(raw)))


def _project_name(root: object) -> str:
    """Name a project by the last segment of its root path.

    Separator-agnostic because a root reaches the CLI as whatever the service
    recorded, which on Windows is backslash-separated even though the same
    payload read on POSIX is not. A root that ends in a separator, or has no
    segment to name, falls back to the full value rather than an empty label.
    """
    value = str(root)
    parts = value.replace("\\", "/").rstrip("/").split("/")
    return parts[-1] if parts and parts[-1] else value


def _path_label(raw: object) -> str:
    value = str(raw or "")
    if not value:
        return "path not reported"
    parts = value.replace("\\", "/").rstrip("/").split("/")
    if ".venv" in parts:
        return "/".join(parts[parts.index(".venv") :])
    if len(parts) > 3:
        return ".../" + "/".join(parts[-3:])
    return value
