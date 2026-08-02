"""CPU-only borrower lease tests using real OS lock holders and HTTP routes."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, Protocol

import pytest
from starlette.testclient import TestClient

from ..config._settings import reset_config
from ..config._types import EnvVar
from ..gpu_borrow_lease import (
    BorrowerLeaseStatus,
    _read_recorded_capability,
    acquire_gpu_borrow_lease,
    borrower_lease_status,
    gpu_borrow_lease_path,
    release_gpu_borrow_lease,
)
from ..server import ServerRouteRuntime, create_http_app
from ..server._lifespan import _borrower_lease_recovery_tick
from ..service import ServiceRegistry
from ._child_signal import await_marker, child_stderr

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.unit]

_TOKEN = "gpu-borrow-lease-test-token"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}
_PROCESS_TIMEOUT_SECONDS = 10.0

_CAPTURED_AUTHORITY_SCENARIO = """
import os
import pickle
import subprocess
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
identity_lock_path = Path(sys.argv[2])
case = sys.argv[3]
root.mkdir(parents=True, exist_ok=True)
(root / "status").mkdir(exist_ok=True)
(root / "qdrant" / "storage").mkdir(parents=True, exist_ok=True)
os.environ["_VAULTSPEC_RAG_PYTEST_SINGLETON_BOOTSTRAP"] = "1"
os.environ["_VAULTSPEC_RAG_PYTEST_SINGLETON_ACTIVE"] = "0"
os.environ.pop("_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT", None)
os.environ["VAULTSPEC_RAG_STATUS_DIR"] = str(root / "status")
os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = str(
    identity_lock_path.parent / "storage"
)

from vaultspec_rag._anchor_claim import claim_anchor, release_anchor_claim
from vaultspec_rag._machine_lock import (
    CapturedMachineLockWitness,
    PreIsolationMachineLock,
    capture_pre_isolation_machine_lock,
    revalidate_captured_machine_lock,
)
from vaultspec_rag._test_isolation import (
    ManagedSingletonIsolationError,
    register_pytest_singleton_root,
)
from vaultspec_rag.gpu_borrow_lease import (
    CapturedBorrowerLeaseAuthority,
    acquire_gpu_borrow_lease_for_captured_authority,
    mint_captured_borrower_lease_authority,
    release_gpu_borrow_lease,
)
from vaultspec_rag.tests._child_signal import await_marker

anchor = identity_lock_path.with_name("gpu-borrower.lock")

_HOLD_CAPTURED_IDENTITY = '''
import os
import sys
import time
from pathlib import Path

from vaultspec_rag._anchor_claim import (
    claim_anchor,
    record_claim_owner,
    release_anchor_claim,
)
from vaultspec_rag.tests._child_signal import publish_marker

identity = Path(sys.argv[1])
ready = Path(sys.argv[2])
stop = Path(sys.argv[3])
claim = claim_anchor(identity, pid_record=True, create_parent=True)
assert claim.descriptor is not None, claim
try:
    record_claim_owner(claim.descriptor)
    publish_marker(ready, str(os.getpid()))
    while not stop.exists():
        time.sleep(0.01)
finally:
    release_anchor_claim(claim.descriptor, pid_record=True)
'''

def probe() -> str:
    claim = claim_anchor(anchor, pid_record=True, create_parent=True)
    try:
        return claim.outcome.value
    finally:
        if claim.descriptor is not None:
            release_anchor_claim(claim.descriptor, pid_record=True)

