"""Process-held advisory lease for an external GPU borrower.

The resident service owns its own singleton lock.  A borrower uses this
separate machine-global anchor to prove that the process which will use the
GPU is still alive and has retained exclusive borrower authority.
"""

from __future__ import annotations

import base64
import hmac
import os
import secrets
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, TypeGuard

from ._anchor_claim import (
    claim_anchor,
    publish_anchor_record,
    read_anchor_record,
    release_anchor_claim,
)
from ._machine_lock import machine_lock_path

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "BorrowerLeaseStatus",
    "GPUBorrowLease",
    "acquire_gpu_borrow_lease",
    "borrower_lease_holder_pid",
    "borrower_lease_status",
    "gpu_borrow_lease_path",
    "is_borrower_capability",
    "release_gpu_borrow_lease",
]

_GPU_BORROW_LEASE_FILENAME = "gpu-borrower.lock"
_CAPABILITY_BYTES = 32

# Every private lease record occupies exactly this many bytes on disk, padded
# with spaces that JSON ignores; the constant width is what keeps an in-place
# republication from ever exposing an empty or partial record to a concurrent
# verifier. Sized with ample headroom over the largest possible payload: a
# 64-bit pid and a 43-character encoded capability come to under 90 bytes.
_LEASE_RECORD_WIDTH = 128


class BorrowerLeaseStatus(StrEnum):
    """The private lease verifier's deliberately small result vocabulary."""

    HELD = "held"
    NOT_HELD = "not_held"
    CAPABILITY_INVALID = "capability_invalid"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class GPUBorrowLease:
    """One process-local handle retaining the external borrower anchor."""

    path: Path
    descriptor: int
    capability: str


_held_leases: dict[str, GPUBorrowLease] = {}
_lease_guard = threading.RLock()


def gpu_borrow_lease_path() -> Path:
    """Return the borrower anchor beside, but distinct from, service identity."""
    return machine_lock_path().with_name(_GPU_BORROW_LEASE_FILENAME)


def is_borrower_capability(capability: object) -> bool:
    """Return whether *capability* encodes exactly 32 URL-safe random bytes."""
    if not isinstance(capability, str) or not capability:
        return False
    encoded = capability.encode("ascii", errors="ignore")
    if encoded.decode("ascii") != capability:
        return False
    padding = b"=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode(encoded + padding)
    except ValueError:
        return False
    return (
        len(decoded) == _CAPABILITY_BYTES
        and base64.urlsafe_b64encode(decoded).rstrip(b"=") == encoded
    )


def acquire_gpu_borrow_lease() -> GPUBorrowLease | None:
    """Acquire and retain the borrower lease, or return ``None`` on contention."""
    from ._test_isolation import enforce_pytest_managed_singleton_containment

    path = gpu_borrow_lease_path()
    enforce_pytest_managed_singleton_containment(
        operation="acquire the GPU borrower lease",
        targets=(path,),
    )
    with _lease_guard:
        retained = _held_leases.get(str(path))
        if retained is not None:
            _require_active_lease(retained, operation="reuse the GPU borrower lease")
            return retained
        claim = claim_anchor(path, pid_record=True, create_parent=True)
        if claim.fault is not None:
            raise claim.fault
        if claim.descriptor is None:
            return None
        capability = _new_capability()
        try:
            publish_anchor_record(
                claim.descriptor,
                {"pid": os.getpid(), "capability": capability},
                width=_LEASE_RECORD_WIDTH,
            )
        except BaseException:
            release_anchor_claim(claim.descriptor, pid_record=True)
            raise
        lease = GPUBorrowLease(
            path=path,
            descriptor=claim.descriptor,
            capability=capability,
        )
        _held_leases[str(path)] = lease
    return lease


def release_gpu_borrow_lease(lease: GPUBorrowLease) -> None:
    """Release *lease* only when it is this process's retained exact handle."""
    from ._test_isolation import enforce_pytest_managed_singleton_containment

    path_key = str(lease.path)
    enforce_pytest_managed_singleton_containment(
        operation="release the GPU borrower lease",
        targets=(lease.path,),
    )
    with _lease_guard:
        if _held_leases.get(path_key) is not lease:
            return
        _held_leases.pop(path_key)
        release_anchor_claim(lease.descriptor, pid_record=True)


def borrower_lease_status(capability: str) -> BorrowerLeaseStatus:
    """Verify live foreign lock contention and its constant-time capability."""
    if not is_borrower_capability(capability):
        return BorrowerLeaseStatus.CAPABILITY_INVALID
    path = gpu_borrow_lease_path()
    from ._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="verify the GPU borrower lease",
        targets=(path,),
    )
    claim = claim_anchor(path, pid_record=True, create_parent=True)
    if claim.fault is not None:
        return BorrowerLeaseStatus.UNAVAILABLE
    if claim.descriptor is not None:
        release_anchor_claim(claim.descriptor, pid_record=True)
        return BorrowerLeaseStatus.NOT_HELD
    recorded = _read_recorded_capability(path)
    if recorded is None or not hmac.compare_digest(recorded, capability):
        return BorrowerLeaseStatus.CAPABILITY_INVALID
    return BorrowerLeaseStatus.HELD


def borrower_lease_holder_pid(capability: str) -> int | None:
    """Return the pid holding the lease *capability* names, while it holds it.

    The service lends the GPU to exactly this process tree, so the pid is read
    only after the lease is verified live and matching; a record that fails
    either check names nobody. The pid is for that loan alone and is never
    projected into a snapshot, status, log or error.
    """
    if borrower_lease_status(capability) is not BorrowerLeaseStatus.HELD:
        return None
    match read_anchor_record(gpu_borrow_lease_path()):
        case {"pid": int() as pid} if type(pid) is int and pid > 0:
            return pid
        case _:
            return None


def _new_capability() -> str:
    """Create one unpadded URL-safe opaque capability from 32 random bytes."""
    raw = secrets.token_bytes(_CAPABILITY_BYTES)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _read_recorded_capability(path: Path) -> str | None:
    """Read a valid private lease record without projecting its contents."""
    parsed = read_anchor_record(path)
    if not _is_json_object(parsed):
        return None
    match parsed:
        case {"pid": int() as pid, "capability": str() as capability} if (
            len(parsed) == 2
        ):
            if type(pid) is int and is_borrower_capability(capability):
                return capability
        case _:
            return None
    return None


def _is_json_object(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow a decoded JSON value to the object surface this module reads."""
    return isinstance(value, dict)


def _require_active_lease(lease: GPUBorrowLease, *, operation: str) -> None:
    """Reject a stale same-process handle before treating it as a lease."""
    active = _held_leases.get(str(lease.path))
    if active is not lease:
        raise PermissionError(f"cannot {operation} without the active borrower lease")
    try:
        os.fstat(lease.descriptor)
    except OSError as exc:
        raise PermissionError(
            f"cannot {operation} after the borrower lease was closed"
        ) from exc
