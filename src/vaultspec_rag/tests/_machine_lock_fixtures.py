"""Machine-lock helpers the test session needs and production does not.

Two kinds live here. Production acquires the machine lock through
``acquire_machine_lock_lease`` and releases the exact lease object it was
handed; a test that only asks "was it won, and by whom" has no lease to carry,
so the pid-only pair is here. And production borrows the GPU from the service
it discovers at the configured paths, so capturing a machine lock identity
*before* the session redirects those paths is the test session's own need.
Both reach the registries through the module that owns them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import _machine_lock
from .._machine_lock import (
    CapturedMachineLockWitness,
    _CapturedMachineLockRecord,
    _probe_existing_machine_lock_holder,
    _project_captured_machine_lock,
    acquire_machine_lock_lease,
    machine_discovery_path,
    machine_lock_path,
    release_machine_lock_lease,
)
from .._test_isolation import (
    ManagedSingletonIsolationError,
    enforce_pytest_managed_singleton_containment,
    pytest_singleton_bootstrap_window,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .._machine_lock import PreIsolationMachineLock

#: Witnesses already spent on a borrower authority. The records themselves
#: stay in the owning module, which still revalidates them; only "this one
#: has been consumed" belongs to the one caller that consumes. Mutated under
#: that module's registry lock, so the lookup and the claim stay one step.
_captured_machine_lock_minted: set[CapturedMachineLockWitness] = set()


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


def capture_pre_isolation_machine_lock() -> PreIsolationMachineLock | None:
    """Capture one existing original machine lock without path input or writes.

    This is the only bridge to the private raw-path probe. It derives the
    configured machine identity and discovery paths before pytest redirects
    them, then returns evidence only when a positive owner PID is recovered
    from a currently contended lock.
    """
    try:
        with pytest_singleton_bootstrap_window(
            operation="capture a pre-isolation machine lock witness"
        ):
            try:
                identity_lock_path = machine_lock_path().resolve(strict=False)
                discovery_path = machine_discovery_path().resolve(strict=False)
            except (OSError, RuntimeError, ValueError):
                return None
            holder_pid = _probe_existing_machine_lock_holder(identity_lock_path)
            if holder_pid is None:
                return None
            witness = object.__new__(CapturedMachineLockWitness)
            record = _CapturedMachineLockRecord(
                identity_lock_path=identity_lock_path,
                discovery_path=discovery_path,
                holder_pid=holder_pid,
            )
            with _machine_lock._captured_machine_lock_guard:
                _machine_lock._captured_machine_lock_records[witness] = record
    except ManagedSingletonIsolationError:
        return None
    return _project_captured_machine_lock(witness, record)


def consume_captured_machine_lock_for_borrower_authority(witness: object) -> Path:
    """Consume one witness for a borrower authority and derive its sibling."""
    if not isinstance(witness, CapturedMachineLockWitness):
        raise PermissionError(
            "a captured GPU borrower lease requires a machine witness"
        )
    with _machine_lock._captured_machine_lock_guard:
        record = _machine_lock._captured_machine_lock_records.get(witness)
        if record is None or witness in _captured_machine_lock_minted:
            raise PermissionError(
                "the captured machine lock witness is stale or consumed"
            )
        _captured_machine_lock_minted.add(witness)
    return record.identity_lock_path.with_name("gpu-borrower.lock")
