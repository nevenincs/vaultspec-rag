"""Run the shipped model fetch in a fresh interpreter, against a stand-in hub.

The hub client reads its endpoint and cache location once, at import, so a
fetch aimed at a loopback hub has to happen in an interpreter started with
both in its environment. What runs there is the shipped fetch, reporting
through the CLI's own sink; this module only starts it and reads what it
printed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING, cast

from ..config._types import EnvVar
from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from pathlib import Path

    from ._loopback_model_hub import LoopbackModelHub

__all__ = [
    "DENSE_REPO",
    "FETCH_IN_A_FRESH_INTERPRETER",
    "QUICK_TIMEOUTS",
    "RERANKER_REPO",
    "TIMEOUT_AFTER_A_FETCH",
    "child_environment",
    "fetch_from",
    "reported_outcome",
    "run_child",
]

DENSE_REPO = "vaultspec-test/dense"
RERANKER_REPO = "vaultspec-test/reranker"

#: Run the shipped fetch through the CLI's own sink and print its outcome as
#: the last line of stdout. Progress goes to stderr, where the reporter sends
#: it off a terminal.
FETCH_IN_A_FRESH_INTERPRETER = """
import json
import os
import sys
import time

import psutil

from vaultspec_rag.cli._progress import StartupStatusReporter
from vaultspec_rag.cli._provision_progress import ReporterProvisionProgress
from vaultspec_rag.commands._model_download import FetchLimits
from vaultspec_rag.commands._model_fetch import fetch_models

# Observation only: the interpreter reports every process it creates and
# every connection it opens to an audit hook, so "was a download process
# started" and "did this process itself reach for the hub" are read, not
# arranged. The download processes are other interpreters and are not seen.
started = []
connected = []


def observe(event, args):
    if event == "subprocess.Popen":
        started.append(args[1])
    elif event == "socket.connect":
        connected.append(str(args[1]))


sys.addaudithook(observe)
shipped = FetchLimits()
limits = FetchLimits(
    window_seconds=float(os.environ.get("TEST_FETCH_WINDOW", shipped.window_seconds)),
    first_byte_seconds=float(
        os.environ.get("TEST_FETCH_FIRST_BYTE", shipped.first_byte_seconds)
    ),
    contention_seconds=float(
        os.environ.get("TEST_FETCH_CONTENTION", shipped.contention_seconds)
    ),
)
if os.environ.get("TEST_KILL_FIRST_DOWNLOAD"):
    import threading

    def kill_the_first_download():
        # What an out-of-memory kill or a task manager does: the download
        # process and whatever it started are ended from outside, mid-work.
        me = psutil.Process()
        while not me.children(recursive=True):
            time.sleep(0.05)
        time.sleep(1.5)
        for child in me.children(recursive=True):
            try:
                child.kill()
            except psutil.Error:
                pass

    threading.Thread(target=kill_the_first_download, daemon=True).start()
began = time.monotonic()
reporter = StartupStatusReporter(json_mode=False, interactive=False)
with ReporterProvisionProgress(reporter) as sink:
    fetched = fetch_models(progress=sink, limits=limits)
took = time.monotonic() - began
print(
    json.dumps(
        {
            "action": str(fetched.action),
            "detail": fetched.detail,
            "code": fetched.code,
            "repos": [
                [repo.repo, str(repo.action), repo.code]
                for repo in fetched.repos
            ],
            "details": [repo.detail for repo in fetched.repos],
            "processes_started": len(started),
            "connections": connected,
            "processes_left": [
                child.pid for child in psutil.Process().children(recursive=True)
            ],
            "seconds": took,
        }
    )
)
"""

#: Run the fetch as a preview, which reaches the hub client without asking
#: the network for anything, then print the per-read timeout the client is
#: left with.
TIMEOUT_AFTER_A_FETCH = """
from vaultspec_rag.commands._model_fetch import fetch_models

fetch_models(dry_run=True)

from huggingface_hub import constants

print(constants.HF_HUB_DOWNLOAD_TIMEOUT)
"""

#: The hub client's own timeouts, shortened so a hub that stops answering is
#: given up on in seconds. They are the knobs an operator has, set the way an
#: operator sets them; nothing about how the client waits is replaced.
QUICK_TIMEOUTS = {
    EnvVar.HF_HUB_DOWNLOAD_TIMEOUT.value: "1",
    "HF_HUB_ETAG_TIMEOUT": "1",
}


def child_environment(
    hub: LoopbackModelHub, cache: Path, extra: dict[str, str] | None = None
) -> dict[str, str]:
    """Build a fresh interpreter's environment: *hub*, *cache*, two fake repos."""
    env = hub.child_environment(cache)
    env[EnvVar.EMBEDDING_MODEL.value] = DENSE_REPO
    env[EnvVar.RERANKER_MODEL.value] = RERANKER_REPO
    env[EnvVar.SPARSE_ENABLED.value] = "0"
    env.update(extra or {})
    return env


def run_child(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run *script* in a fresh interpreter with *env*, bounded, and return it."""
    return subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
        check=False,
    )


def fetch_from(
    hub: LoopbackModelHub, cache: Path, extra: dict[str, str] | None = None
) -> tuple[dict[str, object], str]:
    """Run the fetch in a fresh interpreter aimed at *hub*; return it and stderr.

    Whatever the hub did and however the fetch ended, the interpreter that
    ran it must have opened no connection of its own: every request to the
    hub belongs to a download process, which can be stopped.

    Mutation check: with the size of a repository asked for by the fetch
    itself before it starts a download process, every case that reaches a
    download fails here, naming the hub's address; removing the request
    passes.
    """
    completed = run_child(
        FETCH_IN_A_FRESH_INTERPRETER, child_environment(hub, cache, extra)
    )
    assert completed.returncode == 0, completed.stderr
    outcome = reported_outcome(completed.stdout)
    return outcome, completed.stderr


def reported_outcome(stdout: str) -> dict[str, object]:
    """Read the outcome a fetch interpreter printed, and hold it to the invariant."""
    outcome = cast("dict[str, object]", json.loads(stdout.strip().splitlines()[-1]))
    assert outcome["connections"] == [], (
        "the fetch's own process opened a connection; only a download process may"
    )
    return outcome
