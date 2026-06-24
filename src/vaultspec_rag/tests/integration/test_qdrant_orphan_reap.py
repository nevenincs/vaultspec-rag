"""Managed-Qdrant orphan reaping tests (plan W03.P06).

No mocks, no GPU: reaping is exercised against a real spawned child process, and
the "a live holder is never reaped" guarantee is checked at the decision layer
(a live, owned, capable server is routed to attach, never to reap).
"""

from __future__ import annotations

import os
import subprocess
import sys

from ...qdrant_runtime._resolve import (
    QdrantEndpointProbe,
    QdrantIdentity,
    decide_qdrant_action,
    pid_alive,
    pid_image_is_qdrant,
    reap_qdrant_orphan,
)

_SLEEP = "import time; time.sleep(60)"


class TestReap:
    def test_reaps_a_real_process(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", _SLEEP])
        try:
            assert pid_alive(proc.pid) is True
            assert reap_qdrant_orphan(proc.pid) is True
            assert pid_alive(proc.pid) is False
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_already_dead_pid_is_noop_success(self) -> None:
        assert reap_qdrant_orphan(2_000_000_000) is True

    def test_nonpositive_pid_is_not_reaped(self) -> None:
        assert reap_qdrant_orphan(0) is False


class TestLiveHolderNeverReaped:
    def test_live_owned_capable_server_routes_to_attach_not_reap(self) -> None:
        # A live, owned, capable managed server must be attached, never reaped:
        # the decision policy is the safety boundary that keeps reaping off any
        # process whose owning service is still alive.
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.18.2")
        identity = QdrantIdentity(
            storage_path="/srv/storage",
            version="1.18.2",
            owner_pid=os.getpid(),
            http_port=8765,
            qdrant_pid=os.getpid(),
        )
        action, _reason = decide_qdrant_action(
            probe,
            identity,
            expected_version="1.18.2",
            expected_storage="/srv/storage",
        )
        assert action == "attach"

    def test_dead_owner_holding_port_routes_to_reap(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=False, version="")
        identity = QdrantIdentity(
            storage_path="/srv/storage",
            version="1.18.2",
            owner_pid=2_000_000_000,
            http_port=8765,
            qdrant_pid=2_000_000_001,
        )
        action, _reason = decide_qdrant_action(
            probe,
            identity,
            expected_version="1.18.2",
            expected_storage="/srv/storage",
        )
        assert action == "reap_then_spawn"


class TestReapTargetImageGuard:
    """A recycled pid (now an unrelated process) must never be reaped."""

    def test_this_python_process_is_not_a_qdrant_target(self) -> None:
        # The reap guard checks the target's image; this test process is python.
        assert pid_image_is_qdrant(os.getpid()) is False

    def test_dead_pid_is_not_a_qdrant_target(self) -> None:
        assert pid_image_is_qdrant(2_000_000_000) is False