ready_path = root / "identity-holder-ready"
stop_path = root / "identity-holder-stop"
# The holder inherits this process's stderr rather than owning a pipe: the
# test runs this scenario through ``subprocess.run``, which drains that
# stream concurrently, so the holder can never block writing a traceback -
# and its diagnostics land in the stderr the test already reports.
holder = subprocess.Popen(
    [
        sys.executable,
        "-c",
        _HOLD_CAPTURED_IDENTITY,
        str(identity_lock_path),
        str(ready_path),
        str(stop_path),
    ],
    stderr=sys.stderr,
    text=True,
)
try:
    reported = await_marker(ready_path, holder, timeout=10.0)
    if reported is None:
        raise RuntimeError("captured identity holder did not start")
    holder_pid = int(reported)
    captured = capture_pre_isolation_machine_lock()
    if captured is None or captured.holder_pid != holder_pid:
        raise RuntimeError("pre-root machine capture did not recover its holder")
    witness = captured.witness
    try:
        PreIsolationMachineLock(
            witness=witness,
            identity_lock_path=identity_lock_path,
            discovery_path=identity_lock_path.with_name("service.json"),
            holder_pid=holder_pid,
        )
    except TypeError:
        pass
    else:
        raise RuntimeError("machine lock projection had a public constructor")
    if "service.lock" in repr(witness):
        raise RuntimeError("machine witness repr projected its private identity")
    try:
        pickle.dumps(witness)
    except TypeError:
        pass
    else:
        raise RuntimeError("machine witness was serializable")
    forged_witness = object.__new__(CapturedMachineLockWitness)
    if revalidate_captured_machine_lock(forged_witness) is not None:
        raise RuntimeError("forged machine witness revalidated")
    try:
        mint_captured_borrower_lease_authority(identity_lock_path)
    except PermissionError:
        pass
    else:
        raise RuntimeError("raw identity path minted a borrower authority")
    authority = mint_captured_borrower_lease_authority(witness)
    try:
        mint_captured_borrower_lease_authority(witness)
    except PermissionError:
        pass
    else:
        raise RuntimeError("machine witness minted multiple borrower authorities")
    if "gpu-borrower.lock" in repr(authority):
        raise RuntimeError("authority repr projected its private anchor")
    try:
        pickle.dumps(authority)
    except TypeError:
        pass
    else:
        raise RuntimeError("authority was serializable")
    try:
        acquire_gpu_borrow_lease_for_captured_authority(authority)
    except ManagedSingletonIsolationError:
        pass
    else:
        raise RuntimeError("authority acquired before root registration")

    register_pytest_singleton_root(root)
    revalidated = revalidate_captured_machine_lock(witness)
    if (
        revalidated is None
        or revalidated is captured
        or revalidated.identity_lock_path != captured.identity_lock_path
        or revalidated.discovery_path != captured.discovery_path
        or revalidated.holder_pid != holder_pid
    ):
        raise RuntimeError("captured machine witness did not revalidate live holder")
    try:
        mint_captured_borrower_lease_authority(witness)
    except ManagedSingletonIsolationError:
        pass
    else:
        raise RuntimeError("authority minted after root registration")
    forged = object.__new__(CapturedBorrowerLeaseAuthority)
    try:
        acquire_gpu_borrow_lease_for_captured_authority(forged)
    except PermissionError:
        pass
    else:
        raise RuntimeError("forged authority was accepted")

    if case == "contended":
        borrower_holder = claim_anchor(anchor, pid_record=True, create_parent=True)
        if borrower_holder.descriptor is None:
            raise RuntimeError("test holder did not acquire the borrower anchor")
        try:
            if acquire_gpu_borrow_lease_for_captured_authority(authority) is not None:
                raise RuntimeError("contended authority acquired the borrower anchor")
        finally:
            release_anchor_claim(borrower_holder.descriptor, pid_record=True)
        if probe() != "held":
            raise RuntimeError(
                "borrower anchor was not released after contention holder"
            )
        try:
            acquire_gpu_borrow_lease_for_captured_authority(authority)
        except PermissionError:
            result = "contention-consumed"
        else:
            raise RuntimeError("contended authority was reusable")
    elif case == "faulted":
        anchor.mkdir()
        try:
            acquire_gpu_borrow_lease_for_captured_authority(authority)
        except OSError:
            pass
        else:
            raise RuntimeError("faulted authority acquired the borrower anchor")
        try:
            acquire_gpu_borrow_lease_for_captured_authority(authority)
        except PermissionError:
            result = "fault-consumed"
        else:
            raise RuntimeError("faulted authority was reusable")
    else:
        lease = acquire_gpu_borrow_lease_for_captured_authority(authority)
        if lease is None:
            raise RuntimeError("authority did not acquire its private borrower anchor")
        if lease.path != anchor:
            raise RuntimeError("lease did not retain the private registry anchor")
        if probe() != "contended":
            raise RuntimeError("lease did not hold a real OS borrower anchor")
        release_gpu_borrow_lease(lease)
        if probe() != "held":
            raise RuntimeError("release did not free the exact borrower anchor")
        try:
            acquire_gpu_borrow_lease_for_captured_authority(authority)
        except PermissionError:
            result = "one-shot-released"
        else:
            raise RuntimeError("released authority was reusable")
finally:
    if holder.poll() is None:
        stop_path.write_text("stop", encoding="ascii")
    try:
        holder.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        holder.kill()
        holder.wait(timeout=10.0)
    if holder.returncode != 0:
        raise RuntimeError(
            f"captured identity holder exited {holder.returncode}; its traceback "
            "is above on this stream"
        )
