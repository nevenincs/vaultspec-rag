"""Shared job-failure taxonomy and stall threshold.

The silent index-wedge incident surfaced two observability gaps: job failure
reasons were free text that only the CLI renderer knew how to interpret
(a disk-full string match invisible to `/jobs` consumers), and the
"no progress for N minutes" stall signal existed only in human CLI
output. This module is the one shared source for both: the jobs registry
stamps ``error_kind`` from :func:`classify_error_text`, the ``/jobs``
route computes ``stalled`` against :data:`STALL_THRESHOLD_SECONDS`, and
the CLI renders remediation from :func:`remediation` - every adapter
derives the same answer from the same place
(``service-domain-owns-operability``).

Torch-free, qdrant-free, and CLI-free by design: the CLI service
commands and the maintenance import graph both reach it.
"""

from __future__ import annotations

__all__ = [
    "STALL_THRESHOLD_SECONDS",
    "classify_error_text",
    "remediation",
]

#: A running, non-waiting job whose progress is older than this is
#: reported ``stalled`` on every surface. Matches the CLI's historical
#: advisory threshold.
STALL_THRESHOLD_SECONDS = 300.0

# Marker sets are matched case-insensitively against the recorded error
# text. Disk-full covers the raw OS error, qdrant's WAL guard and
# optimizer messages, and the preflight refusal phrasing.
_DISK_FULL_MARKERS = (
    "no space left",
    "errno 28",
    "wal buffer size exceeds",
    "not enough space available",
    "not enough free disk space",
)
_TIMEOUT_MARKERS = ("timed out", "timeout")
_UNAVAILABLE_MARKERS = (
    "connection refused",
    "connection reset",
    "connection error",
    "failed to connect",
    "unavailable",
)


def classify_error_text(text: str | None) -> str | None:
    """Map a job's recorded error text onto a stable ``error_kind`` token.

    Returns ``disk_full``, ``timeout``, ``unavailable``, or ``other``;
    ``None`` when there is no error text at all.
    """
    if not text:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in _DISK_FULL_MARKERS):
        return "disk_full"
    if any(marker in lowered for marker in _TIMEOUT_MARKERS):
        return "timeout"
    if any(marker in lowered for marker in _UNAVAILABLE_MARKERS):
        return "unavailable"
    return "other"


def remediation(kind: str | None) -> str | None:
    """Operator-facing remediation text for an ``error_kind``, if any."""
    if kind == "disk_full":
        return "not enough disk space; free disk space and retry"
    if kind == "timeout":
        return "the vector store did not respond in time; check qdrant health and retry"
    if kind == "unavailable":
        return "the vector store was unreachable; check the managed qdrant server"
    return None
