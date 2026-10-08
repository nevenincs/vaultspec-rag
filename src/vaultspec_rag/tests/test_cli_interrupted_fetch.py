"""An interrupted foreground fetch ends as one outcome, like every other ending.

``server start``, ``server warmup`` and ``server qdrant install`` each fetch
in the foreground, where an operator can press Ctrl+C. A broker driving the
same verbs with ``--json`` is owed one envelope on every exit path, and an
interrupt that left as a traceback gave it none.

Each case runs the shipped command in a fresh interpreter against a loopback
source that accepts the request and never answers, so the fetch is in flight
for as long as the test needs. The interrupt is raised in that interpreter's
main thread once the source has seen the request - the point a keypress would
land at - and is the interpreter's own, the one a signal handler raises.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING, cast

import pytest

from ..commands._model_fetch import MODELS_OFFLINE
from ..config._types import EnvVar
from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS
from ._cli_helpers import app, runner
from ._loopback_model_hub import LoopbackModelHub
from ._loopback_tls import plain_loopback_sources, stay_silent, trusted_loopback_sources
from ._model_cache_seed import STAND_IN_DENSE, STAND_IN_RERANKER, seed_model_cache
from ._model_fetch_child import child_environment
from ._ports import free_loopback_port
from .conftest import managed_env

if TYPE_CHECKING:
    from pathlib import Path

    from ._http_stubs import QuietHandler

pytestmark = [pytest.mark.unit]

#: Run one command as a host that can serve, and raise an interrupt in the
#: main thread once the file named first on the command line appears. The
#: role and the capability are pinned with the helpers the in-process suites
#: use, because neither pin crosses a process boundary. Exit 130 means the
#: command let the interrupt through.
_INTERRUPTED_COMMAND = """
import _thread
import os
import sys
import threading
import time

import pytest

from pathlib import Path

from vaultspec_rag.operator_state._installation import ComputeCapability, InstallRole
from vaultspec_rag.tests.conftest import (
    pin_daemon_capability,
    pin_hardware_anchors,
    pin_install_role,
)

pinned = pytest.MonkeyPatch()
pin_install_role(pinned, InstallRole.HOST)
pin_daemon_capability(pinned, ComputeCapability.READY)
# A service that owns this machine's GPU would refuse the start outright.
pin_hardware_anchors(pinned, Path(sys.argv[1]).parent)


def interrupt_when_told(marker):
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        if os.path.exists(marker):
            _thread.interrupt_main()
            return
        time.sleep(0.05)


threading.Thread(target=interrupt_when_told, args=(sys.argv[1],), daemon=True).start()

from vaultspec_rag.cli import app

try:
    app(sys.argv[2:])
except SystemExit as stopped:
    sys.exit(stopped.code if isinstance(stopped.code, int) else 1)
except KeyboardInterrupt:
    sys.exit(130)