if revalidate_captured_machine_lock(witness) is not None:
    raise RuntimeError("stale machine witness revalidated after identity release")
print(result, flush=True)
"""


class BorrowerProcess(NamedTuple):
    """One spawned process holding the production borrower lease."""

    process: subprocess.Popen[str]
    capability: str


class BorrowerRoutes(NamedTuple):
    """A real no-lifespan route client and the registry it controls."""

    client: TestClient
    registry: ServiceRegistry


class _RouteResponse(Protocol):
    """The TestClient response surface this test needs without an HTTPX alias."""

    status_code: int

    def json(self) -> object:
        """Return the decoded response payload."""


_HOLD_GPU_BORROW_LEASE = """
import sys
import time
from vaultspec_rag.gpu_borrow_lease import (
    acquire_gpu_borrow_lease,
    release_gpu_borrow_lease,
)
from vaultspec_rag.tests._child_signal import publish_marker

lease = acquire_gpu_borrow_lease()
if lease is None:
    raise RuntimeError("child could not acquire the GPU borrower lease")
publish_marker(sys.argv[1], lease.capability)
try:
    time.sleep(120)
finally:
    release_gpu_borrow_lease(lease)
"""


@contextmanager
def _isolated_borrower_anchor(tmp_path: Path) -> Generator[None]:
    """Relocate the machine-global borrower anchor under the pytest root."""
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    previous_storage = os.environ.get(storage_key)
    os.environ[storage_key] = str(tmp_path / "qdrant" / "storage")
    reset_config()
    try:
        yield
    finally:
        if previous_storage is None:
            os.environ.pop(storage_key, None)
        else:
            os.environ[storage_key] = previous_storage
        reset_config()


@contextmanager
def _unavailable_borrower_anchor(tmp_path: Path) -> Generator[None]:
    """Point the borrower anchor under a real file, so its parent cannot exist."""
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    previous_storage = os.environ.get(storage_key)
    blocked_parent = tmp_path / "borrower-anchor-parent-file"
    blocked_parent.write_text("not a directory", encoding="ascii")
    os.environ[storage_key] = str(blocked_parent / "storage")
    reset_config()
    try:
        yield
    finally:
        if previous_storage is None:
            os.environ.pop(storage_key, None)
        else:
            os.environ[storage_key] = previous_storage
        reset_config()


@contextmanager
def _borrower_process() -> Generator[BorrowerProcess]:
    """Spawn a process that holds a real borrower lease and returns its secret."""
    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(delete=False) as marker_file:
        marker = Path(marker_file.name)
    marker.unlink()
    with child_stderr() as diagnostics:
        process = subprocess.Popen(
            [sys.executable, "-c", _HOLD_GPU_BORROW_LEASE, str(marker)],
            stdout=subprocess.DEVNULL,
            stderr=diagnostics.sink,
            text=True,
        )
        try:
            capability = await_marker(marker, process, timeout=_PROCESS_TIMEOUT_SECONDS)
            if capability is None:
                process.kill()
                process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
                raise AssertionError(
                    f"borrower child did not acquire the OS lease: {diagnostics.read()}"
                )
            yield BorrowerProcess(process, capability)
        finally:
            marker.unlink(missing_ok=True)
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
            assert process.poll() is not None, "borrower child did not exit"


@contextmanager
def _borrower_routes() -> Generator[BorrowerRoutes]:
    """Serve the production routes with no app lifespan or GPU startup."""
    registry = ServiceRegistry()
    app = create_http_app(
        ServerRouteRuntime(token=_TOKEN, registry=registry, port=8765),
        lifespan=None,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield BorrowerRoutes(client, registry)


def _response_payload(response: _RouteResponse) -> object:
    """Read one successful HTTP response as an opaque JSON value."""
    assert response.status_code == 200
    return response.json()


def _unrelated_capability() -> str:
    """Create a structurally valid capability that no child owns."""
    return (
        base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    )


def _await_borrower_release(capability: str) -> BorrowerLeaseStatus:
    """Wait only for the OS to finish releasing a just-crashed child lock."""
    deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
    status = borrower_lease_status(capability)
    while status is BorrowerLeaseStatus.HELD and time.monotonic() < deadline:
        time.sleep(0.05)
        status = borrower_lease_status(capability)
    return status


def _assert_borrower_refusal(
    response: _RouteResponse,
    reason: str,
    *,
    state: str,
) -> None:
    """Assert the one failure envelope without reading private lease data."""
    match _response_payload(response):
        case {
            "ok": False,
            "status": str() as status,
            "error": str() as error,
            "message": str() as message,
            "retryable": True,
            "quiesce": {"state": str() as quiesce_state},
        }:
            assert status == reason
            assert error == reason
            assert message == reason
            assert quiesce_state == state
        case payload:
            pytest.fail(f"unexpected borrower refusal envelope: {payload!r}")


def _assert_pause_success(response: _RouteResponse) -> None:
    """Assert the achieved safe-quiescence shape from the production route."""
    match _response_payload(response):
        case {
            "ok": True,
            "status": "quiesced",
            "quiesce": {
                "state": "quiesced",
                "safe_to_borrow_gpu": True,
            },
        }:
            return
        case payload:
            pytest.fail(f"unexpected achieved pause envelope: {payload!r}")


def _assert_resume_success(response: _RouteResponse) -> None:
    """Assert the achieved running shape from the production route."""
    match _response_payload(response):
        case {
            "ok": True,
            "status": "running",
            "quiesce": {
                "state": "running",
                "safe_to_borrow_gpu": False,
            },
        }:
            return
        case payload:
            pytest.fail(f"unexpected achieved resume envelope: {payload!r}")


def test_os_lease_contends_and_releases_after_borrower_crash(tmp_path: Path) -> None:
    """A crashed child frees the real OS borrower lock for the next holder."""
    with _isolated_borrower_anchor(tmp_path), _borrower_process() as borrower:
        assert borrower_lease_status(borrower.capability) is BorrowerLeaseStatus.HELD
        assert acquire_gpu_borrow_lease() is None

        borrower.process.kill()
        borrower.process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
        assert borrower.process.poll() is not None, "borrower child did not terminate"

        assert (
            _await_borrower_release(borrower.capability) is BorrowerLeaseStatus.NOT_HELD
        )
        successor = acquire_gpu_borrow_lease()
        assert successor is not None
        release_gpu_borrow_lease(successor)


def _run_captured_authority_scenario(
    tmp_path: Path,
    case: str,
) -> subprocess.CompletedProcess[str]:
    """Run one fresh bootstrap-to-registration authority flow in a real process."""
    root = tmp_path / "authority-session-root"
    identity_lock_path = (root / "captured-service" / "service.lock").resolve()
    environment = os.environ.copy()
    environment.pop("PYTEST_CURRENT_TEST", None)
    environment["_VAULTSPEC_RAG_PYTEST_SINGLETON_ACTIVE"] = "0"
    environment["_VAULTSPEC_RAG_PYTEST_SINGLETON_BOOTSTRAP"] = "1"
    environment.pop("_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT", None)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _CAPTURED_AUTHORITY_SCENARIO,
            str(root),
            str(identity_lock_path),
            case,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=_PROCESS_TIMEOUT_SECONDS,
        env=environment,
    )


def test_captured_authority_is_bootstrap_only_one_shot_and_releases_exact_anchor(
    tmp_path: Path,
) -> None:
    """The opaque authority alone reaches its private sibling anchor once.

    Mutation it catches: retaining the original path in the target or admitting
    a captured authority twice.  Either flaw would reopen a general pytest path
    escape or let a stale capture claim an anchor after its original handoff.
    """
    scenario = _run_captured_authority_scenario(tmp_path, "released")

    assert scenario.returncode == 0, scenario.stderr
    assert scenario.stdout.strip() == "one-shot-released"


def test_captured_authority_contention_consumes_the_private_handle(
    tmp_path: Path,
) -> None:
    """A contended claim consumes the authority before the OS result is known.

    Mutation it catches: consuming only after a successful claim.  A caller
    could otherwise retry the same capture after a different service takes or
    releases the one private borrower anchor.
    """
    scenario = _run_captured_authority_scenario(tmp_path, "contended")

    assert scenario.returncode == 0, scenario.stderr
    assert scenario.stdout.strip() == "contention-consumed"


def test_captured_authority_fault_consumes_the_private_handle(
    tmp_path: Path,
) -> None:
    """A claim fault consumes the authority before the broken path is observed.

    Mutation it catches: removing the registry entry only after a successful
    claim.  A transient path fault could then leave an opaque authority live for
    a later retry against a changed service anchor.
    """
    scenario = _run_captured_authority_scenario(tmp_path, "faulted")

    assert scenario.returncode == 0, scenario.stderr
    assert scenario.stdout.strip() == "fault-consumed"


def test_authenticated_routes_bind_and_require_the_live_borrower_capability(
    tmp_path: Path,
) -> None:
    """Only the holder can bind safe quiescence, then resume it once."""
    with (
        _isolated_borrower_anchor(tmp_path),
        _borrower_process() as borrower,
        _borrower_routes() as routes,
    ):
        invalid = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": ""},
        )
        _assert_borrower_refusal(
            invalid,
            "invalid_borrower_capability",
            state="running",
        )

        wrong_before_bind = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": _unrelated_capability()},
        )
        _assert_borrower_refusal(
            wrong_before_bind,
            "borrower_capability_invalid",
            state="running",
        )

        _assert_pause_success(
            routes.client.post(
                "/pause",
                headers=_HEADERS,
                json={"borrower_capability": borrower.capability},
            )
        )

        wrong_bound_pause = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": _unrelated_capability()},
        )
        _assert_borrower_refusal(
            wrong_bound_pause,
            "borrower_lease_mismatch",
            state="quiesced",
        )

        empty_resume = routes.client.post(
            "/resume",
            headers=_HEADERS,
            json={},
        )
        _assert_borrower_refusal(
            empty_resume,
            "borrower_lease_required",
            state="quiesced",
        )

        wrong_bound_resume = routes.client.post(
            "/resume",
            headers=_HEADERS,
            json={"borrower_capability": _unrelated_capability()},
        )
        _assert_borrower_refusal(
            wrong_bound_resume,
            "borrower_lease_mismatch",
            state="quiesced",
        )

        _assert_resume_success(
            routes.client.post(
                "/resume",
                headers=_HEADERS,
                json={"borrower_capability": borrower.capability},
            )
        )


def test_lost_bound_lease_auto_resumes_but_manual_quiescence_stays_held(
    tmp_path: Path,
) -> None:
    """The heartbeat tick resumes only the quiescence that has a lost binding."""
    with _isolated_borrower_anchor(tmp_path), _borrower_routes() as routes:
        _assert_pause_success(routes.client.post("/pause", headers=_HEADERS))
        assert routes.registry.resume_lost_borrower_lease() is None
        assert routes.registry.quiesce_snapshot().state.value == "quiesced"
        _assert_resume_success(routes.client.post("/resume", headers=_HEADERS))

        with _borrower_process() as borrower:
            _assert_pause_success(
                routes.client.post(
                    "/pause",
                    headers=_HEADERS,
                    json={"borrower_capability": borrower.capability},
                )
            )
            with _unavailable_borrower_anchor(tmp_path):
                assert (
                    borrower_lease_status(borrower.capability)
                    is BorrowerLeaseStatus.UNAVAILABLE
                )
                _assert_borrower_refusal(
                    routes.client.post(
                        "/pause",
                        headers=_HEADERS,
                        json={"borrower_capability": borrower.capability},
                    ),
                    "borrower_lease_unavailable",
                    state="quiesced",
                )
                asyncio.run(_borrower_lease_recovery_tick(routes.registry))
                assert routes.registry.quiesce_snapshot().state.value == "quiesced"
            borrower.process.kill()
            borrower.process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
            assert borrower.process.poll() is not None, (
                "borrower child did not terminate"
            )
            assert (
                _await_borrower_release(borrower.capability)
                is BorrowerLeaseStatus.NOT_HELD
            )

            with _borrower_process():
                assert (
                    borrower_lease_status(borrower.capability)
                    is BorrowerLeaseStatus.CAPABILITY_INVALID
                )
                asyncio.run(_borrower_lease_recovery_tick(routes.registry))
                assert routes.registry.quiesce_snapshot().state.value == "quiesced"

            asyncio.run(_borrower_lease_recovery_tick(routes.registry))

        assert routes.registry.quiesce_snapshot().state.value == "running"


def test_valid_capability_without_a_live_lease_is_refused(tmp_path: Path) -> None:
    """A syntactically valid secret cannot replace active OS lock ownership."""
    with _isolated_borrower_anchor(tmp_path), _borrower_routes() as routes:
        refused = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": _unrelated_capability()},
        )
        _assert_borrower_refusal(
            refused,
            "borrower_lease_not_held",
            state="running",
        )


# Verifications taken against a holder that is republishing its private lease
# record. The truncate-then-write order this guards against leaves the anchor
# empty for a slice of every publication, so a few hundred samples put several
# hits inside a reverted build and none inside a correct one.
_LEASE_RACE_SAMPLES = 400

_REPUBLISH_LEASE_RECORD = """
import os
import sys
from pathlib import Path

