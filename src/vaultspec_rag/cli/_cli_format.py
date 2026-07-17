"""Pure presentation helpers shared across the ``server`` CLI renderers.

Stateless number, size, and path formatting used by more than one lifecycle
renderer. ``_counted_unit`` was previously duplicated verbatim in the status
and jobs renderers; it lives here once and both import it back.
"""

from __future__ import annotations

__all__ = [
    "_counted_unit",
    "_format_mb",
    "_format_milliseconds",
    "_format_seconds",
    "_path_label",
]


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
    if not isinstance(raw, int | float):
        return "not reported"
    return f"{float(raw):.1f} MB"


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