"""


class _SilentSource:
    """A responder that answers nothing, and says when it was first asked."""

    def __init__(self) -> None:
        self.asked = threading.Event()

    def respond(self, handler: QuietHandler) -> None:
        self.asked.set()
        stay_silent(handler)


def _interrupted(
    tmp_path: Path, argv: list[str], env: dict[str, str], source: _SilentSource
) -> subprocess.CompletedProcess[str]:
    """Run *argv*, interrupt it once its fetch reached *source*, and return it.

    Mutation check: with the child's hardware anchors left on the machine's
    own, a host whose service owns the GPU refuses the start, and the premise
    fails within two seconds carrying the ``gpu_owned`` envelope. Restoring
    the redirect passes.
    """
    marker = tmp_path / "interrupt-now"
    child = subprocess.Popen(
        [sys.executable, "-c", _INTERRUPTED_COMMAND, str(marker), *argv],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        deadline = time.monotonic() + CHILD_PROCESS_TIMEOUT_SECONDS
        while not source.asked.wait(timeout=0.2):
            # A child that ended has answered already, and what it said is
            # the reason its fetch never began.
            assert child.poll() is None, (
                "premise: the command ended before its fetch reached the source",
                *child.communicate(),
            )
            assert time.monotonic() < deadline, (
                "premise: the fetch never reached its source"
            )
        marker.write_text("now", encoding="utf-8")
        stdout, stderr = child.communicate(timeout=CHILD_PROCESS_TIMEOUT_SECONDS)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()
    return subprocess.CompletedProcess(child.args, child.returncode, stdout, stderr)


def _only_envelope(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, (completed.stdout, completed.stderr)
    return cast("dict[str, object]", json.loads(lines[0]))


def _model_fetch_environment(
    tmp_path: Path, endpoint: str, extra: dict[str, str] | None = None
) -> dict[str, str]:
    """A host with no model cached, whose hub is the silent source."""
    status = tmp_path / "status"
    return child_environment(
        LoopbackModelHub(repos=(), endpoint=endpoint),
        tmp_path / "hub-cache",
        {
            EnvVar.STATUS_DIR.value: str(status),
            EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant" / "storage"),
            # The hub client must not give up before the interrupt arrives,
            # and a run that mishandles the interrupt must still end.
            EnvVar.HF_HUB_DOWNLOAD_TIMEOUT.value: "60",
            "HF_HUB_ETAG_TIMEOUT": "60",
            EnvVar.MODEL_FETCH_DEADLINE_SECONDS.value: "90",
            **(extra or {}),
        },
    )


@pytest.mark.usefixtures("inference_host")
def test_a_warmup_that_cannot_fetch_is_a_failed_envelope_naming_each_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The envelope carries one failure code, and each repository's own.

    Mutation check: with the verb exiting on a failed fetch before it writes
    the envelope, stdout is empty and parsing it fails; with the code left
    out of the envelope, the ``error`` assertion fails. Restoring passes.
    """
    with managed_env(**{EnvVar.HF_HUB_OFFLINE.value: "1"}):
        seed_model_cache(
            monkeypatch,
            tmp_path / "hf-cache",
            missing=[STAND_IN_DENSE, STAND_IN_RERANKER],
        )
        result = runner.invoke(app, ["server", "warmup", "--json"])

    assert result.exit_code == 1, result.output
    envelope = cast("dict[str, object]", json.loads(result.stdout))
    assert envelope["ok"] is False
    assert envelope["command"] == "service.warmup"
    assert envelope["error"] == MODELS_OFFLINE
    data = cast("dict[str, object]", envelope["data"])
    assert data["action"] == "failed"
    repos = cast("list[dict[str, object]]", data["repos"])
    assert [(repo["repo"], repo["code"]) for repo in repos] == [
        (STAND_IN_DENSE, MODELS_OFFLINE),
        (STAND_IN_RERANKER, MODELS_OFFLINE),
    ]


@pytest.mark.usefixtures("client_installation")
def test_a_warmup_on_a_client_is_a_successful_envelope_that_fetched_nothing() -> None:
    """A client needs no models, which is an outcome and not a failure."""
    result = runner.invoke(app, ["server", "warmup", "--json"])

    assert result.exit_code == 0, result.output
    envelope = cast("dict[str, object]", json.loads(result.stdout))
    assert envelope["ok"] is True
    data = cast("dict[str, object]", envelope["data"])
    assert data["action"] == "skipped"
    assert data["repos"] == []
    assert "not needed by a client installation" in str(data["detail"])


