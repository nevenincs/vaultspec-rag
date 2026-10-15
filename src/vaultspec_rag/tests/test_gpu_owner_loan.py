"""The machine's own GPU owner anchor, asked from inside and outside the loan.

These run in the integration tier, whose session the resident service has lent
the GPU to: the service owns the machine's anchor, and the loan it recorded
there names the process that borrowed for the session, so every process this
one starts is admitted. Each question is asked of the real anchor. A process
inside the loan is answered with the loan. A contender is started outside it,
as a process whose parent has exited, and is refused by the real owner.
"""

from __future__ import annotations

import json
import os
import socket
from typing import TYPE_CHECKING, cast

import pytest

from .._anchor_claim import read_anchor_record
from .._gpu_owner import (
    GpuOwnerState,
    gpu_owner_anchor_path,
    observe_gpu_owner,
    require_gpu_ownership,
)
from .._process_probe import pid_alive, process_lineage
from ._outside_the_loan import Outside, run_outside_the_loan

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]

_ASK = """
import json
from vaultspec_rag._gpu_owner import GpuOwnedError, require_gpu_ownership

try:
    answer = {"state": str(require_gpu_ownership().state), "holder_pid": 0}
except GpuOwnedError as exc:
    answer = {
        "state": str(exc.ownership.state),
        "holder_pid": exc.ownership.holder_pid,
    }
print(json.dumps(answer))
"""

_LOAD_ACCELERATOR = """
import json
import sys

from vaultspec_rag._gpu import load_accelerator
from vaultspec_rag._gpu_owner import GpuOwnedError

try:
    load_accelerator()
    answer = {"raised": None, "state": ""}
except GpuOwnedError as exc:
    answer = {"raised": "GpuOwnedError", "state": str(exc.ownership.state)}
answer["torch_imported"] = "torch" in sys.modules
print(json.dumps(answer))
"""

# The shipped command, run as an operator runs it.
_CLI = """
import sys

from vaultspec_rag.cli import app

try:
    app(sys.argv[1:])
except SystemExit as stopped:
    code = stopped.code
    sys.exit(code if isinstance(code, int) else (0 if code is None else 1))
"""


def _the_owner_pid() -> int:
    """Return the pid of the process that owns the machine's GPU anchor.

    Read the way any process does, from inside the loan, so the contenders
    below are compared with whoever the loan really came from.
    """
    ownership = observe_gpu_owner()
    assert ownership.state is GpuOwnerState.LENT_HERE, ownership
    assert ownership.holder_pid > 0
    return ownership.holder_pid


def _answer(outside: Outside) -> dict[str, object]:
    assert outside.returncode == 0, (outside.stdout, outside.stderr)
    return cast("dict[str, object]", json.loads(outside.stdout))


def test_the_session_is_lent_the_gpu_by_the_process_that_owns_it() -> None:
    """The loan on the machine's anchor names this process tree, not this process.

    The owner's record carries the borrower's pid and start time, and this
    process is admitted because that borrower is one of its ancestors. Asking
    to load models is answered with the loan and takes nothing: the claim guard
    fails any test that leaves this process owning the machine's anchor.

    Mutation: made ``require_gpu_ownership`` answer a lent process as the
    owner. Observed the state assertion fail on owned here where lent here was
    asserted; restoring it passed.
    """
    owner = _the_owner_pid()
    ownership = require_gpu_ownership()
    record = cast("dict[str, object]", read_anchor_record(gpu_owner_anchor_path()))
    ancestors = {entry.pid: entry.start_time for entry in process_lineage()}

    assert ownership.state is GpuOwnerState.LENT_HERE
    assert ownership.holder_pid == owner
    assert owner != os.getpid()
    assert pid_alive(owner)
    assert record["pid"] == owner
    lent_to = record["lent_to"]
    assert isinstance(lent_to, int)
    assert lent_to in ancestors
    assert lent_to != owner


