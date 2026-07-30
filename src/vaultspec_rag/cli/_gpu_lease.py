"""Fail-closed borrower coordination for explicit local GPU work.

The service remains the authority for its own lifecycle and residency.  This
module only binds one locally-held borrower lease to the service's existing
authenticated pause and resume routes before allowing a caller to use the GPU.
"""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING, Final, TypeGuard

if TYPE_CHECKING:
    from collections.abc import Callable

from ..gpu_borrow_lease import (
    GPUBorrowLease,
    acquire_gpu_borrow_lease,
    release_gpu_borrow_lease,
)
from ..service_quiesce import QUIESCE_ENVELOPE_FIELDS, QuiesceState
from ..serviceclient._compat import classify_service_version
from ..serviceclient._discovery import MachineResolution, resolve_machine_service
from ..serviceclient._transport import _try_http_admin

__all__ = ["BorrowGPUError", "run_with_borrowed_gpu"]

_LEASE_UNAVAILABLE: Final = "gpu_borrow_lease_unavailable"
_SERVICE_UNAVAILABLE: Final = "borrow_gpu_service_unavailable"
_SERVICE_PORT_MISMATCH: Final = "borrow_gpu_service_port_mismatch"
_SERVICE_VERSION_INCOMPATIBLE: Final = "borrow_gpu_service_version_incompatible"
_PAUSE_UNACKNOWLEDGED: Final = "borrow_gpu_pause_unacknowledged"
_SAFE_SNAPSHOT_MISSING: Final = "borrow_gpu_safe_snapshot_missing"
_RESUME_UNACKNOWLEDGED: Final = "borrow_gpu_resume_unacknowledged"


class BorrowGPUError(RuntimeError):
    """A fail-closed borrower-coordination refusal safe to render at the CLI."""

    def __init__(self, error: str, message: str) -> None:
        self.error = error
        super().__init__(message)


def run_with_borrowed_gpu(
    *,
    requested_port: int | None,
    work: Callable[[], None],
) -> None:
    """Run *work* only while a matching borrower pause is acknowledged.

    A failed pause may have reached the service even when its response did not
    return, so every pause attempt is paired with resume before a lease can be
    released.  An unacknowledged resume intentionally leaves the descriptor
    open: S29's service heartbeat then observes OS lease loss when this process
    exits and performs the only safe recovery.
    """
    lease = acquire_gpu_borrow_lease()
    if lease is None:
        raise BorrowGPUError(
            _LEASE_UNAVAILABLE,
            "Another process already holds the GPU borrower lease.",
        )

    pause_attempted = False
    port: int | None = None
    failure: BaseException | None = None
    try:
        port = _resolve_compatible_service(requested_port)
        pause_attempted = True
        _require_acknowledged_pause(lease, port)
        work()
    except BaseException as exc:
        failure = exc
        raise
    finally:
        if not pause_attempted or (
            port is not None and _resume_is_acknowledged(lease, port)
        ):
            release_gpu_borrow_lease(lease)
        elif failure is None:
            raise BorrowGPUError(
                _RESUME_UNACKNOWLEDGED,
                "The service did not acknowledge borrower resume; the GPU "
                "borrower lease is retained until this process exits.",
            )
        else:
            raise BorrowGPUError(
                _RESUME_UNACKNOWLEDGED,
                "The service did not acknowledge borrower resume; the GPU "
                "borrower lease is retained until this process exits.",
            ) from failure


def _resolve_compatible_service(requested_port: int | None) -> int:
    """Return the selected live compatible service, or refuse before pause."""
    resolution = resolve_machine_service()
    if not resolution.is_ready or resolution.port is None:
        raise BorrowGPUError(
            _SERVICE_UNAVAILABLE,
            _service_unavailable_message(resolution),
        )
    if requested_port is not None and requested_port != resolution.port:
        raise BorrowGPUError(
            _SERVICE_PORT_MISMATCH,
            (
                f"The requested service port {requested_port} does not match the "
                f"discovered service port {resolution.port}."
            ),
        )
    verdict = classify_service_version(resolution.payload)
    if not verdict.is_compatible:
        raise BorrowGPUError(
            _SERVICE_VERSION_INCOMPATIBLE,
            f"The discovered service is not compatible: {verdict.reason()}.",
        )
    return resolution.port


