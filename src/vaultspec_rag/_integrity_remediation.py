"""Turn a demonstrated index shrink into one supervised repair, conservatively.

The serve-time integrity check classifies a collection against its published
claim on every search, but the evaluator is stateless: each verdict lives for
one response and then is gone. This module is the memory and the hand on the
lever. It remembers which root and domain a search proved shrunken, asks the
job machinery for exactly one non-destructive repair per demonstrated shrink,
and answers the status surface's question - "is a repair in flight for this?" -
without the status path re-counting anything.

The repair is deliberately the weakest verb that heals: an ordinary
incremental index job. The indexer's own evidence check compares the published
breadth against the live store at the start of every incremental run and
escalates to a full failure-safe reconciliation itself when the store falls
short, so the decision of *how* to rebuild stays with the one place that
already owns it. Nothing here drops, cleans, or rebuilds destructively - a
repair that destroyed served data to fix a shrink would be the defect wearing
a cure's name.

Three restraints keep this from becoming a loop:

* Only ``shrunken`` acts. ``unverifiable`` is ignorance, not loss, and acting
  on ignorance would rebuild roots whose only crime is an unreadable sidecar.
  ``consistent`` clears the observation, so a healed collection stops being
  reported the moment a search proves it whole.
* One repair per shrink. While a requested repair's job is active, the job
  manager's equivalent-active deduplication returns the same job for every
  further request, and this registry does not even ask again until a spacing
  interval has passed - so a burst of shrunken searches cannot stack jobs, and
  a repair that keeps failing costs at most one admission per interval while
  the job machinery's own resilience policy owns the retries in between.
* The serving path never waits. Admission runs a policy preflight that scans
  the tree, which has no business inside a search request, so the enqueue runs
  on a short-lived background thread and the search returns with whatever job
  id is already known.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ._index_integrity import VERDICT_CONSISTENT, VERDICT_SHRUNKEN

if TYPE_CHECKING:
    import pathlib

    from ._index_integrity import IntegrityVerdict
    from ._source_types import PublicSourceType

logger = logging.getLogger(__name__)

__all__ = [
    "REPAIR_REQUEST_MIN_INTERVAL_SECONDS",
    "SHRUNKEN_OBSERVATION_TTL_SECONDS",
    "note_integrity_verdict",
    "reset_observations",
    "shrunken_observations",
]

#: How long a shrunken observation keeps answering for its root and domain
#: after the last search that saw it. A live shrink is re-observed by every
#: search, so a real problem refreshes this continuously; an entry that ages
#: out either healed while nothing was searching or belongs to a root nobody
#: queries any more, and neither deserves a permanent degraded line.
SHRUNKEN_OBSERVATION_TTL_SECONDS = 900.0

#: Minimum spacing between repair *requests* for one root and domain. While a
#: requested job is active the job manager deduplicates further requests onto
#: it, so this interval only governs how soon a new request follows a job that
#: reached a terminal state. A repair that keeps failing therefore costs one
#: admission per interval at worst - its retries in between belong to the job
#: machinery's own resilience policy, never to a search-driven loop.
REPAIR_REQUEST_MIN_INTERVAL_SECONDS = 600.0

#: Hard ceiling on remembered observations, mirroring the claim cache's bound:
#: unreachable through a daemon's bounded root registry, present so a
#: pathological caller cycling roots cannot grow the dict without bound.
_MAX_OBSERVATIONS = 256


@dataclass(frozen=True, slots=True)
class _Observation:
    """One root+domain's remembered shrink and the repair requested for it."""

    observed_at: float
    requested_at: float | None
    repair_job_id: str | None


_STATE_LOCK = threading.Lock()
_OBSERVATIONS: dict[tuple[str, str], _Observation] = {}


def _observation_key(root: pathlib.Path, source: str) -> tuple[str, str]:
    """Return the canonical registry key for one root and domain."""
    return (os.path.normcase(str(root)), source)


def reset_observations() -> None:
    """Forget every observation (tests only)."""
    with _STATE_LOCK:
        _OBSERVATIONS.clear()


def _auto_repair_enabled() -> bool:
    from .config._settings import get_config

    return bool(get_config().integrity_auto_repair)


