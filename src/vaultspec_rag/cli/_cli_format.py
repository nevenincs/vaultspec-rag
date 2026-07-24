"""Pure presentation helpers shared across the ``server`` CLI renderers.

Stateless number, size, and path formatting used by more than one lifecycle
renderer. ``_counted_unit`` is the singular/plural rule every operator-facing
count goes through, and it lives here once: the status, jobs, index, projects,
watcher, and install renderers all import it back rather than restating it.

Restating it is the failure mode this module exists to prevent - the copies
drift silently, because a pluralisation bug reads as a typo rather than as a
defect, and no test compares two renderers' wording against each other.

Duration formatting is deliberately NOT centralised here. The vocabularies
differ by subject and are not interchangeable: an elapsed duration reports
``less than 1 second`` and carries hours, while a configured delay reports
``immediately`` and keeps a fractional ``1.5 seconds``. Collapsing them would
silently restate one surface's contract in the other's words.
"""

from __future__ import annotations

__all__ = [
    "NOT_REPORTED",
    "_counted_unit",
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


def _format_seconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported"
    raw_seconds = max(0.0, float(raw))
    if raw_seconds < 1:
        return "less than 1 second"
    seconds = int(raw_seconds)
    if seconds < 60:
        return _counted_unit(seconds, "second")
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        if rem:
            return f"{_counted_unit(minutes, 'minute')} {_counted_unit(rem, 'second')}"
        return _counted_unit(minutes, "minute")
    hours, minutes = divmod(minutes, 60)
    if minutes:
        return f"{_counted_unit(hours, 'hour')} {_counted_unit(minutes, 'minute')}"
    return _counted_unit(hours, "hour")


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
