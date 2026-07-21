"""Shared job-failure taxonomy, safety outcomes, and remediation.

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

from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "STALL_THRESHOLD_SECONDS",
    "JobError",
    "JobErrorKind",
    "classify_error_text",
    "remediation",
]

#: A running, non-waiting job whose progress is older than this is
#: reported ``stalled`` on every surface. Matches the CLI's historical
#: advisory threshold.
STALL_THRESHOLD_SECONDS = 300.0


class JobErrorKind(StrEnum):
    """Stable service-domain failure and refusal vocabulary.

    Existing write-path classifications remain unchanged.  The additional
    values are the terminal safety and admission outcomes shared by indexing,
    watcher, job, route, health, and CLI adapters.  Keeping them here prevents
    policy consumers from minting near-synonyms that adapters would have to
    interpret independently.
    """

    DISK_FULL = "disk_full"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    OTHER = "other"
    NO_PROGRESS_TIMEOUT = "no_progress_timeout"
    RSS_MEMORY_CEILING = "rss_memory_ceiling"
    CUDA_MEMORY_CEILING = "cuda_memory_ceiling"
    WATCHER_CIRCUIT_OPEN = "watcher_circuit_open"
    PROFILE_REQUIREMENTS_NOT_MET = "profile_requirements_not_met"
    CORPUS_LIMIT_EXCEEDED = "corpus_limit_exceeded"
    DISK_PREFLIGHT_FAILED = "disk_preflight_failed"
    JOB_CAPACITY_EXCEEDED = "job_capacity_exceeded"


_REMEDIATION: Final = MappingProxyType(
    {
        JobErrorKind.DISK_FULL: "not enough disk space; free disk space and retry",
        JobErrorKind.TIMEOUT: (
            "the vector store did not respond in time; check qdrant health and retry"
        ),
        JobErrorKind.UNAVAILABLE: (
            "the vector store was unreachable; check the managed qdrant server"
        ),
        JobErrorKind.NO_PROGRESS_TIMEOUT: (
            "no storage-confirmed progress reached the configured deadline; "
            "check qdrant health and resume from the last checkpoint"
        ),
        JobErrorKind.RSS_MEMORY_CEILING: (
            "process memory reached its safety ceiling; free host memory or reduce "
            "the queue and segment limits, then resume from the last checkpoint"
        ),
        JobErrorKind.CUDA_MEMORY_CEILING: (
            "GPU memory reached its safety ceiling; stop competing GPU work or "
            "reduce the slice limit, then resume from the last checkpoint"
        ),
        JobErrorKind.WATCHER_CIRCUIT_OPEN: (
            "automatic indexing retries are paused; resolve the reported failure "
            "and retry after the circuit delay"
        ),
        JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET: (
            "this host or backend does not meet the selected indexing profile; "
            "select a compatible profile or provide the required resources"
        ),
        JobErrorKind.CORPUS_LIMIT_EXCEEDED: (
            "the corpus exceeds the selected indexing profile; select a "
            "benchmarked larger profile or reduce the indexed scope"
        ),
        JobErrorKind.DISK_PREFLIGHT_FAILED: (
            "the vector store lacks required disk headroom; free disk space, run "
            "vaultspec-rag server storage survey, and retry"
        ),
        JobErrorKind.JOB_CAPACITY_EXCEEDED: (
            "the service is at its nonterminal job limit; wait for a job to finish "
            "before retrying"
        ),
    }
)


class JobError(RuntimeError):
    """Failure carrying a stable kind for deep production policy paths.

    The kind prefixes the exception text because the existing background-job
    boundary persists exception text before classification.  This preserves
    typed identity across that boundary until canonical snapshots consume the
    kind directly.
    """

    error_kind: JobErrorKind
    detail: str

    def __init__(self, error_kind: JobErrorKind, detail: str) -> None:
        if not detail.strip():
            msg = "job error detail must not be empty"
            raise ValueError(msg)
        self.error_kind = error_kind
        self.detail = detail
        super().__init__(f"{error_kind.value}: {detail}")

    @property
    def remediation(self) -> str | None:
        """Return the shared operator action for this failure kind."""
        return remediation(self.error_kind)


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


def classify_error_text(text: str | None) -> JobErrorKind | None:
    """Map a job's recorded error text onto a stable ``error_kind`` token.

    Typed ``JobError`` text is recovered before the legacy marker mapping.
    Existing free-text failures still map to ``disk_full``, ``timeout``,
    ``unavailable``, or ``other``; ``None`` means no error text at all.
    """
    if not text:
        return None
    lowered = text.lower()
    token, separator, _detail = lowered.partition(":")
    if separator:
        try:
            return JobErrorKind(token.strip())
        except ValueError:
            pass
    if any(marker in lowered for marker in _DISK_FULL_MARKERS):
        return JobErrorKind.DISK_FULL
    if any(marker in lowered for marker in _TIMEOUT_MARKERS):
        return JobErrorKind.TIMEOUT
    if any(marker in lowered for marker in _UNAVAILABLE_MARKERS):
        return JobErrorKind.UNAVAILABLE
    return JobErrorKind.OTHER


def remediation(kind: JobErrorKind | str | None) -> str | None:
    """Operator-facing remediation text for an ``error_kind``, if any."""
    if kind is None:
        return None
    try:
        error_kind = JobErrorKind(kind)
    except ValueError:
        return None
    return _REMEDIATION.get(error_kind)
