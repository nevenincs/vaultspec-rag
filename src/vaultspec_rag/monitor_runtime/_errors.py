"""The one exception type everything about the monitor refuses through.

Obtaining the monitor, trusting it and launching it are three steps with one
caller: a start that has to report whatever stopped it as a single outcome.
Each step therefore raises the same type with its own machine-readable code,
so no caller has to know which step was reached to catch the refusal.

What these messages may say is constrained. Getting the monitor is automatic
from end to end, so no message tells anyone to install it, download it,
configure it or point at it: a failure states what went wrong, and that the
next start tries again. Only a refusal of settings the operator set
themselves names those settings.
"""

from __future__ import annotations

__all__ = ["MonitorError"]


class MonitorError(RuntimeError):
    """The monitor cannot be obtained, trusted, or run.

    Attributes:
        error: A stable machine-readable code naming why, for envelopes.
    """

    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error
