"""Guard tests for the qdrant supervisor's progress-aware readiness wait.

The wait's contract is that elapsed wall time alone never condemns a child. A
store that is still writing output is still working, and stopping it discards
every collection it had recovered, so the patience window restarts on every new
line and only a hard ceiling bounds the total wait. These tests pin the three
outcomes apart from one another: ready-after-the-window, stopped-at-the-ceiling,
and stopped-for-silence - plus the one that must not change, a dead child
refused immediately so the caller can still reach its recovery path.

No mocks and no fake clocks: every child below is a real subprocess whose
output a real drain thread reads, and the readiness endpoint is a real HTTP
server on a real loopback port. The windows are set in fractions of a second so
the same behaviour that takes minutes in production takes seconds here.
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
import sys
import threading
import time
from http.server import HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ..qdrant_runtime._supervise import _READY_CEILING_MULTIPLE, QdrantSupervisor
from ._http_stubs import QuietHandler
from ._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

_SUPERVISE_LOGGER = "vaultspec_rag.qdrant_runtime._supervise"

# Emits a load line every 50ms forever and never listens on anything: the shape
# of a store working through its collections, and the shape of one that has
# work to report but will never finish it. Which of the two it stands for is
# decided by whether the readiness endpoint appears, not by the child.
_CHATTERING_CHILD = """
import time

while True:
    print("Loading collection: sample", flush=True)
    time.sleep(0.05)
"""

# Alive, reachable by every liveness check, and doing nothing observable.
_SILENT_CHILD = """
import time

