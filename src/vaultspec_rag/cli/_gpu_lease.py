"""Fail-closed borrower coordination for explicit local GPU work.

The service remains the authority for its own lifecycle and residency.  This
module only binds one locally-held borrower lease to the service's existing
authenticated pause and resume routes before allowing a caller to use the GPU.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Final, TypeGuard

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

from .._test_isolation import ManagedSingletonIsolationError
from ..gpu_borrow_lease import (
    CapturedBorrowerLeaseAuthority,
    GPUBorrowLease,
    acquire_gpu_borrow_lease,
    acquire_gpu_borrow_lease_for_captured_authority,
    mint_captured_borrower_lease_authority,
    release_gpu_borrow_lease,
)
from ..service_quiesce import QUIESCE_ENVELOPE_FIELDS, QuiesceState
from ..serviceclient._compat import classify_service_version
from ..serviceclient._discovery import (
    MachineResolution,
    PreIsolationMachinePointer,
    capture_pre_isolation_machine_pointer,
    resolve_machine_service,
    revalidate_captured_machine_pointer,
)
from ..serviceclient._transport import (
    _get_admin_timeout,
    _try_http_admin,
    _try_http_health,
)

__all__ = [
    "BorrowGPUError",
    "BorrowerServiceTarget",
    "capture_borrower_service_target",
    "run_with_borrowed_gpu",
]

_LEASE_UNAVAILABLE: Final = "gpu_borrow_lease_unavailable"
_SERVICE_UNAVAILABLE: Final = "borrow_gpu_service_unavailable"
_SERVICE_PORT_MISMATCH: Final = "borrow_gpu_service_port_mismatch"
_SERVICE_VERSION_INCOMPATIBLE: Final = "borrow_gpu_service_version_incompatible"
_PAUSE_UNACKNOWLEDGED: Final = "borrow_gpu_pause_unacknowledged"
_SAFE_SNAPSHOT_MISSING: Final = "borrow_gpu_safe_snapshot_missing"
_RESUME_UNACKNOWLEDGED: Final = "borrow_gpu_resume_unacknowledged"
_SERVICE_TARGET_CHANGED: Final = "borrow_gpu_service_target_changed"


@dataclass(frozen=True, slots=True)
class BorrowerServiceTarget:
    """One immutable pre-isolation identity for a borrower lifecycle call.

    This value deliberately retains only original public identity witnesses,
    a token digest, and the redacted in-process authority. The service token
    is represented by its SHA-256 digest; each pause or resume re-reads its
    short-lived raw bearer after the target has been revalidated.
    """

    identity_lock_path: Path
    discovery_path: Path
    port: int
    service_pid: int
    token_sha256: str
    authority: CapturedBorrowerLeaseAuthority
    pointer: PreIsolationMachinePointer


class BorrowGPUError(RuntimeError):
    """A fail-closed borrower-coordination refusal safe to render at the CLI."""

    def __init__(self, error: str, message: str) -> None:
        self.error = error
        super().__init__(message)


def capture_borrower_service_target() -> BorrowerServiceTarget | None:
    """Capture the live machine service before pytest redirects managed paths.

    The capture itself is not GPU permission. It only freezes the original
    paths and non-secret identity witnesses that a later borrower-held call
    must repeat after its isolated test configuration is in effect.
    """
    captured = capture_pre_isolation_machine_pointer()
    if captured is None:
        return None
    resolved = _captured_machine_pointer(captured)
    if resolved is None:
        return None
    payload, port, service_pid, service_token = resolved
    if not classify_service_version(payload).is_compatible:
        return None
    if (
        _matching_health_identity(
            _read_health_evidence(port),
            service_pid=service_pid,
            port=port,
            token_sha256=_token_sha256(service_token),
        )
        is None
    ):
        return None
    try:
        authority = mint_captured_borrower_lease_authority(captured.observation.witness)
    except (ManagedSingletonIsolationError, PermissionError):
        return None
    return BorrowerServiceTarget(
        identity_lock_path=captured.observation.identity_lock_path,
        discovery_path=captured.observation.discovery_path,
        port=port,
        service_pid=service_pid,
        token_sha256=_token_sha256(service_token),
        authority=authority,
        pointer=captured.redacted(),
    )


def run_with_borrowed_gpu(
    *,
    requested_port: int | None,
    work: Callable[[], None],
    target: BorrowerServiceTarget | None = None,
) -> None:
    """Run *work* only while a matching borrower pause is acknowledged.

    A failed pause may have reached the service even when its response did not
    return, so every pause attempt is paired with resume before a lease can be
    released.  An unacknowledged resume intentionally leaves the descriptor
    open: the service's heartbeat then observes OS lease loss when this process
    exits and performs the only safe recovery.
    """
    try:
        lease = (
            acquire_gpu_borrow_lease_for_captured_authority(target.authority)
            if target is not None
            else acquire_gpu_borrow_lease()
        )
    except PermissionError as exc:
        raise BorrowGPUError(
            _SERVICE_TARGET_CHANGED,
            "The captured service borrower lease could not be acquired safely.",
        ) from exc
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
        port = _resolve_borrower_port(requested_port, target)

        def mark_pause_attempted() -> None:
            nonlocal pause_attempted
            pause_attempted = True

        _require_acknowledged_pause(
            lease,
            port,
            target=target,
            before_request=mark_pause_attempted,
        )
        work()
    except BaseException as exc:
        failure = exc
        raise
    finally:
        if not pause_attempted or (
            port is not None and _resume_is_acknowledged(lease, port, target=target)
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


def _resolve_borrower_port(
    requested_port: int | None,
    target: BorrowerServiceTarget | None,
) -> int:
    """Resolve an ordinary CLI target or retain the captured machine target."""
    if target is not None:
        if requested_port is not None and requested_port != target.port:
            raise BorrowGPUError(
                _SERVICE_PORT_MISMATCH,
                (
                    f"The requested service port {requested_port} does not match the "
                    f"captured service port {target.port}."
                ),
            )
        return target.port
    return _resolve_compatible_service(requested_port)


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
    target: BorrowerServiceTarget | None,
    before_request: Callable[[], None],
) -> None:
    """Require an authenticated pause plus the exact safe snapshot."""
    target_verified, result = _try_borrower_lifecycle_call(
        "pause_service",
        lease,
        port,
        target=target,
        before_request=before_request,
    )
    if not target_verified:
        raise BorrowGPUError(
            _SERVICE_TARGET_CHANGED,
            "The captured service target no longer matches the original machine "
            "service.",
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


def _resume_is_acknowledged(
    lease: GPUBorrowLease,
    port: int,
    *,
    target: BorrowerServiceTarget | None,
) -> bool:
    """Return whether the matching authenticated resume reached running."""
    target_verified, result = _try_borrower_lifecycle_call(
        "resume_service",
        lease,
        port,
        target=target,
        before_request=lambda: None,
    )
    return target_verified and _acknowledged_transition(result, QuiesceState.RUNNING)


def _try_borrower_lifecycle_call(
    tool_name: str,
    lease: GPUBorrowLease,
    port: int,
    *,
    target: BorrowerServiceTarget | None,
    before_request: Callable[[], None],
) -> tuple[bool, dict[str, object] | None]:
    """Make one lifecycle call, pinning captured targets before each send.

    The raw token returned by ``_revalidate_captured_target`` stays inside this
    one pause or resume transport call. Its refresh closure captures only the
    non-secret target and asks for a new token after a 401.
    """
    args: dict[str, object] = {"borrower_capability": lease.capability}
    if target is None:
        before_request()
        return True, _try_http_admin(tool_name, args, port)
    token = _revalidate_captured_target(target)
    if token is None:
        return False, None
    before_request()
    return True, _try_http_admin(
        tool_name,
        args,
        port,
        initial_bearer_token=token,
        refresh_bearer_token=lambda: _revalidate_captured_target(target) or "",
    )


def _revalidate_captured_target(target: BorrowerServiceTarget) -> str | None:
    """Return the current bearer only when every captured witness still agrees."""
    resolution = revalidate_captured_machine_pointer(
        target.pointer,
        expected_pid=target.service_pid,
        expected_port=target.port,
        token_sha256=target.token_sha256,
    )
    if (
        resolution is None
        or resolution.payload is None
        or not classify_service_version(resolution.payload).is_compatible
    ):
        return None
    discovery_token = resolution.service_token
    if not discovery_token:
        return None
    health = _read_health_evidence(target.port)
    return _matching_health_token(health, target)


def _captured_machine_pointer(
    captured: PreIsolationMachinePointer,
) -> tuple[dict[str, object], int, int, str] | None:
    """Resolve one existing machine pointer during pytest's pre-root window.

    Generic discovery probes configured singleton paths, which pytest correctly
    blocks before it has registered its root. Captured borrowing is the one
    narrow exception: it observes only the original paths captured before that
    redirect. This helper neither creates nor writes a path, and returns no
    result unless the normal pointer schema, freshness, port, token, and exact
    lock-holder/PID correlation all hold.
    """
    resolution = captured.resolution
    holder_pid = captured.observation.holder_pid
    if (
        not resolution.is_ready
        or resolution.holder_pid != holder_pid
        or resolution.pointer_pid != holder_pid
        or resolution.port is None
        or not resolution.service_token
        or resolution.payload is None
    ):
        return None
    return (
        resolution.payload,
        resolution.port,
        holder_pid,
        resolution.service_token,
    )


def _matching_health_token(
    health: dict[str, object] | None,
    target: BorrowerServiceTarget,
) -> str | None:
    """Return the served bearer only when health proves the captured identity."""
    return _matching_health_identity(
        health,
        service_pid=target.service_pid,
        port=target.port,
        token_sha256=target.token_sha256,
    )


def _read_health_evidence(port: int) -> dict[str, object] | None:
    """Read ``/health`` as identity evidence, on the operator-governed bound.

    Every borrower identity check reads health to PROVE which service holds
    the port, which is a different question from the readiness poll the
    probe's short default bound is shaped for. There a fast "not up yet" is
    the point; here an unanswered probe is indistinguishable from a service
    whose pid, port or token disagree, and the caller refuses either way. So
    the short bound turns a merely busy service into a false "this is not the
    service I captured" - and a service busy enough to answer slowly is
    exactly the one a borrower most needs to coordinate with. Evidence reads
    therefore take the same operator-governed bound the rest of this client's
    evidence reads take.
    """
    return _try_http_health(port, timeout=_get_admin_timeout())


def _matching_health_identity(
    health: dict[str, object] | None,
    *,
    service_pid: int,
    port: int,
    token_sha256: str,
) -> str | None:
    """Return a served bearer only when health proves the frozen identity."""
    if health is None:
        return None
    health_pid = health.get("pid")
    health_port = health.get("port")
    health_token = health.get("service_token")
    if (
        health_pid != service_pid
        or health_port != port
        or not isinstance(health_token, str)
        or not health_token
        or not hmac.compare_digest(_token_sha256(health_token), token_sha256)
    ):
        return None
    return health_token


def _token_sha256(token: str) -> str:
    """Return the non-secret identity witness persisted in a captured target."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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
