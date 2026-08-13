"""Binding and releasing an external GPU borrower's hold on the service.

A borrower proves it still holds the machine-wide lease before the service
will act on its behalf, and the binding is cleared only by the resume that
ends the hold. Kept apart from the residency transition it authorises so that
"who asked" and "what happens" stay separable.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from .gpu_borrow_lease import BorrowerLeaseStatus, borrower_lease_status
from .service_quiesce import (
    QuiesceSnapshot,
    QuiesceState,
    QuiesceTransition,
    ServiceQuiesceController,
)

if TYPE_CHECKING:
    import threading

logger = logging.getLogger("vaultspec_rag.service")


class BorrowerLeaseMixin:
    """Validates and tracks the borrower authorised to hold this service paused."""

    _borrower_capability: str | None
    _lock: threading.RLock
    _quiesce_controller: ServiceQuiesceController

    if TYPE_CHECKING:
        # Provided by the registry this mixes into.
        def resume_resources(
            self, *, timeout_seconds: float = ...
        ) -> QuiesceTransition: ...

    def quiesce_snapshot(self) -> QuiesceSnapshot:
        """Return the registry-owned controller's read-only lifecycle truth."""
        return self.published_quiesce_snapshot(self._quiesce_controller.snapshot())

    def published_quiesce_snapshot(self, snapshot: QuiesceSnapshot) -> QuiesceSnapshot:
        """Stamp borrower ownership onto one controller snapshot before it ships.

        The controller decides lifecycle state and the registry decides who owns
        the resulting hold, so neither half can answer an operator alone.  Every
        snapshot that leaves this process goes through here, including the one
        carried on a transition result: a route that rendered the controller's
        own snapshot would report an unowned hold on exactly the responses where
        ownership is the thing being reported.

        The binding is read without ``self._lock`` deliberately.  That lock is
        held across model construction, and the watcher reads a snapshot on its
        intake path, so acquiring it here would let a model load stall watcher
        handoff.  Reading one attribute is atomic, and the answer is a
        point-in-time observation either way: the controller half of this
        snapshot was already taken at a different instant.  The security-
        relevant comparison in :meth:`borrower_capability_is_bound` still takes
        the lock, because deciding who may act is not an observation.
        """
        return replace(
            snapshot,
            borrower_bound=self._borrower_capability is not None,
        )

    def validate_borrower_lifecycle_request(
        self,
        capability: str | None,
        *,
        pause: bool,
    ) -> str | None:
        """Return one lease denial, or ``None`` for an authorized lifecycle call."""
        with self._lock:
            bound_capability = self._borrower_capability
        if bound_capability is not None:
            if capability is None:
                return None if pause else "borrower_lease_required"
            if not hmac.compare_digest(bound_capability, capability):
                return "borrower_lease_mismatch"
        if capability is None:
            return None
        return self._borrower_lease_error(capability)

    def borrower_capability_is_bound(self, capability: str) -> bool:
        """Return whether this exact capability already owns the current hold.

        Separate from :meth:`bind_borrower_capability` because the caller needs
        to distinguish "already mine" from "bindable" before deciding whether an
        observed quiescence may be claimed at all.  Compared in constant time
        like every other capability check.
        """
        with self._lock:
            bound_capability = self._borrower_capability
        if bound_capability is None:
            return False
        return hmac.compare_digest(bound_capability, capability)

    def bind_borrower_capability(self, capability: str) -> bool:
        """Retain a verified borrower only after the registry is safely quiesced."""
        snapshot = self._quiesce_controller.snapshot()
        if (
            snapshot.state is not QuiesceState.QUIESCED
            or not snapshot.vram_released
            or not snapshot.safe_to_borrow_gpu
        ):
            return False
        with self._lock:
            bound_capability = self._borrower_capability
            if bound_capability is None:
                self._borrower_capability = capability
                return True
            return hmac.compare_digest(bound_capability, capability)

    def clear_borrower_capability_after_resume(self, capability: str | None) -> None:
        """Clear a borrower binding only for its matching achieved resume."""
        if capability is None:
            return
        with self._lock:
            bound_capability = self._borrower_capability
            if bound_capability is not None and hmac.compare_digest(
                bound_capability,
                capability,
            ):
                self._borrower_capability = None

    def resume_lost_borrower_lease(self) -> QuiesceTransition | None:
        """Recover only a borrower-bound safe quiescence after its OS lock dies."""
        with self._lock:
            bound_capability = self._borrower_capability
        if bound_capability is None:
            return None
        snapshot = self._quiesce_controller.snapshot()
        if snapshot.state is not QuiesceState.QUIESCED:
            return None
        lease_status = borrower_lease_status(bound_capability)
        if lease_status is BorrowerLeaseStatus.UNAVAILABLE:
            logger.warning(
                "GPU borrower lease is unavailable; retaining service quiescence"
            )
            return None
        if lease_status is not BorrowerLeaseStatus.NOT_HELD:
            return None
        transition = self.resume_resources()
        if transition.achieved:
            self.clear_borrower_capability_after_resume(bound_capability)
        return transition

    @staticmethod
    def _borrower_lease_error(capability: str) -> str | None:
        """Map one live borrower verification result to its lifecycle error."""
        match borrower_lease_status(capability):
            case BorrowerLeaseStatus.HELD:
                return None
            case BorrowerLeaseStatus.NOT_HELD:
                return "borrower_lease_not_held"
            case BorrowerLeaseStatus.CAPABILITY_INVALID:
                return "borrower_capability_invalid"
            case BorrowerLeaseStatus.UNAVAILABLE:
                return "borrower_lease_unavailable"