def test_a_process_outside_the_loan_is_refused_by_the_owner(tmp_path: Path) -> None:
    """The real owner refuses a process the GPU is not lent to, and names itself.

    Inside the loan every process this one starts is admitted, so the contender
    is a process whose parent has exited. It asks the same anchor, and is told
    the GPU is owned elsewhere by the same process that lent it here.

    Mutation: made the lineage check match every process. Observed the answer
    assertion fail on the contender reading lent here; restoring it passed.
    """
    owner = _the_owner_pid()

    answer = _answer(run_outside_the_loan(_ASK, directory=tmp_path))

    assert answer == {"state": GpuOwnerState.OWNED_ELSEWHERE, "holder_pid": owner}


def test_load_accelerator_asks_for_ownership_before_anything_else(
    tmp_path: Path,
) -> None:
    """A refused process learns it before torch is imported, let alone the device.

    Mutation: moved the ownership check below the torch import in
    ``load_accelerator``. Observed the answer assertion fail on the refused
    process having imported torch; restoring the order passed.
    """
    answer = _answer(run_outside_the_loan(_LOAD_ACCELERATOR, directory=tmp_path))

    assert answer == {
        "raised": "GpuOwnedError",
        "state": GpuOwnerState.OWNED_ELSEWHERE,
        "torch_imported": False,
    }


@pytest.mark.usefixtures("isolated_singleton_dirs")
def test_server_start_refuses_in_seconds_when_another_process_owns_the_gpu(
    tmp_path: Path,
) -> None:
    """A start outside the loan is refused by the owner before it fetches anything.

    A start judges the installation before it looks at who owns the GPU, and
    this host can serve, so the ownership refusal is the one reached.

    Mutation: gave the refusal another error code. Observed the code assertion
    fail; replacing the start's own remediation with the local-compute one
    failed the human-mode assertion on the missing next step. Restoring each
    passed.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = str(probe.getsockname()[1])
    owner = _the_owner_pid()

    machine = run_outside_the_loan(
        _CLI, "server", "start", "--json", "--port", free_port, directory=tmp_path
    )
    human = run_outside_the_loan(
        _CLI, "server", "start", "--port", free_port, directory=tmp_path
    )

    assert machine.returncode == 1, (machine.stdout, machine.stderr)
    envelope = json.loads(machine.stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == "gpu_owned"
    assert envelope["data"]["gpu_owner"] == {
        "state": GpuOwnerState.OWNED_ELSEWHERE,
        "holder_pid": owner,
        "detail": "",
    }
    # A start is resolved by the owner going away, never by search flags.
    # Catches the start path reusing the local-compute remediation.
    assert human.returncode == 1, (human.stdout, human.stderr)
    assert "Then start this one" in human.stdout
    assert "--allow-fallback" not in human.stdout


def test_a_mandated_local_search_is_refused_while_another_process_owns_the_gpu(
    tmp_path: Path,
) -> None:
    """A local mandate outside the loan is refused rather than loading a second stack.

    Mutation: removed the router's ownership pre-check. Observed the error
    assertion fail on the search carrying on locally and answering
    ``index_unavailable``; restoring the check passed.
    """
    workspace = tmp_path / "workspace"
    (workspace / ".vaultspec").mkdir(parents=True)
    owner = _the_owner_pid()

    searched = run_outside_the_loan(
        _CLI,
        "--target",
        str(workspace),
        "search",
        "anything",
        "--port",
        "1",
        "--allow-fallback",
        "--json",
        directory=tmp_path,
    )

    assert searched.returncode == 1, (searched.stdout, searched.stderr)
    envelope = json.loads(searched.stdout)
    assert envelope["ok"] is False
    assert envelope["command"] == "search"
    assert envelope["error"] == "gpu_owned"
    # The same object a refused start carries, so one condition has one shape.
    assert envelope["gpu_owner"] == {
        "state": GpuOwnerState.OWNED_ELSEWHERE,
        "holder_pid": owner,
        "detail": "",
    }
    assert any("--allow-fallback" in step for step in envelope["remediation"])
