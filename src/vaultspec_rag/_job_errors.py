"""Shared job-failure taxonomy, safety outcomes, and remediation.

The silent index-wedge incident surfaced two observability gaps: job failure
reasons were free text that only the CLI renderer knew how to interpret
(a disk-full string match invisible to `/jobs` consumers), and the
"no progress for N minutes" stall signal existed only in human CLI
output. This module is the one shared source for both: the jobs registry
stamps ``error_kind`` from :func:`classify_error_text`, the ``/jobs``
route computes ``stalled`` against :data:`STALL_THRESHOLD_SECONDS`, and
the CLI renders remediation from :func:`remediation` - every adapter
derives the same answer from the same place.

Torch-free, qdrant-free, and CLI-free by design: the CLI service
commands and the maintenance import graph both reach it.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "DEGRADED_THRESHOLD_SECONDS",
    "RATE_COLLAPSE_RATIO",
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

#: A running, non-waiting job with no progress tick and no forward-pass
#: boundary newer than this is reported ``degraded``. Sixty seconds because an
#: uncontended encode slice finishes in single-digit seconds, so a minute
#: without either signal is an order of magnitude beyond any healthy
#: slice-boundary gap - while short legitimate pauses (model load, a store
#: flush, one slow slice) stay well under it, so the verdict does not flap.
#: Deliberately a fifth of the hard stall threshold above: ``degraded`` is the
#: early, cause-attributed tier and ``stalled`` remains the hard verdict.
DEGRADED_THRESHOLD_SECONDS = 60.0

#: A running job whose current throughput has fallen to this fraction of the
#: median it has sustained on the same step is reported ``degraded``, however
#: recent its progress and forward-pass signals are. The recency thresholds
#: above cannot see a collapse that keeps reporting: an encode stage clamped
#: by its own memory ceiling ticks progress and enters forwards continuously
#: while doing a fraction of the work, which is exactly how an order-of-
#: magnitude slowdown read healthy for half an hour.
#:
#: A quarter - a fourfold collapse - because that is the bottom of the range
#: a real collapse produced against its own median, and because the readings
#: either side of it are unambiguous: normal variation between slices moves
#: throughput by tens of percent, not by a factor of four. The baseline it is
#: measured against only exists after the run has reported enough spaced
#: observations to have a median, so a single slow slice cannot move it and
#: the verdict does not flap.
RATE_COLLAPSE_RATIO = 0.25


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
    MIGRATION_REQUIRED = "migration_required"
    ADMISSION_CONFIG_INVALID = "admission_config_invalid"
    EXTRACTION_RETRYABLE = "extract_retryable"
    EXTRACTION_TERMINAL = "extract_terminal"
    DECODE_FAILED = "decode_failed"
    CHUNK_FAILED = "chunk_failed"
    LEDGER_CONTENDED = "ledger_contended"


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
        JobErrorKind.MIGRATION_REQUIRED: (
            "the root policy uses an older schema; add explicit content targets and "
            "extractor versions before retrying"
        ),
        JobErrorKind.ADMISSION_CONFIG_INVALID: (
            "the root policy has invalid or conflicting content ownership; correct "
            "the reported routes before retrying"
        ),
        JobErrorKind.EXTRACTION_RETRYABLE: (
            "the extractor failed transiently; retain the file as pending work and "
            "retry under the service backoff policy"
        ),
        JobErrorKind.EXTRACTION_TERMINAL: (
            "the extractor rejected this input terminally; correct the source, rule, "
            "or extractor version before retrying"
        ),
        JobErrorKind.DECODE_FAILED: (
            "the admitted raw content did not satisfy its strict decoder policy; "
            "correct the content or caller-authored route before retrying"
        ),
        JobErrorKind.CHUNK_FAILED: (
            "the admitted content could not be chunked; inspect the parser failure "
            "and retry after correcting the content or parser support"
        ),
        JobErrorKind.LEDGER_CONTENDED: (
            "durable index bookkeeping stayed locked by concurrent indexing on this "
            "root; storage-confirmed work is intact and the run resumes from its "
            "last checkpoint on retry"
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


# Marker sets are matched case-insensitively against the recorded error
# text. Disk-full covers the raw OS error, qdrant's WAL guard and
# optimizer messages, and the preflight refusal phrasing.
#: Every spelling of "the disk is full" this project has seen, across the
#: OS, the qdrant server, and its WAL. One tuple with two readers: the job
#: record's error_kind, and the store-write retry loop, which treats a full
#: disk as unrecoverable. They diverged while there were two lists - the
#: write path knew two of these five, so three of them were retried until
#: the budget ran out against a disk that was never going to free itself.
DISK_FULL_MARKERS = (
    "no space left",
    "errno 28",
    "wal buffer size exceeds",
    "not enough space available",
    "not enough free disk space",
)

#: The spelling to use when this project RAISES a disk-full error itself,
#: rather than relaying one. It is matched by the tuple above, so a message
#: built from it classifies as ``disk_full`` and reaches the operator with
#: the friendly remediation instead of falling through to ``other``.
DISK_FULL_PHRASE = "No space left on device"
#: SQLite's spellings for a lock another connection already holds. Both are
#: transient by construction - the peer's transaction ends and the next attempt
#: succeeds - so they must not fall through to ``other``, which reads as a
#: terminal fault and discards a generation holding storage-confirmed work.
LOCK_CONTENTION_MARKERS = (
    "database is locked",
    "database table is locked",
)
_TIMEOUT_MARKERS = ("timed out", "timeout")
_UNAVAILABLE_MARKERS = (
    "connection refused",
    "connection reset",
    "connection error",
    "failed to connect",
    "unavailable",
)


#: Legacy free-text marker sets in the order they are tested. Order is part of
#: the contract, not incidental: a message can carry more than one marker, and
#: the first match wins. Kept as a table rather than a chain of branches so
#: adding a condition does not lengthen the classifier.
_MARKER_CLASSIFICATIONS: Final = (
    (DISK_FULL_MARKERS, JobErrorKind.DISK_FULL),
    (LOCK_CONTENTION_MARKERS, JobErrorKind.LEDGER_CONTENDED),
    (_TIMEOUT_MARKERS, JobErrorKind.TIMEOUT),
    (_UNAVAILABLE_MARKERS, JobErrorKind.UNAVAILABLE),
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
    for markers, kind in _MARKER_CLASSIFICATIONS:
        if any(marker in lowered for marker in markers):
            return kind
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
