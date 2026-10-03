"""Machine-lock helpers the test session needs and production does not.

Production acquires the machine lock through ``acquire_machine_lock_lease``
and releases the exact lease object it was handed; a test that only asks "was
it won, and by whom" has no lease to carry, so the pid-only pair is here. Both
reach the lease registry through the module that owns it.
"""

from __future__ import annotations

from .. import _machine_lock
from .._machine_lock import (
    acquire_machine_lock_lease,
    machine_lock_path,
    release_machine_lock_lease,
)
from .._test_isolation import enforce_pytest_managed_singleton_containment


def acquire_machine_lock() -> tuple[bool, int]:
    """Acquire the machine lock, reporting only whether it was won and by whom."""
    lease, holder = acquire_machine_lock_lease()
    return (lease is not None, holder)


def release_machine_lock() -> None:
    """Release the machine-scoped service lock if this process holds it.

    Containment is enforced before the registry is consulted, so an unsafe
    configured anchor is refused whether or not a lease is held.
    """
    path = machine_lock_path()
    enforce_pytest_managed_singleton_containment(
        operation="release the machine service lock",
        targets=(path,),
    )
    with _machine_lock._lease_guard:
        lease = _machine_lock._held_leases.get(str(path))
    if lease is None:
        return
    release_machine_lock_lease(lease)