def _service_unavailable_message(resolution: MachineResolution) -> str:
    """Describe unavailable discovery without treating it as GPU permission."""
    return (
        "A compatible running service is required before GPU work may be "
        f"borrowed: {resolution.evidence()}."
    )


def _require_acknowledged_pause(lease: GPUBorrowLease, port: int) -> None:
    """Require an authenticated pause plus the exact safe snapshot."""
    result = _try_http_admin(
        "pause_service",
        {"borrower_capability": lease.capability},
        port,
    )
    if not _acknowledged_transition(result, QuiesceState.QUIESCED):
        raise BorrowGPUError(
            _PAUSE_UNACKNOWLEDGED,
            "The service did not acknowledge borrower pause.",
        )
    if result is None or not _is_exact_safe_quiesce(result.get("quiesce")):
        raise BorrowGPUError(
            _SAFE_SNAPSHOT_MISSING,
            "The service did not provide an acknowledged safe borrower snapshot.",
        )


def _resume_is_acknowledged(lease: GPUBorrowLease, port: int) -> bool:
    """Return whether the matching authenticated resume reached running."""
    result = _try_http_admin(
        "resume_service",
        {"borrower_capability": lease.capability},
        port,
    )
    return _acknowledged_transition(result, QuiesceState.RUNNING)


def _acknowledged_transition(
    result: dict[str, object] | None,
    expected_state: QuiesceState,
) -> bool:
    """Accept only a successful transition carrying the canonical state."""
    if result is None or result.get("ok") is not True:
        return False
    quiesce = result.get("quiesce")
    if not _is_exact_quiesce_snapshot(quiesce):
        return False
    return quiesce["state"] == expected_state.value


def _is_exact_safe_quiesce(value: object) -> bool:
    """Require the controller's exact canonical safe-handoff observation."""
    if not _is_exact_quiesce_snapshot(value):
        return False
    return (
        value["state"] == QuiesceState.QUIESCED.value
        and value["admissions_open"] is False
        and value["active_compute_tickets"] == 0
        and value["drain_complete"] is True
        and value["vram_released"] is True
        and value["safe_to_borrow_gpu"] is True
        and value["failure_reason"] is None
    )


def _is_exact_quiesce_snapshot(value: object) -> TypeGuard[dict[str, object]]:
    """Accept only the full typed controller envelope published by the service."""
    if not _is_json_object(value) or frozenset(value) != QUIESCE_ENVELOPE_FIELDS:
        return False
    state = value["state"]
    epoch = value["admission_epoch"]
    admissions_open = value["admissions_open"]
    tickets = value["active_compute_tickets"]
    drain_complete = value["drain_complete"]
    vram_released = value["vram_released"]
    safe_to_borrow_gpu = value["safe_to_borrow_gpu"]
    timestamps = (
        value["pause_requested_at"],
        value["drain_acknowledged_at"],
        value["quiesced_at"],
        value["warming_started_at"],
    )
    failure_reason = value["failure_reason"]
    return (
        isinstance(state, str)
        and state in {item.value for item in QuiesceState}
        and type(epoch) is int
        and epoch >= 0
        and isinstance(admissions_open, bool)
        and type(tickets) is int
        and tickets >= 0
        and isinstance(drain_complete, bool)
        and isinstance(vram_released, bool)
        and isinstance(safe_to_borrow_gpu, bool)
        and all(_is_optional_finite_timestamp(timestamp) for timestamp in timestamps)
        and (failure_reason is None or isinstance(failure_reason, str))
    )


def _is_optional_finite_timestamp(value: object) -> bool:
    """Accept a finite numeric timestamp or its explicit absent marker."""
    return value is None or (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and isfinite(float(value))
    )


def _is_json_object(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow one decoded JSON value to the object form this client reads."""
    return isinstance(value, dict)
