"""One GPU owner per machine (real owner processes, private anchors).

Every question here is asked of real processes contending for a real anchor:
a child claims the GPU, lends it or does not, and this process - or a process
this one starts - asks whether it may load models. Each anchor is private to
its test, because the machine's own anchor may be held by a live service, and
a test must never contend for it.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from .._anchor_claim import AnchorOutcome, observe_existing_anchor
from .._gpu_owner import (
    GpuOwnedError,
    GpuOwnerState,
    observe_gpu_owner,
    require_gpu_ownership,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_STARTUP_SECONDS = 60.0
_HOLD_SECONDS = 240

_WAIT_FOR_STOP = f"""
ready.write_text(str(os.getpid()))
deadline = time.monotonic() + {_HOLD_SECONDS}
while not stop.exists() and time.monotonic() < deadline:
    time.sleep(0.05)
"""

# A child that owns the anchor named on its command line. It lends the GPU to
# the pid given, or publishes the given loan under its own live pid - the shape
# a forged or stale loan has - then reports its pid and holds until told to stop.
_OWNER = (
    """
import json, os, sys, time
from pathlib import Path
from vaultspec_rag import _gpu_owner
from vaultspec_rag._anchor_claim import publish_anchor_record

anchor, ready, stop = (Path(arg) for arg in sys.argv[1:4])
lend_to, loan = int(sys.argv[4]), json.loads(sys.argv[5])
_gpu_owner.require_gpu_ownership(anchor=anchor)
if lend_to:
    assert _gpu_owner.lend_gpu(lend_to, anchor=anchor)
if loan:
    publish_anchor_record(
        _gpu_owner._held[str(anchor)],
        {"pid": os.getpid(), **loan},
        width=_gpu_owner._OWNER_RECORD_WIDTH,
    )
"""
    + _WAIT_FOR_STOP
)

# A child that only exists: a live process with a pid of its own.
_IDLE = (
    """
import os, sys, time
from pathlib import Path

ready, stop = (Path(arg) for arg in sys.argv[1:3])
"""
    + _WAIT_FOR_STOP
)

# A child that holds a storage-scoped service lock at the path given, with its
# owner record, as a service of any release does.
_LOCK_HOLDER = (
    """
import os, sys, time
from pathlib import Path
from vaultspec_rag._anchor_claim import claim_anchor, record_claim_owner

lock, ready, stop = (Path(arg) for arg in sys.argv[1:4])
claim = claim_anchor(lock, pid_record=True, create_parent=True)
assert claim.descriptor is not None, claim
record_claim_owner(claim.descriptor)
"""
    + _WAIT_FOR_STOP
)

# A child that holds this session's storage-scoped service lock, as a service
# does between claiming its machine and loading its first model.
_SERVICE = (
    """
import os, sys, time
from pathlib import Path
from vaultspec_rag._machine_lock import acquire_machine_lock