def _spawn_repair(
    root: pathlib.Path,
    source: PublicSourceType,
    key: tuple[str, str],
) -> None:
    """Request one repair job off the serving thread and record its id."""

    def _request() -> None:
        try:
            from ._source_types import PublicSourceType as _Source
            from .jobs import (
                start_reindex_codebase,
                start_reindex_documents,
                start_reindex_vault,
            )

            starters = {
                _Source.CODE: start_reindex_codebase,
                _Source.DOCUMENT: start_reindex_documents,
                _Source.VAULT: start_reindex_vault,
            }
            job_id = starters[source](root, False, initiator_kind="integrity")
        except Exception:
            # The next observation past the spacing interval asks again; a
            # failed admission must degrade the repair, never the search.
            logger.warning(
                "could not admit an integrity repair for the %s index of %s",
                source.value,
                root,
                exc_info=True,
            )
            return
        with _STATE_LOCK:
            entry = _OBSERVATIONS.get(key)
            if entry is not None:
                _OBSERVATIONS[key] = replace(entry, repair_job_id=job_id)
        logger.info(
            "integrity repair %s admitted for the shrunken %s index of %s",
            job_id,
            source.value,
            root,
        )

    threading.Thread(
        target=_request,
        name=f"integrity-repair-{source.value}",
        daemon=True,
    ).start()


def _record_verdict(
    root: pathlib.Path,
    source: PublicSourceType,
    verdict: IntegrityVerdict,
    *,
    now: float,
) -> tuple[bool, str | None]:
    """Advance the registry for one verdict; decide, but perform nothing.

    Returns ``(request_repair, repair_job_id)``. Split from the dispatch so
    the decision - which verdicts act, how requests are spaced, what clears
    an observation - is a plain function over registry state.

    ``consistent`` clears the root+domain's observation: a proven-whole
    collection needs no memory of its shrink. ``unverifiable`` neither
    records nor repairs - an unreadable claim is not evidence of loss, and
    automatic action on it is forbidden. Only ``shrunken`` records the
    observation and, when auto-repair is enabled and the spacing interval
    allows, asks for one repair.
    """
    key = _observation_key(root, source.value)
    if verdict == VERDICT_CONSISTENT:
        with _STATE_LOCK:
            _OBSERVATIONS.pop(key, None)
        return (False, None)
    if verdict != VERDICT_SHRUNKEN:
        return (False, None)

    request_repair = False
    with _STATE_LOCK:
        entry = _OBSERVATIONS.get(key)
        if entry is None:
            if len(_OBSERVATIONS) >= _MAX_OBSERVATIONS:
                _OBSERVATIONS.clear()
            entry = _Observation(observed_at=now, requested_at=None, repair_job_id=None)
        else:
            entry = replace(entry, observed_at=now)
        if _auto_repair_enabled() and (
            entry.requested_at is None
            or now - entry.requested_at >= REPAIR_REQUEST_MIN_INTERVAL_SECONDS
        ):
            request_repair = True
            entry = replace(entry, requested_at=now)
        _OBSERVATIONS[key] = entry
        job_id = entry.repair_job_id
    return (request_repair, job_id)


def note_integrity_verdict(
    root: pathlib.Path,
    source: PublicSourceType,
    verdict: IntegrityVerdict,
) -> str | None:
    """Record one serve-time verdict and return the active repair job id, if any.

    Called by the service search path beside the evaluator, never by an entry
    point. The decision itself lives in :func:`_record_verdict`; this performs
    whatever it decided, off the serving thread.
    """
    request_repair, job_id = _record_verdict(
        root, source, verdict, now=time.monotonic()
    )
    if request_repair:
        _spawn_repair(root, source, _observation_key(root, source.value))
    return job_id


def shrunken_observations(
    root: pathlib.Path,
    *,
    now: float | None = None,
) -> dict[str, dict[str, object]]:
    """Return the live shrunken observations for *root*, keyed by domain.

    Read by the domain-status surface so an operator sees "shrunken, repair in
    flight" (or "shrunken, auto-repair disabled") instead of a mystery reindex.
    Expired entries are dropped on read, so the surface never reports a shrink
    no recent search has re-observed. ``now`` shares the monotonic clock the
    recorder stamps with; passing it makes expiry decidable in a test.
    """
    if now is None:
        now = time.monotonic()
    normalized = os.path.normcase(str(root))
    enabled = _auto_repair_enabled()
    result: dict[str, dict[str, object]] = {}
    with _STATE_LOCK:
        expired = [
            key
            for key, entry in _OBSERVATIONS.items()
            if now - entry.observed_at >= SHRUNKEN_OBSERVATION_TTL_SECONDS
        ]
        for key in expired:
            del _OBSERVATIONS[key]
        for (entry_root, source), entry in _OBSERVATIONS.items():
            if entry_root != normalized:
                continue
            result[source] = {
                "repair_job_id": entry.repair_job_id,
                "auto_repair": "enabled" if enabled else "disabled",
            }
    return result
