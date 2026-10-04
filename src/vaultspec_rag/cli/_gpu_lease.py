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
from ..serviceclient._discovery import (
    MachineResolution,
    resolve_machine_service,
)
from ..serviceclient._search_transport import get_search_timeout
from ..serviceclient._transport import _try_http_admin

__all__ = [
    "BorrowGPUError",
    "run_with_borrowed_gpu",
]

_LEASE_UNAVAILABLE: Final = "gpu_borrow_lease_unavailable"
_SERVICE_UNAVAILABLE: Final = "borrow_gpu_service_unavailable"
_SERVICE_PORT_MISMATCH: Final = "borrow_gpu_service_port_mismatch"
_SERVICE_VERSION_INCOMPATIBLE: Final = "borrow_gpu_service_version_incompatible"
_PAUSE_UNACKNOWLEDGED: Final = "borrow_gpu_pause_unacknowledged"
_SAFE_SNAPSHOT_MISSING: Final = "borrow_gpu_safe_snapshot_missing"
_RESUME_UNACKNOWLEDGED: Final = "borrow_gpu_resume_unacknowledged"
_QUIESCE_CONTRACT_MISMATCH: Final = "borrow_gpu_quiesce_contract_mismatch"


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
    open: the service's heartbeat then observes OS lease loss when this process
    exits and performs the only safe recovery.
    """
    lease = acquire_gpu_borrow_lease()
    if lease is None:
        raise BorrowGPUError(
            _LEASE_UNAVAILABLE,
            "Another process already holds the GPU borrower lease, so the "
            "service is most likely paused for it. The lease is released when "
            "that work finishes; retry then. Holder identity is deliberately "
            "not published.",
        )

    pause_attempted = False
    port: int | None = None
    failure: BaseException | None = None
    try:
        port = _resolve_compatible_service(requested_port)

        def mark_pause_attempted() -> None:
            nonlocal pause_attempted
            pause_attempted = True

        _require_acknowledged_pause(
            lease,
            port,
            before_request=mark_pause_attempted,
        )
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


def _require_acknowledged_pause(
    lease: GPUBorrowLease,
    port: int,
    *,
    before_request: Callable[[], None],
) -> None:
    """Require an authenticated pause plus the exact safe snapshot."""
    before_request()
    result = _try_http_admin("pause_service", _borrower_args(lease), port)
    _reject_unrecognised_quiesce(result, verb="pause")
    if not _acknowledged_transition(result, QuiesceState.QUIESCED):
        raise BorrowGPUError(
            _PAUSE_UNACKNOWLEDGED,
            _pause_refusal_message(result),
        )
    if result is None or not _is_exact_safe_quiesce(result.get("quiesce")):
        raise BorrowGPUError(
            _SAFE_SNAPSHOT_MISSING,
            "The service did not provide an acknowledged safe borrower snapshot.",
        )


def _borrower_args(lease: GPUBorrowLease) -> dict[str, object]:
    """Return the one authenticated argument every lifecycle call carries."""
    return {"borrower_capability": lease.capability}


def _resume_is_acknowledged(lease: GPUBorrowLease, port: int) -> bool:
    """Return whether the matching authenticated resume reached running."""
    result = _try_http_admin(
        "resume_service",
        _borrower_args(lease),
        port,
        timeout=get_search_timeout(None),
    )
    _reject_unrecognised_quiesce(result, verb="resume")
    return _acknowledged_transition(result, QuiesceState.RUNNING)


def _pause_refusal_message(result: dict[str, object] | None) -> str:
    """Explain a refused borrower pause using the envelope it came back with.

    "The service did not acknowledge borrower pause" is true of every refusal
    and therefore useless for the common one. A service still working cannot
    hand over the device yet, and that reads identically to a service that will
    never hand it over - so the operator is left with no way to tell "wait" from
    "something is wrong". The envelope already says which it is.
    """
    quiesce = result.get("quiesce") if result is not None else None
    if _is_exact_quiesce_snapshot(quiesce):
        tickets = quiesce["active_compute_tickets"]
        if isinstance(tickets, int) and tickets > 0:
            return (
                f"The service is still running {tickets} compute "
                f"{'ticket' if tickets == 1 else 'tickets'} and cannot hand over "
                "the device yet. This clears on its own once that work drains; "
                "retry the borrow, or wait for the service to report idle."
            )
        named = _named_refusal(result)
        if named is not None:
            return named
        if quiesce["state"] != QuiesceState.QUIESCED.value:
            return (
                "The service did not reach a quiesced state for the borrower "
                f"(state: {quiesce['state']!r})."
            )
        return (
            "The service reached a quiesced state but did not acknowledge the "
            "borrower's pause."
        )
    return _named_refusal(result) or "The service did not acknowledge borrower pause."


def _named_refusal(result: dict[str, object] | None) -> str | None:
    """Return the sentence the service sent for a refusal it named, if any.

    A service that reaches a quiesced state and still refuses has a reason,
    and it is one this side cannot derive: a loan it could not record on an
    anchor another account owns reads, from the snapshot alone, exactly like
    an unacknowledged pause. The service already says which; repeating its
    sentence is what puts the condition in front of the operator instead of
    only in the daemon's log.
    """
    if result is None:
        return None
    error = result.get("error")
    message = result.get("message")
    if isinstance(error, str) and error and isinstance(message, str) and message:
        return message
    return None


def _reject_unrecognised_quiesce(
    result: dict[str, object] | None,
    *,
    verb: str,
) -> None:
    """Raise when the envelope came from a service on a different contract.

    The transition checks compare the envelope's field set exactly, which is
    right - a partial snapshot must never read as a safe handoff. But an exact
    comparison cannot tell a service that refused the transition from one that
    performed it and described the result in a vocabulary this build does not
    know. Both arrive as "not acknowledged", and the operator is sent to look
    at quiescence when the actual condition is two builds of the same service
    disagreeing about the envelope.

    Separating them costs nothing and is the difference between a message that
    names the fix and one that hides it: the transition may well have
    succeeded, so the remedy is to align the builds, not to debug a pause.
    """
    if result is None:
        return
    quiesce = result.get("quiesce")
    if not _is_json_object(quiesce):
        return
    unknown = frozenset(quiesce) - QUIESCE_ENVELOPE_FIELDS
    absent = QUIESCE_ENVELOPE_FIELDS - frozenset(quiesce)
    if not unknown and not absent:
        return
    raise BorrowGPUError(
        _QUIESCE_CONTRACT_MISMATCH,
        (
            f"The service described the {verb} with a quiesce envelope this "
            "build does not recognise, so the outcome cannot be verified even "
            "though the call itself succeeded. The service and this client are "
            "different builds; run them from the same install. "
            f"(unexpected fields: {sorted(unknown) or 'none'}; "
            f"missing fields: {sorted(absent) or 'none'})"
        ),
    )


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
    borrower_bound = value["borrower_bound"]
    return (
        isinstance(borrower_bound, bool)
        and isinstance(state, str)
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
