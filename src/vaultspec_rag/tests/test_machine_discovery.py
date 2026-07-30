"""Unit tests for the machine-global discovery pointer (rag-broker-affordances).

The pointer lets a consumer that does not share rag's ``VAULTSPEC_RAG_STATUS_DIR``
find the one running service. No mocks: the tests write and read a real file at a
temp-isolated machine-global path (the managed-singleton isolation rule), and clean
it through the real shutdown hook.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from .. import server as server_state
from .._machine_lock import (
    acquire_machine_lock_lease,
    machine_discovery_path,
    machine_lock_path,
    read_machine_discovery,
    release_machine_lock_lease,
)
from ..config._settings import reset_config
from ..config._types import EnvVar
from ..server import ServerRouteRuntime
from ..server._lifecycle import _DiscoveryPublisher
from ..service import ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture
def owner_publisher(
    tmp_path: Path,
) -> Iterator[_DiscoveryPublisher]:
    status_key = EnvVar.STATUS_DIR.value
    storage_key = EnvVar.QDRANT_STORAGE_DIR.value
    prior = {
        status_key: os.environ.get(status_key),
        storage_key: os.environ.get(storage_key),
    }
    os.environ[status_key] = str(tmp_path / "status")
    os.environ[storage_key] = str(tmp_path / "qdrant" / "storage")
    reset_config()
    prior_launch_token = server_state._launch_token
    server_state._launch_token = "test-launch-token"
    lease, holder = acquire_machine_lock_lease()
    assert lease is not None
    assert holder == os.getpid()
    publisher = _DiscoveryPublisher(
        ServerRouteRuntime(
            token="test-owner-token",
            registry=ServiceRegistry(),
            port=8766,
        ),
        lease,
    )
    try:
        yield publisher
    finally:
        publisher.quiesce()
        publisher.cleanup()
        release_machine_lock_lease(lease)
        server_state._launch_token = prior_launch_token
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


@pytest.mark.usefixtures("owner_publisher")
class TestMachineDiscoveryPointer:
    def test_pointer_sits_beside_the_lock(self) -> None:
        pointer = machine_discovery_path()
        assert pointer.parent == machine_lock_path().parent
        assert pointer.name == "service.json"

    def test_read_is_none_when_absent(self) -> None:
        assert read_machine_discovery() is None

    def test_owner_publish_then_read_round_trips_the_payload(
        self,
        owner_publisher: _DiscoveryPublisher,
    ) -> None:
        payload = owner_publisher.publish_phase("warming")
        assert payload is not None
        got = read_machine_discovery()
        assert got is not None
        assert got == payload
        assert got["port"] == 8766
        assert got["service_token"] == "test-owner-token"
        assert got["pid"] == os.getpid()

    def test_publish_phase_detail_round_trips_and_persists_across_heartbeats(
        self,
        owner_publisher: _DiscoveryPublisher,
    ) -> None:
        # The cold-start detail the CLI spinner renders must round-trip through
        # the published view, and stay set on subsequent heartbeats until the
        # next publish_phase changes it - otherwise the spinner would blank out
        # between the stage publish and the next heartbeat tick.
        published = owner_publisher.publish_phase("warming", detail="loading models")
        assert published is not None
        assert published["phase_detail"] == "loading models"
        discovered = read_machine_discovery()
        assert discovered is not None
        assert discovered["phase_detail"] == "loading models"

        beat = owner_publisher.heartbeat()
        assert beat is not None
        assert beat["phase_detail"] == "loading models"

        # A later stage publish replaces the detail.
        owner_publisher.publish_phase("warming", detail="loading the reranker")
        rediscovered = read_machine_discovery()
        assert rediscovered is not None
        assert rediscovered["phase_detail"] == "loading the reranker"

    def test_publish_phase_count_is_carried_only_when_a_total_is_given(
        self,
        owner_publisher: _DiscoveryPublisher,
    ) -> None:
        # A stage with a discrete count carries done/total for a determinate
        # signal; a stage without one must NOT stamp the count keys at all, so
        # the CLI renders a spinner rather than a bogus "0/0".
        counted = owner_publisher.publish_phase(
            "warming", detail="loading models", done=0, total=3
        )
        assert counted is not None
        assert counted["phase_total"] == 3
        assert counted["phase_done"] == 0

        countless = owner_publisher.publish_phase("warming", detail="warming")
        assert countless is not None
        assert "phase_total" not in countless
        assert "phase_done" not in countless

    def test_read_tolerates_garbage_and_non_object_json(self) -> None:
        pointer = machine_discovery_path()
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text("}{ not json", encoding="utf-8")
        assert read_machine_discovery() is None
        pointer.write_text("[1, 2, 3]", encoding="utf-8")  # valid JSON, not an object
        assert read_machine_discovery() is None

    def test_shutdown_cleanup_removes_the_pointer(
        self,
        owner_publisher: _DiscoveryPublisher,
    ) -> None:
        owner_publisher.heartbeat()
        assert machine_discovery_path().exists()
        assert owner_publisher.cleanup() is True
        assert not machine_discovery_path().exists()


class TestBoundedShutdownGuard:
    """Shutdown-time discovery guard waits are bounded, not unbounded."""

    def test_quiesce_does_not_block_on_a_wedged_publish_guard(self) -> None:
        """A heartbeat worker wedged mid-publish must not strand teardown.

        ``quiesce`` is the first step of daemon shutdown and holds the same
        ``_guard`` a synchronous heartbeat tick takes across its file I/O. If a
        tick wedges (slow or contended status/pointer write), an unbounded
        ``with self._guard:`` would block quiesce forever before any shutdown
        line is logged. The bounded form abandons the join past its deadline,
        sets the stop flag anyway, and returns. Reverting to the unbounded
        acquire makes this block until the wedged holder releases at ~15s and
        the timing assertion fails - so it guards the bound, not merely the
        call.
        """
        import threading
        import time

        from .._machine_lock import MachineLockLease

        publisher = _DiscoveryPublisher(
            ServerRouteRuntime(
                token="bounded-quiesce-token",
                registry=ServiceRegistry(),
                port=8766,
            ),
            MachineLockLease(machine_lock_path(), os.getpid(), 0),
        )
        held = threading.Event()
        release = threading.Event()

        def wedged_publish() -> None:
            # A different thread holds the guard (the mid-publish tick) and does
            # not release it within the bound.
            publisher._guard.acquire()
            held.set()
            release.wait(timeout=15.0)
            publisher._guard.release()

        worker = threading.Thread(target=wedged_publish)
        worker.start()
        try:
            assert held.wait(timeout=5.0), "holder never took the publish guard"
            started = time.monotonic()
            publisher.quiesce(timeout=1.0)
            elapsed = time.monotonic() - started
            assert elapsed < 3.0, f"quiesce blocked for {elapsed:.1f}s"
            assert elapsed >= 1.0, "quiesce should honour its acquire bound"
            # Stop is flagged even though the guard was abandoned, so a later
            # tick that finishes observes it and goes inert.
            assert publisher._stopping is True
        finally:
            release.set()
            worker.join(timeout=5.0)


class TestAuthoritativeRunningPublish:
    """The RUNNING claim publishes fail-loud; WARMING stays best-effort."""

    def test_running_publish_raises_when_status_lock_is_held(
        self,
        owner_publisher: _DiscoveryPublisher,
    ) -> None:
        """A held status write lock must fail the authoritative RUNNING publish.

        For a machine-singleton daemon, RUNNING is the "I own the machine and
        am serving" claim. If another process holds ``service.json.lock`` (a
        real ownership conflict), the daemon must NOT record RUNNING and serve -
        the publish must raise so startup rolls back. WARMING and heartbeat
        publications stay best-effort and swallow the same contention.

        Mutation proof: reverting the ``if require: raise`` in
        ``_publish_locked`` makes the RUNNING publish swallow the timeout and
        return normally, so ``pytest.raises`` fails - the test binds to the
        fail-loud behaviour, not merely to the call.
        """
        import threading

        from ..serviceclient._discovery import _status_write_lock

        status_path = server_state._status_file_path()
        # Publish once so the status directory and lock file exist before the
        # holder takes the lock (mirrors a daemon that reached WARMING first).
        owner_publisher.publish_phase("warming")
        held = threading.Event()
        release = threading.Event()

        def hold_status_lock() -> None:
            # A different process/owner holds the status write lock throughout.
            with _status_write_lock(status_path, timeout=30.0):
                held.set()
                release.wait(timeout=15.0)

        holder = threading.Thread(target=hold_status_lock)
        holder.start()
        try:
            assert held.wait(timeout=5.0), "holder never took the status lock"
            # Authoritative RUNNING publish must FAIL LOUD under contention, and
            # specifically as a contention-yield (another owner holds the lock)
            # so the rollback records a completed shutdown rather than unclean.
            from ..server._lifecycle import RunningClaimContendedError

            with pytest.raises(RunningClaimContendedError):
                owner_publisher.publish_phase("running", require=True)
            # Best-effort WARMING publish must NOT raise on the same contention.
            owner_publisher.publish_phase("warming")
        finally:
            release.set()
            holder.join(timeout=5.0)


class TestQdrantClientOpTimeout:
    """Managed-Qdrant client operations construct with a finite timeout.

    The startup manifest reconcile runs on the critical path with the machine
    lease held; an unbounded ``get_collections`` against a half-dead server that
    accepts the socket but never answers would strand the singleton forever.
    """

    def test_startup_reconcile_returns_when_the_server_never_answers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reconcile must not wedge on a server that accepts and stalls.

        A refused connection is not the hazard - the reconcile swallows that
        immediately. The hazard is a half-dead server that completes the
        handshake and never answers, because the read then blocks for however
        long the client was built to wait. So the socket here binds and
        listens, and nothing ever accepts a request on it.

        The bound is injected rather than defaulted: asserting the production
        default would mean a test that waits the production default.

        Proven able to fail: dropping ``timeout=`` from the ``QdrantClient``
        construction falls back to the client's own default and the call takes
        roughly 6.1s against this socket; honouring the injected bound takes
        roughly 2.7s. Both numbers are measured, not assumed - a first version
        of this test bounded at 15s and passed under the mutation, because the
        unhonoured path does not hang forever, it just waits longer. The bound
        below sits in the gap with margin either side.
        """
        import socket
        import time

        from ..server import _lifespan

        stall = socket.socket()
        stall.bind(("127.0.0.1", 0))
        stall.listen(1)
        port = stall.getsockname()[1]
        try:
            # Isolate the manifest and identity sidecar to tmp: an empty
            # ``known`` set makes the reconcile a candidate to drop entries, so
            # it must never read or mutate the operator's real managed state.
            monkeypatch.setenv(EnvVar.STATUS_DIR.value, str(tmp_path / "status"))
            monkeypatch.setenv(
                EnvVar.QDRANT_STORAGE_DIR.value,
                str(tmp_path / "qdrant" / "storage"),
            )
            monkeypatch.setenv(EnvVar.QDRANT_URL.value, f"http://127.0.0.1:{port}")
            reset_config()

            started = time.monotonic()
            _lifespan._reconcile_storage_manifest(timeout=1)
            elapsed = time.monotonic() - started
        finally:
            reset_config()
            stall.close()

        assert elapsed < 4.5