ready, stop = (Path(arg) for arg in sys.argv[1:3])
acquired, _ = acquire_machine_lock()
assert acquired
"""
    + _WAIT_FOR_STOP
)

_ASK = (
    "import sys; from pathlib import Path; "
    "from vaultspec_rag._gpu_owner import GpuOwnedError, require_gpu_ownership\n"
    "try:\n"
    "    print(require_gpu_ownership(anchor=Path(sys.argv[1])).state)\n"
    "except GpuOwnedError as exc:\n"
    "    print(exc.ownership.state)\n"
)


@contextlib.contextmanager
def _child(script: str, tmp_path: Path, *args: str) -> Generator[int]:
    """Run *script* until it reports ready; yield the pid it reports."""
    ready = tmp_path / f"ready-{time.monotonic_ns()}"
    stop = tmp_path / f"stop-{time.monotonic_ns()}"
    arguments = [*args[:1], str(ready), str(stop), *args[1:]]
    process = subprocess.Popen([sys.executable, "-c", script, *arguments])
    try:
        deadline = time.monotonic() + _STARTUP_SECONDS
        # The content, not the file: creating it and writing the pid into it
        # are two steps, and a loaded host can be descheduled between them.
        reported = ""
        while not reported:
            assert process.poll() is None, "the holder exited before it was ready"
            assert time.monotonic() < deadline, "the holder never became ready"
            reported = ready.read_text() if ready.exists() else ""
            if not reported:
                time.sleep(0.05)
        yield int(reported)
    finally:
        stop.write_text("stop")
        try:
            process.wait(timeout=_STARTUP_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _owner(
    tmp_path: Path, anchor: Path, *, lend_to: int = 0, loan: object = None
) -> contextlib.AbstractContextManager[int]:
    return _child(_OWNER, tmp_path, str(anchor), str(lend_to), json.dumps(loan))


def _asked_by_a_child(anchor: Path) -> str:
    return subprocess.run(
        [sys.executable, "-c", _ASK, str(anchor)],
        capture_output=True,
        text=True,
        check=True,
        timeout=_STARTUP_SECONDS,
    ).stdout.strip()


@pytest.fixture
def anchor(tmp_path: Path) -> Path:
    return tmp_path / "gpu-owner.lock"


def test_a_process_the_gpu_is_not_lent_to_is_refused(
    anchor: Path, tmp_path: Path
) -> None:
    # Catches the refusal being dropped: a stranger would then be told it may
    # load a second model stack beside a live owner.
    with (
        _owner(tmp_path, anchor) as owner_pid,
        pytest.raises(GpuOwnedError) as refused,
    ):
        require_gpu_ownership(anchor=anchor)

    assert refused.value.ownership.state is GpuOwnerState.OWNED_ELSEWHERE
    assert refused.value.ownership.holder_pid == owner_pid


def test_the_owner_lends_the_gpu_to_the_process_tree_it_names(
    anchor: Path, tmp_path: Path
) -> None:
    with _owner(tmp_path, anchor, lend_to=os.getpid()) as owner_pid:
        here = require_gpu_ownership(anchor=anchor)
        # A process this one starts is inside the loan too, which is how the
        # test daemons of a GPU lane run beneath the borrowing session.
        in_a_child = _asked_by_a_child(anchor)

    assert here.state is GpuOwnerState.LENT_HERE
    assert here.holder_pid == owner_pid
    assert in_a_child == GpuOwnerState.LENT_HERE


def test_a_loan_to_another_process_admits_nobody_else(
    anchor: Path, tmp_path: Path
) -> None:
    with (
        _child(_IDLE, tmp_path) as bystander_pid,
        _owner(tmp_path, anchor, lend_to=bystander_pid),
        pytest.raises(GpuOwnedError) as refused,
    ):
        require_gpu_ownership(anchor=anchor)

    assert refused.value.ownership.state is GpuOwnerState.OWNED_ELSEWHERE


def test_a_loan_naming_this_pid_with_another_start_time_is_refused(
    anchor: Path, tmp_path: Path
) -> None:
    # The loan names this pid but a start time it never had: what a record
    # written for an earlier process that held this pid looks like.
    forged = {"lent_to": os.getpid(), "lent_start": 1.0}
    # Catches the start-time comparison being dropped from the lineage check:
    # a recycled pid would then inherit someone else's loan.
    with (
        _owner(tmp_path, anchor, loan=forged),
        pytest.raises(GpuOwnedError) as refused,
    ):
        require_gpu_ownership(anchor=anchor)

    assert refused.value.ownership.state is GpuOwnerState.OWNED_ELSEWHERE


def test_a_free_gpu_is_claimed_and_held_until_the_owner_exits(
    anchor: Path, tmp_path: Path
) -> None:
    with _owner(tmp_path, anchor):
        assert _asked_by_a_child(anchor) == GpuOwnerState.OWNED_ELSEWHERE

    assert _asked_by_a_child(anchor) == GpuOwnerState.OWNED_HERE


def test_a_service_holding_the_machine_refuses_a_free_gpu(
    anchor: Path, tmp_path: Path
) -> None:
    with _child(_SERVICE, tmp_path) as service_pid:
        # Catches the service-lock check being dropped: a service still
        # loading its models, or one from a release that predates the GPU
        # anchor, would then have a second stack loaded beside it.
        with pytest.raises(GpuOwnedError) as refused:
            require_gpu_ownership(anchor=anchor)
        observed = observe_gpu_owner(anchor=anchor)

    assert refused.value.ownership.state is GpuOwnerState.SERVICE_HOLDS_MACHINE
    assert refused.value.ownership.holder_pid == service_pid
    assert observed.state is GpuOwnerState.SERVICE_HOLDS_MACHINE
    # Refused, so the anchor it briefly took is not kept.
    released = observe_existing_anchor(anchor, pid_record=True, shared=True)
    assert released.outcome is AnchorOutcome.FREE


def test_an_anchor_that_cannot_be_opened_is_unverifiable_not_free(
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    unopenable = blocker / "gpu-owner.lock"

    # Catches an unopenable anchor being read as nobody owning the GPU.
    with pytest.raises(GpuOwnedError) as refused:
        require_gpu_ownership(anchor=unopenable)

    assert refused.value.ownership.state is GpuOwnerState.UNVERIFIABLE
    assert str(unopenable) in str(refused.value)


def test_observing_a_free_gpu_does_not_take_it(anchor: Path) -> None:
    assert observe_gpu_owner(anchor=anchor).state is GpuOwnerState.FREE
    assert _asked_by_a_child(anchor) == GpuOwnerState.OWNED_HERE


def test_load_accelerator_asks_for_ownership_before_anything_else(
    gpu_owner_anchor: Path, tmp_path: Path
) -> None:
    from .._gpu import load_accelerator

    with _owner(tmp_path, gpu_owner_anchor), pytest.raises(GpuOwnedError):
        # Catches load_accelerator losing its ownership check: it would then
        # import torch and reach admission, returning an accelerator or a
        # contention refusal instead of this one.
        load_accelerator()


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_server_start_refuses_in_seconds_when_another_process_owns_the_gpu(
    gpu_owner_anchor: Path, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from ..cli import app

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    with _owner(tmp_path, gpu_owner_anchor) as owner_pid:
        # Catches the start pre-flight losing its ownership check: the start
        # would then go on to bring Qdrant up and fail only at model load.
        result = CliRunner().invoke(
            app, ["server", "start", "--json", "--port", str(free_port)]
        )
        human = CliRunner().invoke(app, ["server", "start", "--port", str(free_port)])

    assert result.exit_code == 1, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == "gpu_owned"
    assert envelope["data"]["gpu_owner"] == {
        "state": GpuOwnerState.OWNED_ELSEWHERE,
        "holder_pid": owner_pid,
        "detail": "",
    }
    # A start is resolved by the owner going away, never by search flags.
    # Catches the start path reusing the local-compute remediation.
    assert human.exit_code == 1
    assert "Then start this one" in human.output
    assert "--allow-fallback" not in human.output


def test_a_mandated_local_search_is_refused_while_another_process_owns_the_gpu(
    gpu_owner_anchor: Path, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from ..cli import app

    workspace = tmp_path / "workspace"
    (workspace / ".vaultspec").mkdir(parents=True)
    with _owner(tmp_path, gpu_owner_anchor) as owner_pid:
        # Catches the search router running in-process on a local mandate
        # beside a live owner: it would open the store and load models
        # instead of refusing.
        result = CliRunner().invoke(
            app,
            [
                "--target",
                str(workspace),
                "search",
                "anything",
                "--port",
                "1",
                "--allow-fallback",
                "--json",
            ],
        )

    assert result.exit_code == 1, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["command"] == "search"
    assert envelope["error"] == "gpu_owned"
    # The same object a refused start carries, so one condition has one shape.
    assert envelope["gpu_owner"] == {
        "state": GpuOwnerState.OWNED_ELSEWHERE,
        "holder_pid": owner_pid,
        "detail": "",
    }
    assert any("--allow-fallback" in step for step in envelope["remediation"])


def test_a_load_refused_inside_a_command_renders_the_ownership_refusal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import typer

    from .._gpu_owner import GpuOwnership
    from ..cli._gpu_errors import _handle_gpu_error

    refusal = GpuOwnedError(GpuOwnership(GpuOwnerState.OWNED_ELSEWHERE, 4242))
    with pytest.raises(typer.Exit) as exited:
        _handle_gpu_error(refusal)

    printed = capsys.readouterr().out
    assert exited.value.exit_code == 1
    assert str(refusal) in " ".join(printed.split())
    # Catches the ownership branch being dropped: the torch classifier then
    # prints the refusal as a bare error line, with no next actions to take.
    assert "Next actions:" in printed


def test_a_load_refused_inside_a_json_command_emits_one_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import typer

    from .._gpu_owner import GpuOwnership
    from ..cli._gpu_errors import _handle_gpu_error

    refusal = GpuOwnedError(GpuOwnership(GpuOwnerState.OWNED_ELSEWHERE, 4242))
    with pytest.raises(typer.Exit):
        _handle_gpu_error(refusal, command="index", json_mode=True)

    # Catches the handler ignoring the caller's JSON mode: a broker parsing
    # stdout would get prose and no document.
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "index"
    assert envelope["error"] == "gpu_owned"
    assert envelope["gpu_owner"]["holder_pid"] == 4242


def test_a_held_default_location_service_lock_is_seen_as_a_service(
    tmp_path: Path,
) -> None:
    from .._gpu_owner import _holder_of_service_lock

    lock = tmp_path / "service.lock"
    with _child(_LOCK_HOLDER, tmp_path, str(lock)) as holder_pid:
        # Catches the default-location check being dropped or reading a held
        # lock as free: a service of an earlier release would then be invisible.
        assert _holder_of_service_lock(lock) == holder_pid
    assert _holder_of_service_lock(lock) is None
    assert _holder_of_service_lock(tmp_path / "never-created.lock") is None


def test_an_unobservable_service_lock_fails_closed(tmp_path: Path) -> None:
    from .._gpu_owner import _holder_of_service_lock

    # Something exists where the lock should be and cannot be opened as one -
    # a directory refuses on every platform.
    unobservable = tmp_path / "service.lock"
    unobservable.mkdir()

    # Catches an unobservable lock being read as "no service": that is the
    # fail-open answer on the one path that sees services of earlier releases.
    with pytest.raises(OSError, match="could not be observed"):
        _holder_of_service_lock(unobservable)


def test_importing_the_ownership_module_leaves_torch_unimported() -> None:
    check = "import sys, vaultspec_rag._gpu_owner; print('torch' in sys.modules)"
    imported = subprocess.run(
        [sys.executable, "-c", check],
        capture_output=True,
        text=True,
        check=True,
        timeout=_STARTUP_SECONDS,
    ).stdout.strip()

    assert imported == "False"