def test_an_interrupted_warmup_is_one_envelope_and_exit_one(tmp_path: Path) -> None:
    """The verb has a JSON mode, and an interrupt is one of its outcomes.

    Mutation check: with the interrupt no longer caught by the verb, the
    interpreter exits 130 with nothing on stdout, and the exit-code assertion
    fails with 130. Restoring it passes.
    """
    silent = _SilentSource()
    with plain_loopback_sources() as sources:
        endpoint = sources.serve(silent.respond, tls=False).url()
        completed = _interrupted(
            tmp_path,
            ["server", "warmup", "--json"],
            _model_fetch_environment(tmp_path, endpoint),
            silent,
        )

    assert completed.returncode == 1, (completed.stdout, completed.stderr)
    envelope = _only_envelope(completed)
    assert envelope["ok"] is False
    assert envelope["command"] == "service.warmup"
    assert envelope["error"] == "interrupted"
    assert envelope.get("data") == {"next_actions": ["vaultspec-rag server warmup"]}


def test_a_start_interrupted_while_fetching_starts_nothing_and_says_so(
    tmp_path: Path,
) -> None:
    """One envelope, the command to run again, and no service left behind.

    The interrupt arrives while the start is still fetching the model files,
    before any daemon exists. That is a different outcome from interrupting
    the wait for readiness, where a daemon carries on, and the envelope says
    which: ``started`` is false.

    Mutation check: with the interrupt no longer caught around the fetch,
    the interpreter exits 130 with nothing on stdout, and the exit-code
    assertion fails with 130. Restoring it passes.
    """
    silent = _SilentSource()
    with plain_loopback_sources() as sources:
        endpoint = sources.serve(silent.respond, tls=False).url()
        completed = _interrupted(
            tmp_path,
            ["server", "start", "--json", "--port", str(free_loopback_port())],
            _model_fetch_environment(
                tmp_path,
                endpoint,
                {
                    EnvVar.QDRANT_AUTO_PROVISION.value: "0",
                    EnvVar.LOCAL_ONLY.value: "",
                    EnvVar.QDRANT_URL.value: "",
                },
            ),
            silent,
        )

    assert completed.returncode == 1, (completed.stdout, completed.stderr)
    envelope = _only_envelope(completed)
    assert envelope["ok"] is False
    assert envelope["command"] == "service.start"
    assert envelope["error"] == "start_interrupted"
    assert envelope.get("data") == {
        "started": False,
        "next_actions": ["vaultspec-rag server start"],
    }
    assert not (tmp_path / "status" / "service.json").exists()


def test_an_interrupted_qdrant_install_installs_nothing_and_says_so(
    tmp_path: Path,
) -> None:
    """The install verb reports the interrupt and leaves no working file.

    The release source accepts the request and sends nothing. A read that is
    waiting on a silent source is not woken by an interrupt, so the verb
    answers when that read gives up, which the download's own stall limit
    bounds at thirty seconds.

    Mutation check: with the interrupt no longer caught by the verb, the
    interpreter exits 130 with nothing on stdout, and the exit-code assertion
    fails with 130. Restoring it passes.
    """
    silent = _SilentSource()
    status = tmp_path / "status"
    with trusted_loopback_sources(tmp_path / "tls") as sources:
        env = {
            **os.environ,
            EnvVar.STATUS_DIR.value: str(status),
            EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant" / "storage"),
            EnvVar.QDRANT_RELEASE_BASE_URL.value: sources.serve(silent.respond).url(
                "/mirror"
            ),
        }
        for unset in (
            EnvVar.QDRANT_BINARY,
            EnvVar.QDRANT_BINARY_SHA256,
            EnvVar.LOCAL_ONLY,
            EnvVar.QDRANT_URL,
        ):
            env.pop(unset.value, None)
        completed = _interrupted(
            tmp_path, ["server", "qdrant", "install", "--json"], env, silent
        )

    assert completed.returncode == 1, (completed.stdout, completed.stderr)
    envelope = _only_envelope(completed)
    assert envelope["ok"] is False
    assert envelope["command"] == "server.qdrant.install"
    assert envelope["error"] == "interrupted"
    assert envelope.get("data") == {
        "next_actions": ["vaultspec-rag server qdrant install"]
    }
    left = [path.name for path in status.rglob("*") if path.is_file()]
    assert not [name for name in left if name.endswith(".staging")], left
