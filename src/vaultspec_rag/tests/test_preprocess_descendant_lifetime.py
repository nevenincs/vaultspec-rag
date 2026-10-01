"""Real inherited pipes cannot extend preprocessing timeout or cancellation."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, cast

import pytest

from .._process_probe import (
    LineageEntry,
    kill_process_descendants,
    pid_matches_start_time,
    process_lineage,
    send_signal,
    wait_for_exit,
)
from ..indexer._preprocess_runner import _terminate_and_join
from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_PARENT = """
import json, os, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
descendant = subprocess.Popen(
    [sys._base_executable, '-c', 'import time; time.sleep(60)'])
(root / 'descendant.pid').write_text(str(descendant.pid))
while not (root / 'witnessed').exists():
    time.sleep(.01)
if sys.argv[2] == 'parent_exited':
    os._exit(0)
time.sleep(60)
"""

_PROBE = """
import json, subprocess, sys, threading, time
from pathlib import Path
from vaultspec_rag.indexer._preprocess_runner import (
    _drain_and_wait, _PreprocessSkipError)
from vaultspec_rag.job_control import CancelRequested, RunControlToken
from vaultspec_rag._process_probe import process_lineage, pid_terminated, wait_for_exit
root, mode = Path(sys.argv[1]), sys.argv[2]
parent_source = (root / 'parent.py').read_text()
parent = subprocess.Popen([sys._base_executable, '-c', parent_source, str(root), mode],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
sibling = subprocess.Popen([sys._base_executable, '-c', 'import time; time.sleep(60)'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    identity = process_lineage(parent.pid)[0]
    (root / 'parent.json').write_text(json.dumps(
        {'pid': identity.pid, 'start_time': identity.start_time}))
    deadline = time.monotonic() + 10
    while not (root / 'descendant.pid').exists():
        assert parent.poll() is None, 'fixture parent exited before readiness'
        assert time.monotonic() < deadline, 'descendant readiness missing'
        time.sleep(.01)
    child_pid = int((root / 'descendant.pid').read_text())
    child_identity = process_lineage(child_pid)[0]
    descendant = {'pid': child_pid, 'start_time': child_identity.start_time}
    (root / 'descendant.json').write_text(json.dumps(descendant))
    (root / 'witnessed').touch()
    if mode == 'parent_exited':
        parent.wait(timeout=10)
    token = RunControlToken()
    if mode == 'cancel':
        token.request_cancel()
    try:
        checkpoint = token.checkpoint if mode == 'cancel' else None
        _drain_and_wait(parent, .1, 1024, checkpoint)
    except (CancelRequested, _PreprocessSkipError) as error:
        message = str(error)
        expected = CancelRequested if mode == 'cancel' else _PreprocessSkipError
        assert isinstance(error, expected)
    else:
        raise AssertionError('invocation falsely completed')
    assert parent.poll() is not None
    assert parent.stdout.closed and parent.stderr.closed
    assert not any(t.name.startswith('preprocessor-') for t in threading.enumerate())
    assert sibling.poll() is None, 'unrelated sibling was terminated'
    if mode == 'parent_exited':
        assert not pid_terminated(descendant['pid'])
        assert 'descendant_count=unknown' in message
    else:
        assert wait_for_exit(descendant['pid'], timeout=5), 'owned descendant survived'
    print(json.dumps({'mode': mode, 'message': message,
                      'parent_reaped': True, 'pipes_closed': True,
                      'sibling_survived': True}), flush=True)
finally:
    for process in (parent, sibling):
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
"""


def _reap_fixture_witnesses(root: Path) -> None:
    """Only fixture-created, incarnation-matching processes may be signalled."""
    for name in ("descendant.json", "parent.json"):
        path = root / name
        if not path.exists():
            continue
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        witness = cast("dict[str, object]", raw)
        pid, started = witness["pid"], witness["start_time"]
        assert isinstance(pid, int) and isinstance(started, float)
        if pid_matches_start_time(pid, started):
            assert not send_signal(pid, signal.SIGTERM)
        assert wait_for_exit(pid, timeout=10), name


@pytest.mark.parametrize("mode", ["timeout", "cancel", "parent_exited"])
def test_inherited_pipe_descendants_cannot_hold_the_cleanup_open(
    tmp_path: Path, mode: str
) -> None:
    """Real pipe inheritance, real identity cleanup, and a live unrelated sibling.

    The subprocess deadline is a hang guard; no throughput or wall-clock ratio
    decides success. Timeout/cancel type, closed handles and live sibling do.
    Removing descendant termination failed on "owned descendant survived";
    removing pipe-close registration failed on closed handles. Restoring each
    passed the same real-process case.
    """
    (tmp_path / "parent.py").write_text(_PARENT, encoding="utf-8")
    environment = dict(os.environ, PYTHONWARNINGS="error")
    try:
        result = subprocess.run(
            [sys.executable, "-W", "error", "-c", _PROBE, str(tmp_path), mode],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == "", result.stderr
        report: object = json.loads(result.stdout)
        assert isinstance(report, dict)
        fields = cast("dict[str, object]", report)
        assert fields["mode"] == mode
        assert fields["parent_reaped"] is True
        assert fields["pipes_closed"] is True
        assert fields["sibling_survived"] is True
    finally:
        _reap_fixture_witnesses(tmp_path)


def test_changed_parent_identity_cannot_authorize_descendant_termination() -> None:
    """Removing the birth-time check failed the refusal; restoration passed."""
    parent = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        witness = process_lineage(parent.pid)[0]
        with pytest.raises(ProcessLookupError, match="identity changed"):
            kill_process_descendants(LineageEntry(witness.pid, witness.start_time - 1))
        assert parent.poll() is None
    finally:
        parent.kill()
        parent.wait(timeout=10)


def test_reader_shutdown_preserves_the_uncontained_descendant_diagnostic() -> None:
    """A reader completing inside set() must not erase the pre-stop witness.

    Sampling after set() failed the required refusal; sampling before it passed.
    The event controls scheduling without replacing process or cleanup behavior.
    """

    class JoinedStop(threading.Event):
        reader: threading.Thread

        def set(self) -> None:
            super().set()
            self.reader.join(timeout=5)
            assert not self.reader.is_alive()

    stopped = JoinedStop()
    reader = threading.Thread(target=stopped.wait)
    stopped.reader = reader
    with subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as parent:
        parent.wait(timeout=10)
        reader.start()
        try:
            with pytest.raises(
                ProcessLookupError,
                match="pending_pipe_readers=1, descendant_count=unknown",
            ):
                _terminate_and_join(parent, (reader,), stopped)
            assert parent.poll() == 0
            assert not reader.is_alive()
        finally:
            stopped.set()
