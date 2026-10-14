"""Borrower lease tests using real OS lock holders and HTTP routes.

A served registry lends its GPU through the owner anchor it is given. The tests
that drive a borrower's pause hand it a private one, so none claims the
machine's. The two that ask the machine's own anchor are integration tests, and
every other test is a unit test.
"""

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
import typer
from starlette.testclient import TestClient

from .._anchor_claim import read_anchor_record
from .._gpu_owner import gpu_owner_anchor_path, observation_wire
from .._process_probe import pid_start_time, process_lineage
from ..config._types import EnvVar
from ..gpu_borrow_lease import (
    BorrowerLeaseStatus,
    BorrowerState,
    _read_recorded_capability,
    acquire_gpu_borrow_lease,
    borrower_lease_holder_pid,
    borrower_lease_status,
    gpu_borrow_lease_path,
    observe_gpu_borrower,
    release_gpu_borrow_lease,
)
from ..server import ServerRouteRuntime, create_http_app
from ..server._lifespan import _borrower_lease_recovery_tick
from ..service import ServiceRegistry
from ._child_signal import (
    CHILD_PROCESS_TIMEOUT_SECONDS,
    await_marker,
    child_stderr,
)
from ._config_fixtures import reset_config
from ._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Generator


_TOKEN = "gpu-borrow-lease-test-token"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


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
            capability = await_marker(
                marker, process, timeout=CHILD_PROCESS_TIMEOUT_SECONDS
            )
            if capability is None:
                process.kill()
                process.wait(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
                raise AssertionError(
                    f"borrower child did not acquire the OS lease: {diagnostics.read()}"
                )
            yield BorrowerProcess(process, capability)
        finally:
            marker.unlink(missing_ok=True)
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
            assert process.poll() is not None, "borrower child did not exit"


@contextmanager
def _borrower_routes(owner_anchor: Path) -> Generator[BorrowerRoutes]:
    """Serve the production routes with no app lifespan or GPU startup.

    The registry lends through *owner_anchor*, which the caller owns.
    """
    registry = ServiceRegistry(gpu_owner_anchor=owner_anchor)
    app = create_http_app(
        ServerRouteRuntime(token=_TOKEN, registry=registry, port=8765),
        lifespan=None,
    )
    with TestClient(
        app, raise_server_exceptions=False, base_url="http://127.0.0.1"
    ) as client:
        yield BorrowerRoutes(client, registry)


def _borrower_pause(routes: BorrowerRoutes, capability: str) -> _RouteResponse:
    """Send one borrower pause for *capability* through the production route."""
    return routes.client.post(
        "/pause",
        headers=_HEADERS,
        json={"borrower_capability": capability},
    )


def _borrower_resume(routes: BorrowerRoutes, capability: str) -> _RouteResponse:
    """Send one borrower resume for *capability* through the production route."""
    return routes.client.post(
        "/resume",
        headers=_HEADERS,
        json={"borrower_capability": capability},
    )


def _kill_borrower(borrower: BorrowerProcess) -> None:
    """Hard-kill one borrower and wait until the OS has freed its lease."""
    borrower.process.kill()
    borrower.process.wait(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
    assert borrower.process.poll() is not None, "borrower child did not terminate"
    assert _await_borrower_release(borrower.capability) is BorrowerLeaseStatus.NOT_HELD


def _assert_bound_witness(response: _RouteResponse, *, bound: bool) -> None:
    """Assert the published ownership witness on one lifecycle envelope."""
    match _response_payload(response):
        case {"quiesce": {"borrower_bound": bool() as witness}}:
            assert witness is bound
        case payload:
            pytest.fail(f"envelope carried no ownership witness: {payload!r}")


def _assert_achieved_state(response: _RouteResponse, state: str) -> None:
    """Assert one achieved lifecycle transition reached *state*."""
    match _response_payload(response):
        case {"ok": True, "quiesce": {"state": str() as reached}}:
            assert reached == state
        case payload:
            pytest.fail(f"unexpected achieved envelope: {payload!r}")


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
    deadline = time.monotonic() + CHILD_PROCESS_TIMEOUT_SECONDS
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
            # The code names the condition for a machine; the message has to
            # explain it to a person. Asserting only "not the code" would pass
            # for a single word, so require prose: several words, ending in a
            # full stop, and never the bare token an operator cannot act on.
            assert message != reason
            assert message.endswith(".")
            assert len(message.split()) >= 5
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


@pytest.mark.unit
def test_os_lease_contends_and_releases_after_borrower_crash(tmp_path: Path) -> None:
    """A crashed child frees the real OS borrower lock for the next holder."""
    with _isolated_borrower_anchor(tmp_path), _borrower_process() as borrower:
        assert borrower_lease_status(borrower.capability) is BorrowerLeaseStatus.HELD
        assert acquire_gpu_borrow_lease() is None

        borrower.process.kill()
        borrower.process.wait(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
        assert borrower.process.poll() is not None, "borrower child did not terminate"

        assert (
            _await_borrower_release(borrower.capability) is BorrowerLeaseStatus.NOT_HELD
        )
        successor = acquire_gpu_borrow_lease()
        assert successor is not None
        release_gpu_borrow_lease(successor)


@pytest.mark.unit
def test_authenticated_routes_bind_and_require_the_live_borrower_capability(
    tmp_path: Path, private_owner_anchor: Path
) -> None:
    """Only the holder can bind safe quiescence, then resume it once."""
    with (
        _isolated_borrower_anchor(tmp_path),
        _borrower_process() as borrower,
        _borrower_routes(private_owner_anchor) as routes,
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


@pytest.mark.unit
def test_lost_bound_lease_auto_resumes_but_manual_quiescence_stays_held(
    tmp_path: Path, private_owner_anchor: Path
) -> None:
    """The heartbeat tick resumes only the quiescence that has a lost binding.

    A different live lease holder is left to take the hold over; the tick
    clears it only once no borrower holds the lease. Mutation: reverting the
    takeover fails the successor's pause with a lease mismatch.
    """
    with (
        _isolated_borrower_anchor(tmp_path),
        _borrower_routes(private_owner_anchor) as routes,
    ):
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
            borrower.process.wait(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
            assert borrower.process.poll() is not None, (
                "borrower child did not terminate"
            )
            assert (
                _await_borrower_release(borrower.capability)
                is BorrowerLeaseStatus.NOT_HELD
            )

            with _borrower_process() as successor:
                assert (
                    borrower_lease_status(borrower.capability)
                    is BorrowerLeaseStatus.CAPABILITY_INVALID
                )
                # A different live lease holder is not proof the pause was
                # abandoned: it is the borrower that takes the hold over in its
                # own pause, so the heartbeat leaves the hold standing for it
                # and the device is not rebuilt in between.
                asyncio.run(_borrower_lease_recovery_tick(routes.registry))
                assert routes.registry.quiesce_snapshot().state.value == "quiesced"
                _assert_achieved_state(
                    _borrower_pause(routes, successor.capability), "quiesced"
                )

            # The successor exited too, so the hold it inherited clears.
            asyncio.run(_borrower_lease_recovery_tick(routes.registry))

        assert routes.registry.quiesce_snapshot().state.value == "running"


@pytest.mark.unit
def test_a_hold_is_protected_while_its_borrower_still_holds_the_lease(
    tmp_path: Path, private_owner_anchor: Path
) -> None:
    """No other capability can act on a hold whose borrower holds the lease.

    The hold survives a stranger's pause and the heartbeat, and stays
    releasable by its own borrower. Mutation: letting a pause carrying any
    different capability replace the binding, instead of only one that verifies
    against the live lease, fails the refusal assertion below.
    """
    with (
        _isolated_borrower_anchor(tmp_path),
        _borrower_process() as borrower,
        _borrower_routes(private_owner_anchor) as routes,
    ):
        _assert_pause_success(_borrower_pause(routes, borrower.capability))

        refused = _borrower_pause(routes, _unrelated_capability())
        _assert_borrower_refusal(refused, "borrower_lease_mismatch", state="quiesced")
        _assert_bound_witness(refused, bound=True)

        asyncio.run(_borrower_lease_recovery_tick(routes.registry))
        assert routes.registry.quiesce_snapshot().state.value == "quiesced"

        released = _borrower_resume(routes, borrower.capability)
        _assert_achieved_state(released, "running")
        _assert_bound_witness(released, bound=False)


@pytest.mark.unit
def test_a_successor_takes_over_a_hold_whose_borrower_is_gone(
    tmp_path: Path, private_owner_anchor: Path
) -> None:
    """A borrower started after a hard-killed one is served, not refused.

    The service is still bound to the dead borrower's capability, because the
    heartbeat has not yet noticed the lease is free. The successor holds the
    exclusive lease, which proves the first released it, so its pause takes the
    hold over without a resume in between and the loan of the GPU moves to it.
    Mutation: reverting the validation to refuse every different capability
    against a binding fails the takeover assertion with a lease mismatch.
    """
    with (
        _isolated_borrower_anchor(tmp_path),
        _borrower_routes(private_owner_anchor) as routes,
        _borrower_process() as first,
    ):
        _assert_pause_success(_borrower_pause(routes, first.capability))
        _kill_borrower(first)
        assert routes.registry.quiesce_snapshot().borrower_bound is True

        with _borrower_process() as successor:
            taken = _borrower_pause(routes, successor.capability)
            _assert_achieved_state(taken, "quiesced")
            _assert_bound_witness(taken, bound=True)
            holder = borrower_lease_holder_pid(successor.capability)
            lent = read_anchor_record(private_owner_anchor)

            stale = _borrower_resume(routes, first.capability)
            _assert_borrower_refusal(stale, "borrower_lease_mismatch", state="quiesced")

            _assert_resume_success(_borrower_resume(routes, successor.capability))

    assert holder is not None
    assert isinstance(lent, dict)
    assert lent["lent_to"] == holder


@pytest.mark.unit
def test_a_bound_borrower_is_lent_the_gpu_until_its_resume(
    tmp_path: Path, private_owner_anchor: Path
) -> None:
    """Binding lends the service's GPU to the borrower; resume takes it back.

    The served registry has loaded no model, so it does not own the GPU when
    the borrower arrives: the bind itself has to claim it before it can lend.
    """
    anchor = private_owner_anchor
    with (
        _isolated_borrower_anchor(tmp_path),
        _borrower_process() as borrower,
        _borrower_routes(private_owner_anchor) as routes,
    ):
        _assert_pause_success(
            routes.client.post(
                "/pause",
                headers=_HEADERS,
                json={"borrower_capability": borrower.capability},
            )
        )
        lent = read_anchor_record(anchor)
        holder = borrower_lease_holder_pid(borrower.capability)
        assert holder is not None
        holder_lineage = {entry.pid for entry in process_lineage(holder)}
        holder_start = pid_start_time(holder)
        stranger = borrower_lease_holder_pid(_unrelated_capability())

        _assert_resume_success(
            routes.client.post(
                "/resume",
                headers=_HEADERS,
                json={"borrower_capability": borrower.capability},
            )
        )
        reclaimed = read_anchor_record(anchor)

    # The lease names the borrower child itself (or, on Windows, the
    # interpreter its venv launcher started).
    assert borrower.process.pid in holder_lineage
    # Catches the bind no longer lending: the borrower and the test daemons
    # it starts would then be refused the GPU they were just granted.
    assert lent == {"pid": os.getpid(), "lent_to": holder, "lent_start": holder_start}
    # Catches resume leaving the loan open while the service reloads models.
    assert reclaimed == {"pid": os.getpid()}
    # A live lease names its holder only to the capability that holds it.
    assert stranger is None


@pytest.mark.unit
def test_a_borrower_is_refused_when_the_gpu_cannot_be_lent(
    tmp_path: Path, private_owner_anchor: Path
) -> None:
    """A pause whose loan was not recorded must not tell a borrower to proceed.

    Another process owns the GPU, so the service can neither claim nor lend
    it. Mutation: ignoring the loan's result in the pause route reports an
    achieved borrower pause here.
    """
    owner_script = (
        "import sys, time; from pathlib import Path; "
        "from vaultspec_rag._gpu_owner import require_gpu_ownership; "
        "require_gpu_ownership(anchor=Path(sys.argv[1])); "
        "Path(sys.argv[2]).write_text('1'); time.sleep(120)"
    )
    ready = tmp_path / "owner-ready"
    owner = subprocess.Popen(
        [sys.executable, "-c", owner_script, str(private_owner_anchor), str(ready)]
    )
    try:
        deadline = time.monotonic() + CHILD_PROCESS_TIMEOUT_SECONDS
        while not ready.exists():
            assert owner.poll() is None, "the owning process exited early"
            assert time.monotonic() < deadline, "the owning process never started"
            time.sleep(0.05)
        with (
            _isolated_borrower_anchor(tmp_path),
            _borrower_process() as borrower,
            _borrower_routes(private_owner_anchor) as routes,
        ):
            refused = routes.client.post(
                "/pause",
                headers=_HEADERS,
                json={"borrower_capability": borrower.capability},
            )
            routes.client.post(
                "/resume",
                headers=_HEADERS,
                json={"borrower_capability": borrower.capability},
            )
    finally:
        owner.kill()
        owner.wait(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)

    _assert_borrower_refusal(refused, "borrower_gpu_not_lendable", state="quiesced")


@pytest.mark.integration
def test_a_registry_given_no_anchor_lends_through_the_machines_own(
    tmp_path: Path,
) -> None:
    """With no anchor named, the lend is asked of the machine's, and refused there.

    The machine's anchor belongs to the resident service, and this process is
    only lent the GPU, so it cannot lend it onward and the loan the service
    recorded stays as it wrote it. A registry that lent through any other file
    would claim that file, record a loan on it and report success.

    Mutation: gave the registry a private anchor when none was named. Observed
    the refusal assertion fail on the lend succeeding; restoring the default
    passed.
    """
    machine_anchor = gpu_owner_anchor_path()
    registry = ServiceRegistry()
    with _isolated_borrower_anchor(tmp_path), _borrower_process() as borrower:
        loan = read_anchor_record(machine_anchor)
        lent = registry.lend_gpu_to_borrower(borrower.capability)
        after = read_anchor_record(machine_anchor)

    assert lent is False
    assert isinstance(loan, dict)
    assert after == loan


@pytest.mark.unit
def test_valid_capability_without_a_live_lease_is_refused(
    tmp_path: Path, private_owner_anchor: Path
) -> None:
    """A syntactically valid secret cannot replace active OS lock ownership."""
    with (
        _isolated_borrower_anchor(tmp_path),
        _borrower_routes(private_owner_anchor) as routes,
    ):
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


@pytest.mark.unit
def test_a_borrower_cannot_take_ownership_of_an_operator_held_pause(
    tmp_path: Path, private_owner_anchor: Path
) -> None:
    """An operator keeps the undo for the pause they asked for.

    This is the reproduction that failed before ownership was bound to the
    request that produced the state: the borrower's pause changed nothing, was
    answered as already-quiesced, and inherited the hold anyway, after which the
    operator's own resume was refused until the borrower exited.
    """
    with (
        _isolated_borrower_anchor(tmp_path),
        _borrower_process() as borrower,
        _borrower_routes(private_owner_anchor) as routes,
    ):
        operator_pause = routes.client.post("/pause", headers=_HEADERS, json={})
        _assert_pause_success(operator_pause)
        _assert_bound_witness(operator_pause, bound=False)

        stolen = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": borrower.capability},
        )
        _assert_borrower_refusal(stolen, "borrower_pause_not_owned", state="quiesced")
        _assert_bound_witness(stolen, bound=False)

        # The refusal changed no state, so the operator's own resume still works.
        operator_resume = routes.client.post("/resume", headers=_HEADERS, json={})
        _assert_achieved_state(operator_resume, "running")


@pytest.mark.unit
def test_a_borrower_repeating_its_own_pause_stays_idempotent(
    tmp_path: Path, private_owner_anchor: Path
) -> None:
    """Retry after a lost response must not read as an attempted takeover.

    The ownership rule refuses a pause that only observed an existing hold, and
    a borrower retrying its own call is exactly that shape. It is allowed
    because the binding it would be granted is the one it already holds.
    """
    with (
        _isolated_borrower_anchor(tmp_path),
        _borrower_process() as borrower,
        _borrower_routes(private_owner_anchor) as routes,
    ):
        first = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": borrower.capability},
        )
        _assert_pause_success(first)
        _assert_bound_witness(first, bound=True)

        retry = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": borrower.capability},
        )
        _assert_achieved_state(retry, "quiesced")
        _assert_bound_witness(retry, bound=True)


@pytest.mark.unit
def test_the_bound_witness_names_a_hold_without_naming_its_holder(
    tmp_path: Path, private_owner_anchor: Path
) -> None:
    """The witness says a hold is owned, never by whom, and clears on release."""
    with (
        _isolated_borrower_anchor(tmp_path),
        _borrower_process() as borrower,
        _borrower_routes(private_owner_anchor) as routes,
    ):
        paused = routes.client.post(
            "/pause",
            headers=_HEADERS,
            json={"borrower_capability": borrower.capability},
        )
        _assert_bound_witness(paused, bound=True)
        serialised = json.dumps(_response_payload(paused))
        assert borrower.capability not in serialised
        assert "pid" not in serialised

        released = routes.client.post(
            "/resume",
            headers=_HEADERS,
            json={"borrower_capability": borrower.capability},
        )
        _assert_achieved_state(released, "running")
        _assert_bound_witness(released, bound=False)


# Verifications taken against a holder that is republishing its private lease
# record. The truncate-then-write order this guards against leaves the anchor
# empty for a slice of every publication, so a few hundred samples put several
# hits inside a reverted build and none inside a correct one.
_LEASE_RACE_SAMPLES = 400

# The floor below which the sample is too small to stand as evidence at all.
# The target count above is what carries the power - a reverted build tears
# roughly one read in a hundred and change, which the full sample catches the
# large majority of the time and a fraction of it would not - so this is a
# vacuity guard, not the detection threshold. It should never bind: reaching
# it means the budget below expired, which takes a machine several times
# slower than an already-contended runner, and the failure then says so
# rather than reporting a tear that was never observed.
_LEASE_RACE_MIN_SAMPLES = 200

# Wall-clock ceiling on the sampling loop. It exists to stop a wedged reader,
# NOT to pace the evidence: the sample count carries the statistical power, so
# a slow machine is given the time to reach it rather than being failed for
# arriving late. Sized well clear of the rate a contended runner sustains, so
# reaching it at all means something is wrong beyond ordinary contention.
_LEASE_RACE_BUDGET_SECONDS = 120.0

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


@pytest.mark.unit
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
                    marker, process, timeout=CHILD_PROCESS_TIMEOUT_SECONDS
                )
                assert capability is not None, (
                    f"republishing lease holder did not start: {diagnostics.read()}"
                )
                # The claim under test is a ratio - no republication is ever
                # read as invalid - so the assertion is on the torn count, and
                # a machine that samples slowly is given longer rather than
                # failed for its speed. Asserting the sample count itself made
                # this guard cry wolf on a contended runner, which costs more
                # than the samples it was protecting: a guard that fails for
                # reasons unrelated to its property trains its readers to
                # re-run it. The floor keeps the sample honest without making
                # throughput the thing being proved.
                torn = 0
                samples = 0
                deadline = time.monotonic() + _LEASE_RACE_BUDGET_SECONDS
                while samples < _LEASE_RACE_SAMPLES and time.monotonic() < deadline:
                    status = borrower_lease_status(capability)
                    samples += 1
                    if status is not BorrowerLeaseStatus.HELD:
                        torn += 1
                assert samples >= _LEASE_RACE_MIN_SAMPLES, (
                    f"only reached {samples} samples in "
                    f"{_LEASE_RACE_BUDGET_SECONDS:g}s, too few to stand as "
                    "evidence that a republished record is never read as "
                    "invalid"
                )
                assert torn == 0, (
                    f"{torn} of {samples} verifications of a held lease could "
                    "not read its capability while the holder republished its "
                    "record"
                )
            finally:
                stop.write_text("stop", encoding="ascii")
                try:
                    process.wait(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
                assert process.returncode == 0, diagnostics.read()


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
def test_observing_the_borrower_lease_names_its_holder_and_takes_nothing(
    tmp_path: Path,
) -> None:
    """Looking at the lease neither takes it nor reveals what guards it.

    Mutation: an observation that reports every lease absent fails the held
    assertion; one that kept the lease it took to look fails the successor's
    acquisition.
    """
    with _isolated_borrower_anchor(tmp_path):
        assert observe_gpu_borrower().state is BorrowerState.ABSENT
        successor = acquire_gpu_borrow_lease()
        assert successor is not None, "observing a free lease must not keep it"
        release_gpu_borrow_lease(successor)

        with _borrower_process() as borrower:
            held = observe_gpu_borrower()
            holder = borrower_lease_holder_pid(borrower.capability)
            wire = json.dumps(observation_wire(held))
            _kill_borrower(borrower)
            gone = observe_gpu_borrower()

    assert holder is not None
    assert held.state is BorrowerState.HELD
    assert held.holder_pid == holder
    assert borrower.capability not in wire
    assert gone.state is BorrowerState.ABSENT
    assert gone.holder_pid == 0


@pytest.mark.unit
def test_a_borrower_lease_that_cannot_be_opened_is_unverifiable_not_absent(
    tmp_path: Path,
) -> None:
    """An anchor that cannot be read must not read as nobody borrowing.

    A directory stands where the anchor file belongs, which no account can open
    for locking. Mutation: reading an open failure as absence reports the
    observation absent and fails the presence assertion.
    """
    with _isolated_borrower_anchor(tmp_path):
        lease_path = gpu_borrow_lease_path()
        lease_path.mkdir(parents=True)
        observed = observe_gpu_borrower()

    assert observed.state is BorrowerState.UNVERIFIABLE
    assert not observed.permits_service_start
    assert str(lease_path) in observed.detail


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_singleton_dirs", "inference_host")
def test_server_start_is_refused_beside_a_live_borrower_in_both_modes() -> None:
    """A start never loads models beside a borrower, and says who and what to do.

    The whole sentence is the envelope's message because the monitor shows that
    and nothing else of a failed start, and a restart relays it. The start is
    refused before anything is fetched. Mutation: dropping the guard lets the
    start carry on to its dependency step and fails the exit-code assertion.
    """
    from typer.testing import CliRunner

    from ..cli import app

    arguments = ["server", "start", "--local-only", "--port", str(free_loopback_port())]
    with _borrower_process() as borrower:
        holder = borrower_lease_holder_pid(borrower.capability)
        as_json = CliRunner().invoke(app, [*arguments, "--json"])
        as_text = CliRunner().invoke(app, arguments)

    assert holder is not None
    assert as_json.exit_code == 1, as_json.output
    envelope = json.loads(as_json.stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == "gpu_borrowed"
    message = envelope["message"]
    assert f"(pid {holder})" in message
    assert "Wait for the borrower to finish, or stop it" in message
    assert envelope["data"]["gpu_borrower"] == {
        "state": "held",
        "holder_pid": holder,
        "detail": "",
    }
    assert borrower.capability not in as_json.output
    assert as_text.exit_code == 1, as_text.output
    assert message in " ".join(as_text.output.split())
    assert borrower.capability not in as_text.output


@pytest.mark.integration
@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_a_start_proceeds_once_the_borrower_has_exited(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The refusal lasts exactly as long as the borrower holds the lease.

    A hard-killed borrower releases it without any cleanup, so the next start is
    not refused. The start also asks the machine's own GPU owner anchor, which
    inside the loan this tier runs in admits the process tree, so the final call
    is refused only by a borrower. Mutation: reading a free anchor file as a
    held lease keeps refusing after the kill and fails the final call; dropping
    the guard fails the first.
    """
    from ..cli._service_start import _guard_start_preconditions

    port = free_loopback_port()
    with _borrower_process() as borrower:
        with pytest.raises(typer.Exit):
            _guard_start_preconditions(port, True)
        refused = json.loads(capsys.readouterr().out)
        _kill_borrower(borrower)

    assert refused["error"] == "gpu_borrowed"
    _guard_start_preconditions(port, True)
    assert capsys.readouterr().out == ""


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_a_start_is_refused_when_the_borrower_lease_cannot_be_verified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unverifiable lease counts as held, with its own sentence.

    Mutation: treating an unverifiable lease as no borrower lets the start
    through and fails the raises assertion.
    """
    from ..cli._service_start import _guard_start_preconditions

    with _isolated_borrower_anchor(tmp_path):
        gpu_borrow_lease_path().mkdir(parents=True)
        with pytest.raises(typer.Exit):
            _guard_start_preconditions(free_loopback_port(), True)

    envelope = json.loads(capsys.readouterr().out)
    assert envelope["error"] == "gpu_borrowed"
    assert envelope["data"]["gpu_borrower"]["state"] == "unverifiable"
    assert "could not be verified" in envelope["message"]


@contextmanager
def _answering_service() -> Generator[tuple[int, list[str]]]:
    """Serve ``/health`` on a loopback port and record every request it sees."""
    import threading
    from http.server import ThreadingHTTPServer

    from ._http_stubs import QuietHandler

    seen: list[str] = []

    class Handler(QuietHandler):
        def _answer(self) -> None:
            seen.append(f"{self.command} {self.path}")
            body = json.dumps({"status": "ok"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = _answer
        do_POST = _answer

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_a_restart_beside_a_live_borrower_stops_nothing_and_says_so() -> None:
    """A restart is refused before its stop, so the running service stays up.

    Start refuses while a borrower holds the GPU, so a restart that stopped
    first would leave the service down for the whole borrow. Mutation: dropping
    the guard lets the restart release the monitor and run its stop step, which
    fails the error assertion with ``restart_stop_failed``.
    """
    from typer.testing import CliRunner

    from ..cli import app

    with _answering_service() as (port, seen), _borrower_process() as borrower:
        holder = borrower_lease_holder_pid(borrower.capability)
        as_json = CliRunner().invoke(
            app, ["server", "restart", "--json", "--port", str(port)]
        )
        as_text = CliRunner().invoke(app, ["server", "restart", "--port", str(port)])

    assert holder is not None
    assert as_json.exit_code == 1, as_json.output
    envelope = json.loads(as_json.stdout)
    assert envelope["command"] == "service.restart"
    assert envelope["error"] == "gpu_borrowed"
    message = envelope["message"]
    assert f"(pid {holder})" in message
    assert "was not restarted" in message
    assert "It is still running as it was." in message
    assert envelope["data"]["gpu_borrower"]["holder_pid"] == holder
    assert as_text.exit_code == 1, as_text.output
    assert message in " ".join(as_text.output.split())
    assert borrower.capability not in as_json.output + as_text.output
    assert {request.split(" ")[0] for request in seen} == {"GET"}, seen


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_a_restart_of_a_stopped_service_leaves_the_refusal_to_its_start(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With nothing running there is nothing to keep, so the guard stands aside.

    The start step then refuses with the start sentence, which never claims a
    service is still running. Mutation: dropping the liveness check refuses
    here with the restart sentence and fails the not-refused assertion.
    """
    from ..cli._service_restart import _guard_borrower_lease

    with _borrower_process():
        try:
            _guard_borrower_lease(True, free_loopback_port())
            refused = False
        except typer.Exit:
            refused = True

    assert not refused, capsys.readouterr().out
    assert capsys.readouterr().out == ""


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_a_stop_during_a_borrow_succeeds_and_names_the_borrower() -> None:
    """Stopping is never refused for a borrower, and its envelope says what follows.

    Mutation: dropping the notice leaves the success envelope without the
    borrower and fails the gpu_borrower assertion.
    """
    from typer.testing import CliRunner

    from ..cli import app

    with _borrower_process() as borrower:
        holder = borrower_lease_holder_pid(borrower.capability)
        as_json = CliRunner().invoke(app, ["server", "stop", "--json"])
        as_text = CliRunner().invoke(app, ["server", "stop"])

    assert holder is not None
    notice = (
        f"A GPU borrower (pid {holder}) holds the GPU, so the service will not "
        "start again until the borrower releases it."
    )
    assert as_json.exit_code == 0, as_json.output
    envelope = json.loads(as_json.stdout)
    assert envelope["ok"] is True
    assert envelope["data"]["status"] == "already_stopped"
    assert envelope["data"]["gpu_borrower"] == {
        "state": "held",
        "holder_pid": holder,
        "detail": "",
    }
    assert envelope["data"]["notice"] == notice
    assert as_text.exit_code == 0, as_text.output
    assert notice in " ".join(as_text.output.split())
    assert borrower.capability not in as_json.output + as_text.output


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_singleton_dirs")
@pytest.mark.parametrize(
    ("status", "reports_borrower"),
    [
        ("stopped", True),
        ("already_stopped", True),
        ("cleaned", True),
        ("reclaimed", True),
        ("reaped", False),
    ],
)
def test_every_stop_outcome_that_leaves_no_service_reports_the_borrower(
    status: str, reports_borrower: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    """An orphan reap says nothing about the live service, so it stays silent.

    Mutation: reporting on every status fails the reaped case, and reporting on
    fewer statuses fails the case that was dropped.
    """
    from ..cli._service_stop import _stop_success

    with _borrower_process():
        _stop_success(True, status=status, human_title="Service stopped")

    data = json.loads(capsys.readouterr().out)["data"]
    assert ("gpu_borrower" in data) is reports_borrower
    assert ("notice" in data) is reports_borrower


@pytest.mark.unit
@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_a_stop_with_no_borrower_carries_no_borrower_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The envelope only grows a borrower when there is one."""
    from ..cli._service_stop import _stop_success

    _stop_success(True, status="stopped", human_title="Service stopped", pid=7)

    assert json.loads(capsys.readouterr().out)["data"] == {
        "status": "stopped",
        "pid": 7,
    }