from vaultspec_rag._anchor_claim import (
    claim_anchor,
    publish_anchor_record,
    release_anchor_claim,
)
from vaultspec_rag.gpu_borrow_lease import _LEASE_RECORD_WIDTH, _new_capability
from vaultspec_rag.tests._child_signal import publish_marker

anchor = Path(sys.argv[1])
marker = sys.argv[2]
stop = Path(sys.argv[3])
claim = claim_anchor(anchor, pid_record=True, create_parent=True)
assert claim.descriptor is not None, claim
record = {"pid": os.getpid(), "capability": _new_capability()}
try:
    publish_anchor_record(claim.descriptor, record, width=_LEASE_RECORD_WIDTH)
    publish_marker(marker, str(record["capability"]))
    while not stop.exists():
        publish_anchor_record(claim.descriptor, record, width=_LEASE_RECORD_WIDTH)
finally:
    release_anchor_claim(claim.descriptor, pid_record=True)
"""


def test_republished_lease_record_is_never_verified_invalid(tmp_path: Path) -> None:
    """A holder replacing its private record never reads as capability-invalid.

    The record is published in place - the OS lock making the lease
    authoritative is bound to the anchor file, so it cannot be swapped in by
    rename - which makes write order the whole guarantee. Mutation: restoring
    a truncate-then-write order in the shared record publication empties the
    anchor between the two calls, and this assertion fires with a non-zero
    count of held-lease-read-as-invalid verifications.
    """
    with _isolated_borrower_anchor(tmp_path):
        anchor = gpu_borrow_lease_path()
        marker = tmp_path / "republish-ready"
        stop = tmp_path / "republish-stop"
        with child_stderr() as diagnostics:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _REPUBLISH_LEASE_RECORD,
                    str(anchor),
                    str(marker),
                    str(stop),
                ],
                stdout=subprocess.DEVNULL,
                stderr=diagnostics.sink,
                text=True,
            )
            try:
                capability = await_marker(
                    marker, process, timeout=_PROCESS_TIMEOUT_SECONDS
                )
                assert capability is not None, (
                    f"republishing lease holder did not start: {diagnostics.read()}"
                )
                # A fixed sample COUNT, not a fixed duration: the count carries
                # the statistical power, and a loaded machine must not quietly
                # reduce it to a handful of reads that prove nothing.
                torn = 0
                samples = 0
                deadline = time.monotonic() + _PROCESS_TIMEOUT_SECONDS
                while samples < _LEASE_RACE_SAMPLES:
                    assert time.monotonic() < deadline, (
                        f"only reached {samples} samples"
                    )
                    status = borrower_lease_status(capability)
                    samples += 1
                    if status is not BorrowerLeaseStatus.HELD:
                        torn += 1
                assert torn == 0, (
                    f"{torn} of {samples} verifications of a held lease could "
                    "not read its capability while the holder republished its "
                    "record"
                )
            finally:
                stop.write_text("stop", encoding="ascii")
                try:
                    process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
                assert process.returncode == 0, diagnostics.read()


def test_unpadded_lease_record_from_an_earlier_build_is_still_read(
    tmp_path: Path,
) -> None:
    """The compact record an earlier build wrote still yields its capability.

    Builds that predate the fixed-width frame wrote the same two-key JSON
    object without padding, so the reader must recover it unchanged. Mutation:
    requiring the padded width, or parsing anything but the leading JSON
    document, loses this record and fails the equality below.
    """
    capability = _unrelated_capability()
    record_path = tmp_path / "gpu-borrower.lock"
    record_path.write_text(
        json.dumps({"pid": 12345, "capability": capability}),
        encoding="utf-8",
    )

    assert _read_recorded_capability(record_path) == capability


def test_published_lease_record_stays_readable_as_plain_json(
    tmp_path: Path,
) -> None:
    """The frame a build with no knowledge of the padding still parses whole.

    Earlier readers parse the entire file as one JSON document, so the fixed
    width must be carried as trailing whitespace inside that same document.
    Mutation: padding with anything JSON does not ignore, or appending the
    width outside the object, fails this parse.
    """
    with _isolated_borrower_anchor(tmp_path):
        lease = acquire_gpu_borrow_lease()
        assert lease is not None
        try:
            parsed = json.loads(gpu_borrow_lease_path().read_text(encoding="utf-8"))
            assert parsed == {"pid": os.getpid(), "capability": lease.capability}
        finally:
            release_gpu_borrow_lease(lease)
