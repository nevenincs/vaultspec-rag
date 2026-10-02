"""Transport-neutral structured failures shared by service adapters."""

from __future__ import annotations


def error_payload(error: str, message: str) -> dict[str, object]:
    """Build the common failure envelope without choosing a transport status."""
    return {"ok": False, "error": error, "message": message}
