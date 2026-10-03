"""Pre-isolation capture of the live machine service, for the GPU tiers.

A GPU tier borrows the device from the resident service, and has to name that
service before the pytest session redirects the managed paths it was found
through. Production borrows from the service it discovers at the configured
paths; only a test session needs the frozen identity, so the capture lives
here while the paths, witnesses and lease authority it freezes remain owned by
the modules that mint them.
"""

from __future__ import annotations

from .. import gpu_borrow_lease
from .._machine_lock import CapturedMachineLockWitness
from .._test_isolation import (
    ManagedSingletonIsolationError,
    pytest_singleton_bootstrap_window,
)
from ..cli._gpu_lease import (
    BorrowerServiceTarget,
    _matching_health_identity,
    _read_health_evidence,
    _token_sha256,
)
from ..gpu_borrow_lease import CapturedBorrowerLeaseAuthority
from ..serviceclient._compat import classify_service_version
from ..serviceclient._discovery import (
    PreIsolationMachinePointer,
    _resolve_machine_pointer_at_path,
)
from ._machine_lock_fixtures import (
    capture_pre_isolation_machine_lock,
    consume_captured_machine_lock_for_borrower_authority,
)


def capture_pre_isolation_machine_pointer() -> PreIsolationMachinePointer | None:
    """Capture the configured original pointer without accepting caller paths.

    This is the sole pre-root bridge for captured GPU borrowing. The machine
    lock module owns no-create lock observation, and the discovery module owns
    exactly the same pointer evaluation the ordinary resolver uses. Neither
    performs a write, retains a claim, or lets a caller choose an observed path.
    """
    machine_lock = capture_pre_isolation_machine_lock()
    if machine_lock is None:
        return None
    return PreIsolationMachinePointer(
        observation=machine_lock,
        resolution=_resolve_machine_pointer_at_path(
            machine_lock.discovery_path,
            holder_pid=machine_lock.holder_pid,
        ),
    )


def mint_captured_borrower_lease_authority(
    witness: object,
) -> CapturedBorrowerLeaseAuthority:
    """Mint one authority for a pre-registration validated service target.

    Only the bootstrap window can mint. The machine-lock registry derives and
    retains the borrower anchor from one opaque witness; callers receive no
    anchor path and cannot select one for a later acquisition.
    """
    if not isinstance(witness, CapturedMachineLockWitness):
        raise PermissionError(
            "a captured GPU borrower lease requires a machine witness"
        )
    with pytest_singleton_bootstrap_window(
        operation="mint a captured GPU borrower lease authority"
    ):
        path = consume_captured_machine_lock_for_borrower_authority(witness)
        authority = object.__new__(CapturedBorrowerLeaseAuthority)
        with gpu_borrow_lease._lease_guard:
            gpu_borrow_lease._captured_authority_paths[authority] = path
    return authority


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
