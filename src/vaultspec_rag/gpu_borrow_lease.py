"""Process-held advisory lease for an external GPU borrower.

The resident service owns its own singleton lock.  A borrower uses this
separate machine-global anchor to prove that the process which will use the
GPU is still alive and has retained exclusive borrower authority.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, TypeGuard

from ._anchor_claim import claim_anchor, release_anchor_claim
from ._machine_lock import machine_lock_path

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "BorrowerLeaseStatus",
    "GPUBorrowLease",
    "acquire_gpu_borrow_lease",
    "borrower_lease_status",
    "gpu_borrow_lease_path",
    "is_borrower_capability",
    "release_gpu_borrow_lease",
]

_GPU_BORROW_LEASE_FILENAME = "gpu-borrower.lock"
_CAPABILITY_BYTES = 32


class BorrowerLeaseStatus(StrEnum):
    """The private lease verifier's deliberately small result vocabulary."""

    HELD = "held"
    NOT_HELD = "not_held"
    CAPABILITY_INVALID = "capability_invalid"


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
    path = gpu_borrow_lease_path()
    from ._test_isolation import enforce_pytest_managed_singleton_containment

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
            _write_private_record(claim.descriptor, capability)
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

    enforce_pytest_managed_singleton_containment(
        operation="release the GPU borrower lease",
        targets=(lease.path,),
    )
    with _lease_guard:
        if _held_leases.get(str(lease.path)) is not lease:
            return
        _held_leases.pop(str(lease.path))
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
        return BorrowerLeaseStatus.NOT_HELD
    if claim.descriptor is not None:
        release_anchor_claim(claim.descriptor, pid_record=True)
        return BorrowerLeaseStatus.NOT_HELD
    recorded = _read_recorded_capability(path)
    if recorded is None or not hmac.compare_digest(recorded, capability):
        return BorrowerLeaseStatus.CAPABILITY_INVALID
    return BorrowerLeaseStatus.HELD


def _new_capability() -> str:
    """Create one unpadded URL-safe opaque capability from 32 random bytes."""
    raw = secrets.token_bytes(_CAPABILITY_BYTES)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _write_private_record(descriptor: int, capability: str) -> None:
    """Write the locked borrower's private process record while it owns the fd."""
    payload = json.dumps({"pid": os.getpid(), "capability": capability}).encode("utf-8")
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.write(descriptor, payload)
    os.fsync(descriptor)


def _read_recorded_capability(path: Path) -> str | None:
    """Read a valid private lease record without projecting its contents."""
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
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
