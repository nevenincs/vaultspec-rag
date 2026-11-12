"""Repeated-failure suppression for watcher controller callbacks.

One broken root fails the same way on every scheduler turn; logging each turn
rotates the whole service log away within a minute. Each distinct failure is
logged in full once, identical repeats are counted, and a still-repeating
failure surfaces as a periodic count, so it is never silent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..watcher_admission import ControllerKey

__all__ = ["WatcherFailureLog"]

logger = logging.getLogger("vaultspec_rag.server")

#: Distinct failures remembered per controller callback. Each is logged in full
#: once; identical repeats are counted instead of logged.
_MAX_FAILURE_SIGNATURES = 8
#: Characters of a failure message that make it "the same" failure.
_FAILURE_SIGNATURE_CHARS = 512
#: How often a still-repeating suppressed failure is summarised.
_FAILURE_SUMMARY_SECONDS = 300.0


@dataclass(slots=True)
class _RepeatedFailure:
    suppressed: int
    summarized_at: float


class WatcherFailureLog:
    """Log controller callback failures once per distinct signature."""

    def __init__(self, monotonic: Callable[[], float]) -> None:
        self._monotonic = monotonic
        self._seen: dict[
            tuple[ControllerKey, str],
            dict[tuple[str, str], _RepeatedFailure],
        ] = {}

    def succeeded(self, key: ControllerKey, phase: str) -> None:
        """Forget the failures of a callback that has just succeeded."""
        self._seen.pop((key, phase), None)

    def forget_root(self, canonical_root: str) -> None:
        """Forget every remembered failure of one canonical root."""
        self._seen = {
            failure_key: seen
            for failure_key, seen in self._seen.items()
            if failure_key[0][0] != canonical_root
        }

    def report(self, key: ControllerKey, phase: str, error: Exception) -> None:
        """Log a failure in full once, then count identical repeats."""
        now = self._monotonic()
        signature = (
            type(error).__qualname__,
            str(error)[:_FAILURE_SIGNATURE_CHARS],
        )
        seen = self._seen.setdefault((key, phase), {})
        repeated = seen.get(signature)
        if repeated is None:
            if len(seen) >= _MAX_FAILURE_SIGNATURES:
                seen.pop(next(iter(seen)))
            seen[signature] = _RepeatedFailure(suppressed=0, summarized_at=now)
            logger.error(
                "Watcher controller %s failed for %s/%s",
                phase,
                *key,
                exc_info=error,
            )
            return
        repeated.suppressed += 1
        if now - repeated.summarized_at >= _FAILURE_SUMMARY_SECONDS:
            logger.error(
                "Watcher controller %s failed for %s/%s %d more times with the "
                "same error in the last %.0f seconds: %s: %s",
                phase,
                *key,
                repeated.suppressed,
                now - repeated.summarized_at,
                *signature,
            )
            repeated.suppressed = 0
            repeated.summarized_at = now