time.sleep(600.0)
"""

# Reports progress and then dies, which is the combination that must not be
# read as liveness: the output is real, and the process behind it is gone.
_DYING_CHILD = """
print("Loading collection: sample", flush=True)
"""


class _ReadyHandler(QuietHandler):
    """Answers every request 200, standing in for a served ``/readyz``."""

    def do_GET(self) -> None:
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def _supervised_child(
    tmp_path: Path,
    source: str,
    http_port: int,
) -> Iterator[QdrantSupervisor]:
    """Attach a real child process and its output drain to a supervisor.

    The child is spawned here rather than through ``spawn()`` because the
    supervisor spawns its binary with no arguments, and these children are
    scripts. Everything after the handoff - the drain thread, the ring, the
    line counter the readiness wait reads - is the production path.
    """
    supervisor = QdrantSupervisor(
        Path(sys.executable),
        http_port=http_port,
        storage_dir=tmp_path / "storage",
        log_path=tmp_path / "qdrant.log",
    )
    process = subprocess.Popen(
        [sys.executable, "-c", source],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
    )
    supervisor._proc = process
    supervisor._start_output_drain()
    try:
        yield supervisor
    finally:
        assert supervisor.stop(timeout=10.0)


@contextlib.contextmanager
def _readyz_from(port: int, *, after: float) -> Iterator[None]:
    """Serve a ready endpoint on *port*, but only once *after* has elapsed.

    Nothing is bound before then, so the supervisor's probes are refused - the
    same sequence a store presents while it is still opening.
    """
    bound: list[HTTPServer] = []
    cancelled = threading.Event()

    def serve() -> None:
        if cancelled.wait(after):
            return
        server = HTTPServer(("127.0.0.1", port), _ReadyHandler)
        bound.append(server)
        server.serve_forever(poll_interval=0.05)

    thread = threading.Thread(target=serve, name="readyz-stub", daemon=True)
    thread.start()
    try:
        yield
    finally:
        cancelled.set()
        for server in bound:
            server.shutdown()
            server.server_close()
        thread.join(timeout=10.0)


class TestProgressCountsAsLiveness:
    """A child still writing output outlives the patience window it was given."""

    def test_progressing_child_becomes_ready_past_its_patience_window(
        self,
        tmp_path: Path,
    ) -> None:
        # The endpoint appears well after the patience window expires, so the
        # only way this can report ready is if each drained line pushed the
        # window out. Delete that reset and the wait returns False on a fixed
        # deadline instead, exactly as it did before, and `ready` is False.
        patience = 1.5
        serve_after = 2.0
        port = free_loopback_port()

        with (
            _supervised_child(tmp_path, _CHATTERING_CHILD, port) as supervisor,
            _readyz_from(port, after=serve_after),
        ):
            started = time.monotonic()
            ready = supervisor.wait_ready(timeout=patience)
            elapsed = time.monotonic() - started

        assert ready is True, (
            f"a child writing output throughout was not waited for; gave up "
            f"after {elapsed:.2f}s against a {patience:.2f}s patience window"
        )
        assert elapsed > patience, (
            "the wait ended within the patience window, so this proves nothing "
            "about progress resetting it"
        )
        assert elapsed < patience * _READY_CEILING_MULTIPLE


class TestWedgedChildIsStillStopped:
    """Neither a chattering child nor a silent one can hold the caller open."""

    def test_child_writing_but_never_serving_is_stopped_at_the_ceiling(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # This child reports progress forever and never serves, so the patience
        # window never expires and the ceiling is the only thing that can end
        # the wait. Widen the effective ceiling past the multiple this test
        # reads and the elapsed bound below fails; the wait is otherwise
        # unbounded. The window is a full second so the poll backoff, which
        # caps at two, cannot land the deciding poll far past the ceiling and
        # eat the bound's margin.
        patience = 1.0
        ceiling = patience * _READY_CEILING_MULTIPLE
        port = free_loopback_port()

        with _supervised_child(tmp_path, _CHATTERING_CHILD, port) as supervisor:
            with caplog.at_level(logging.ERROR, logger=_SUPERVISE_LOGGER):
                started = time.monotonic()
                ready = supervisor.wait_ready(timeout=patience)
                elapsed = time.monotonic() - started
            assert supervisor.is_alive(), "the child died, so this tests nothing"

        assert ready is False
        # The ceiling branch, named exactly: the silence branch and the death
        # branch both also return False and must not satisfy this.
        assert "hard ceiling" in caplog.text
        assert "produced no output" not in caplog.text
        assert elapsed >= patience * 2, (
            "the wait ended near the patience window, so progress was not "
            "resetting it and the ceiling is not what stopped this child"
        )
        assert elapsed < ceiling * 2.5, (
            f"the hard ceiling was not enforced: a child that never serves ran "
            f"{elapsed:.2f}s against a {ceiling:.2f}s ceiling"
        )

    def test_silent_child_is_stopped_at_the_patience_window(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Alive, answering every liveness check, and observably doing nothing.
        # Remove the patience check and this child is held to the ceiling
        # instead, which the branch assertion and the elapsed bound both catch.
        patience = 0.5
        port = free_loopback_port()

        with _supervised_child(tmp_path, _SILENT_CHILD, port) as supervisor:
            with caplog.at_level(logging.ERROR, logger=_SUPERVISE_LOGGER):
                started = time.monotonic()
                ready = supervisor.wait_ready(timeout=patience)
                elapsed = time.monotonic() - started
            assert supervisor.is_alive(), "the child died, so this tests nothing"

        assert ready is False
        assert "produced no output" in caplog.text
        assert "hard ceiling" not in caplog.text
        assert elapsed < patience * _READY_CEILING_MULTIPLE, (
            f"a child that reported nothing was held for {elapsed:.2f}s, past "
            f"its {patience:.2f}s patience window"
        )

    def test_dead_child_is_refused_immediately_despite_its_progress(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # A dead child is evidence of a load failure and must reach the
        # caller's recovery path at once. Its output must never be mistaken for
        # liveness: drop the death check and the drained line holds the wait
        # open to the ceiling, and neither the branch nor the bound below hold.
        patience = 2.0
        port = free_loopback_port()

        with _supervised_child(tmp_path, _DYING_CHILD, port) as supervisor:
            with caplog.at_level(logging.ERROR, logger=_SUPERVISE_LOGGER):
                started = time.monotonic()
                ready = supervisor.wait_ready(timeout=patience)
                elapsed = time.monotonic() - started
            assert not supervisor.is_alive()
            assert "Loading collection" in supervisor.recent_output_tail()

        assert ready is False
        assert "died during startup" in caplog.text
        assert "hard ceiling" not in caplog.text
        assert "produced no output" not in caplog.text
        assert elapsed < patience, (
            f"a dead child was not refused promptly: {elapsed:.2f}s against a "
            f"{patience:.2f}s patience window"
        )
