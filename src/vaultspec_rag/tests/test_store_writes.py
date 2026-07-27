"""Unit tests for the store write-path guards.

Pure logic: real exceptions, real closures, real tmp paths - no store, no
GPU, no Qdrant. The classification, bounded retry, and disk-headroom
contracts are what turned the incident's silent completed=0 wedge into a
loud, classified job failure.
"""

from __future__ import annotations

import errno
import logging
import os
import socket
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from .._job_errors import JobError, JobErrorKind
from .._store_writes import (
    BYTES_PER_POINT_ESTIMATE,
    DISK_FLOOR_BYTES,
    InsufficientDiskSpaceError,
    StoreWritePolicy,
    classify_write_error,
    ensure_disk_headroom,
    probe_store_volume,
    probe_workspace_volume,
    run_store_operation_with_retry,
    store_volume_path,
)
from ..config._settings import reset_config
from ..config._types import EnvVar

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_DISK_FULL_TEXT = (
    "Error processing request: Service internal error: No space left on "
    "device: WAL buffer size exceeds available disk space"
)


@contextmanager
def _retry_policy(
    *,
    attempts: int = 5,
    operation_timeout: float = 120.0,
    base_delay: float = 0.01,
    max_delay: float = 0.02,
) -> Generator[None]:
    """Install a short production retry policy and restore the environment."""
    values = {
        EnvVar.STORE_OPERATION_TIMEOUT_SECONDS.value: str(operation_timeout),
        EnvVar.STORE_WRITE_RETRY_ATTEMPTS.value: str(attempts),
        EnvVar.STORE_WRITE_RETRY_BASE_SECONDS.value: str(base_delay),
        EnvVar.STORE_WRITE_RETRY_MAX_SECONDS.value: str(max_delay),
    }
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        reset_config()
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


class TestFailureOutranksPendingControl:
    """A store failure must survive a cancel that lands during backoff.

    The run policy's wait doubles as the cooperative control channel, and
    the signals it raises derive from ``BaseException``, so they escape the
    retry's ``except Exception``. Left alone they replace the store failure
    that caused the backoff, and the attempt is recorded as cancelled even
    though it genuinely failed - application failure must win over a
    pending cancel.

    These bind to WHICH exception escapes, not merely that one does:
    asserting only "it raised" would pass whether the store failure or the
    control signal came out, which is the entire distinction under test.
    """

    @staticmethod
    def _policy_raising(signal: BaseException) -> StoreWritePolicy:
        """A real policy whose wait delivers *signal*, as the run policy does."""

        def wait(_seconds: float) -> None:
            raise signal

        return StoreWritePolicy(remaining_seconds=lambda: 600.0, wait=wait)

    def test_cancel_during_backoff_does_not_mask_the_failure(self) -> None:
        from ..job_control import CancelRequested

        store_failure = RuntimeError("dimension mismatch on upsert")

        def op(_attempt_timeout: int) -> None:
            raise store_failure

        with _retry_policy(attempts=5), pytest.raises(RuntimeError) as caught:
            run_store_operation_with_retry(
                op,
                description="code chunks",
                policy=self._policy_raising(CancelRequested()),
            )

        # The store failure escapes, not the cancel; the cancel is kept as
        # context so the sequence is still visible in a traceback.
        assert caught.value is store_failure
        assert isinstance(caught.value.__cause__, CancelRequested)

    def test_pause_during_backoff_does_not_mask_the_failure(self) -> None:
        from ..job_control import PauseRequested

        store_failure = RuntimeError("dimension mismatch on upsert")

        def op(_attempt_timeout: int) -> None:
            raise store_failure

        with _retry_policy(attempts=5), pytest.raises(RuntimeError) as caught:
            run_store_operation_with_retry(
                op,
                description="code chunks",
                policy=self._policy_raising(PauseRequested()),
            )
        assert caught.value is store_failure

    def test_shutdown_during_backoff_still_wins(self) -> None:
        """Shutdown is the process ending, not a verdict on the work.

        It must keep propagating so the attempt is classified interrupted
        and resumable rather than failed.
        """
        from ..job_control import ShutdownRequested

        def op(_attempt_timeout: int) -> None:
            raise RuntimeError("dimension mismatch on upsert")

        with (
            _retry_policy(attempts=5),
            pytest.raises(ShutdownRequested),
        ):
            run_store_operation_with_retry(
                op,
                description="code chunks",
                policy=self._policy_raising(ShutdownRequested()),
            )


class TestUnrecoverableOnReadOperations:
    """Storage exhaustion must raise on the first attempt for a read too.

    Widening the bounded retry from the write to every store operation must
    not make a full disk retryable anywhere: a read that surfaces the
    server's disk-full text is as futile to repeat as an upsert. This binds
    to the attempt count, which is the only thing that distinguishes
    "raised immediately" from "raised after exhausting the budget".
    """

    def test_disk_full_on_a_read_raises_without_retrying(self) -> None:
        calls: list[int] = []

        def read_op(_attempt_timeout: int) -> list[str]:
            calls.append(1)
            raise RuntimeError(_DISK_FULL_TEXT)

        with (
            _retry_policy(),
            pytest.raises(RuntimeError, match="No space left on device"),
        ):
            run_store_operation_with_retry(
                read_op,
                description="scroll codebase_docs",
                policy=None,
            )
        assert len(calls) == 1

    def test_enospc_on_a_read_raises_without_retrying(self) -> None:
        calls: list[int] = []

        def read_op(_attempt_timeout: int) -> int:
            calls.append(1)
            raise OSError(errno.ENOSPC, "No space left on device")

        with (
            _retry_policy(),
            pytest.raises(OSError, match="No space left on device"),
        ):
            run_store_operation_with_retry(
                read_op,
                description="count codebase_docs",
                policy=None,
            )
        assert len(calls) == 1


class TestRealConnectionRefusedIsRetried:
    """A genuinely refused TCP connection is ridden out, not fatal.

    These use a real socket against a real closed port, so the failure is an
    actual OS-level ECONNREFUSED (``WinError 10061`` on Windows) - the exact
    production signature - rather than a stubbed client that merely raises.
    The pair binds to the retry actually re-attempting the connection: with
    the attempt budget set to one (the pre-change single-shot behaviour) the
    identical operation fails hard.
    """

    @staticmethod
    def _closed_port() -> int:
        """Return a port that was bound and released, so nothing listens."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    def test_single_attempt_fails_hard_on_refused_connection(self) -> None:
        port = self._closed_port()
        calls: list[int] = []

        def connect_op(attempt_timeout: int) -> str:
            calls.append(1)
            with socket.create_connection(("127.0.0.1", port), timeout=attempt_timeout):
                return "connected"

        # attempts=1 reproduces the unretried path: one refusal, hard error.
        with _retry_policy(attempts=1), pytest.raises(OSError) as caught:
            run_store_operation_with_retry(
                connect_op,
                description="connect",
                policy=None,
            )
        assert isinstance(caught.value, ConnectionRefusedError)
        assert len(calls) == 1

    def test_refused_then_accepted_connection_succeeds_via_retry(self) -> None:
        port = self._closed_port()
        calls: list[int] = []
        refusals: list[OSError] = []
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        backend_up = False

        def bring_backend_up() -> None:
            nonlocal backend_up
            listener.bind(("127.0.0.1", port))
            listener.listen(8)
            backend_up = True

        def connect_op(attempt_timeout: int) -> str:
            calls.append(1)
            # Attempts 1 and 2 hit a genuinely closed port and raise a real
            # ECONNREFUSED; the backend is brought up only for attempt 3,
            # mirroring a restart window. Driving the transition off the
            # attempt count rather than a timer keeps the refusals real
            # without making the test depend on wall-clock racing.
            if len(calls) == 3 and not backend_up:
                bring_backend_up()
            try:
                with socket.create_connection(
                    ("127.0.0.1", port), timeout=attempt_timeout
                ):
                    return "connected"
            except OSError as exc:
                refusals.append(exc)
                raise

        try:
            with _retry_policy(attempts=60, base_delay=0.01, max_delay=0.02):
                result = run_store_operation_with_retry(
                    connect_op,
                    description="connect",
                    policy=None,
                )
        finally:
            listener.close()

        assert result == "connected"
        # Exactly the two pre-transition attempts were refused, and each was
        # a real ECONNREFUSED - so the success came from riding out genuine
        # refusals, not from the port happening to be open.
        assert len(calls) == 3
        assert len(refusals) == 2
        assert all(isinstance(exc, ConnectionRefusedError) for exc in refusals)


@contextmanager
def _server_mode_against(port: int, tmp_path: Path) -> Generator[None]:
    """Point a server-mode store at *port* with isolated managed paths.

    The identity sidecar and the machine-scoped service lock both derive
    from the qdrant storage dir, so it is relocated under the temp path;
    without that a test would reach the real machine-global managed dir.
    """
    values = {
        EnvVar.QDRANT_URL.value: f"http://127.0.0.1:{port}",
        EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant-server" / "storage"),
        EnvVar.STATUS_DIR.value: str(tmp_path / "status"),
    }
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        reset_config()
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


class TestStoreCallSitesRouteThroughTheRetry:
    """The store's own operations must go through the bounded retry.

    This binds to the CALL SITE, not to the retry helper: it drives a real
    ``VaultStore`` in server mode against a port with nothing listening, so
    the failure is a real refused connection from the real client.

    The assertion is on the retry's own per-attempt log records, which only
    the bounded retry emits. Elapsed time is deliberately NOT the signal:
    the qdrant client does its own connection and version-check work
    against a refused endpoint, and that alone exceeds any short backoff,
    so a timing threshold passes whether or not the call site retries -
    verified, it did. Reverting ``_collection_exists`` to
    ``self.client.collection_exists`` emits zero such records and fails.
    """

    def test_collection_exists_routes_through_the_bounded_retry(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from ..store_runtime import VaultStore

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])

        with (
            _server_mode_against(port, tmp_path),
            _retry_policy(
                attempts=3,
                operation_timeout=5.0,
                base_delay=0.01,
                max_delay=0.01,
            ),
        ):
            store = VaultStore(tmp_path)
            assert store._server_mode
            raised: BaseException | None = None
            with caplog.at_level(logging.WARNING, logger="vaultspec_rag._store_writes"):
                try:
                    store._collection_exists("any_collection")
                except BaseException as exc:
                    raised = exc

        assert raised is not None
        # Three attempts emit exactly two "retrying" records, each naming
        # this operation. A call site bypassing the retry emits none.
        retry_records = [
            record.getMessage()
            for record in caplog.records
            if "transient store operation failure" in record.getMessage()
        ]
        assert len(retry_records) == 2, (
            f"call site did not route through the retry; records={retry_records}"
        )
        assert all("collection exists" in message for message in retry_records)


class TestClassifyWriteError:
    def test_enospc_oserror_is_unrecoverable(self) -> None:
        err = OSError(errno.ENOSPC, "No space left on device")
        assert classify_write_error(err) == "unrecoverable"

    def test_server_disk_full_text_is_unrecoverable(self) -> None:
        assert classify_write_error(RuntimeError(_DISK_FULL_TEXT)) == "unrecoverable"

    def test_wrapped_cause_chain_is_walked(self) -> None:
        inner = OSError(errno.ENOSPC, "No space left on device")
        outer = RuntimeError("upsert failed")
        outer.__cause__ = inner
        assert classify_write_error(outer) == "unrecoverable"

    def test_connection_failure_is_transient(self) -> None:
        assert classify_write_error(ConnectionError("refused")) == "transient"
        assert classify_write_error(TimeoutError("timed out")) == "transient"


class TestRunWriteWithRetry:
    def test_transient_failures_retry_then_succeed(self) -> None:
        calls: list[int] = []
        admitted_timeouts: list[int] = []

        def op(attempt_timeout: int) -> str:
            calls.append(1)
            admitted_timeouts.append(attempt_timeout)
            if len(calls) < 3:
                raise ConnectionError("refused")
            return "ok"

        started = time.monotonic()
        with _retry_policy(operation_timeout=2.25):
            result = run_store_operation_with_retry(op, description="test", policy=None)
        elapsed = time.monotonic() - started

        assert result == "ok"
        assert len(calls) == 3
        assert admitted_timeouts == [3, 3, 3]
        # Two real configured waits: 0.01s then 0.02s.
        assert elapsed >= 0.025

    def test_unrecoverable_raises_immediately_without_retry(self) -> None:
        calls: list[int] = []

        def op(_attempt_timeout: int) -> None:
            calls.append(1)
            raise RuntimeError(_DISK_FULL_TEXT)

        with (
            _retry_policy(),
            pytest.raises(RuntimeError, match="No space left on device"),
        ):
            run_store_operation_with_retry(op, description="test", policy=None)
        assert len(calls) == 1

    def test_transient_exhaustion_raises_original_error(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        calls: list[int] = []
        original = ConnectionError("refused")

        def op(_attempt_timeout: int) -> None:
            calls.append(1)
            raise original

        with (
            _retry_policy(attempts=3, base_delay=0.001, max_delay=0.001),
            pytest.raises(ConnectionError, match="refused") as caught,
        ):
            run_store_operation_with_retry(op, description="test", policy=None)
        assert len(calls) == 3
        assert caught.value is original
        assert [
            record.getMessage()
            for record in caplog.records
            if record.name == "vaultspec_rag._store_writes"
            and record.levelno == logging.ERROR
        ] == ["store operation test failed after 3 attempts: refused"]

    def test_remaining_budget_clamps_the_admitted_operation_timeout(self) -> None:
        admitted_timeouts: list[int] = []
        deadline = time.monotonic() + 2.2

        def op(attempt_timeout: int) -> str:
            admitted_timeouts.append(attempt_timeout)
            return "stored"

        policy = StoreWritePolicy(
            remaining_seconds=lambda: deadline - time.monotonic(),
            wait=time.sleep,
        )
        with _retry_policy(operation_timeout=120.0):
            result = run_store_operation_with_retry(
                op,
                description="bounded upsert",
                policy=policy,
            )

        assert result == "stored"
        assert admitted_timeouts == [2]

    def test_subsecond_budget_refuses_attempt_with_typed_outcome(self) -> None:
        calls: list[int] = []
        deadline = time.monotonic() + 0.25

        def op(attempt_timeout: int) -> None:
            calls.append(attempt_timeout)

        policy = StoreWritePolicy(
            remaining_seconds=lambda: deadline - time.monotonic(),
            wait=time.sleep,
        )
        with (
            _retry_policy(operation_timeout=120.0),
            pytest.raises(JobError) as caught,
        ):
            run_store_operation_with_retry(
                op,
                description="bounded upsert",
                policy=policy,
            )

        assert caught.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
        assert calls == []

    def test_retry_wait_is_clamped_to_remaining_budget(self) -> None:
        calls: list[int] = []
        deadline = time.monotonic() + 1.1

        def op(attempt_timeout: int) -> None:
            calls.append(attempt_timeout)
            raise ConnectionError("refused")

        policy = StoreWritePolicy(
            remaining_seconds=lambda: deadline - time.monotonic(),
            wait=time.sleep,
        )
        started = time.monotonic()
        with (
            _retry_policy(
                attempts=5,
                operation_timeout=120.0,
                base_delay=2.0,
                max_delay=2.0,
            ),
            pytest.raises(JobError) as caught,
        ):
            run_store_operation_with_retry(
                op,
                description="bounded upsert",
                policy=policy,
            )
        elapsed = time.monotonic() - started

        assert caught.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
        assert calls == [1]
        assert 1.0 <= elapsed < 1.8

    def test_expired_budget_refuses_first_attempt(self) -> None:
        calls: list[int] = []
        deadline = time.monotonic() - 1.0

        def op(attempt_timeout: int) -> None:
            calls.append(attempt_timeout)

        policy = StoreWritePolicy(
            remaining_seconds=lambda: deadline - time.monotonic(),
            wait=time.sleep,
        )
        with _retry_policy(), pytest.raises(JobError) as caught:
            run_store_operation_with_retry(
                op,
                description="expired upsert",
                policy=policy,
            )

        assert caught.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
        assert calls == []


class TestEnsureDiskHeadroom:
    def test_missing_volume_skips_the_check(self, tmp_path: Path) -> None:
        # A remote server's storage dir does not exist locally; the probe
        # must skip rather than misjudge a volume it cannot see.
        ensure_disk_headroom(tmp_path / "does-not-exist", new_points=10**9)

    def test_ample_headroom_passes(self, tmp_path: Path) -> None:
        ensure_disk_headroom(tmp_path, new_points=0, floor_bytes=0)

    def test_impossible_estimate_raises_with_disk_full_phrasing(
        self, tmp_path: Path
    ) -> None:
        # An exabyte-scale estimate cannot fit on any real volume.
        impossible = (2**60) // BYTES_PER_POINT_ESTIMATE
        with pytest.raises(InsufficientDiskSpaceError, match="No space left on"):
            ensure_disk_headroom(tmp_path, new_points=impossible)

    def test_floor_breach_raises(self, tmp_path: Path) -> None:
        with pytest.raises(InsufficientDiskSpaceError):
            ensure_disk_headroom(tmp_path, floor_bytes=2**60)

    def test_refusal_reports_units_not_raw_bytes(self, tmp_path: Path) -> None:
        with pytest.raises(InsufficientDiskSpaceError) as raised:
            ensure_disk_headroom(tmp_path, floor_bytes=2**40)
        assert str(2**40) not in str(raised.value)
        assert "1.0 TiB" in str(raised.value)


class TestPerRunEstimateSizesTheRun:
    """The per-run estimate, not the flat floor, decides whether a run fits.

    This is the protection bought by lowering the host-provisioning floor:
    the flat floor was over-serving as a proxy for run size, and refusing
    ordinary runs on hosts with ample room. Both cases here run against the
    SAME real volume with real ``shutil.disk_usage``, so the only variable
    is the size of the requested run - which is precisely the property the
    flat floor cannot express and the estimate can.
    """

    @staticmethod
    def _free_bytes_of(path: Path) -> int:
        import shutil

        return shutil.disk_usage(path).free

    def test_an_oversized_run_is_refused_on_this_volume(self, tmp_path: Path) -> None:
        free = self._free_bytes_of(tmp_path)
        # Twice what the volume holds, expressed in points at the production
        # per-point estimate - derived from the live measurement rather than
        # a hardcoded constant, so the test cannot pass by coincidence on a
        # differently sized runner.
        oversized = (2 * free) // BYTES_PER_POINT_ESTIMATE

        with pytest.raises(InsufficientDiskSpaceError) as raised:
            ensure_disk_headroom(tmp_path, new_points=oversized)
        assert "No space left on" in str(raised.value)

    def test_an_ordinary_run_admits_on_the_same_volume(self, tmp_path: Path) -> None:
        free = self._free_bytes_of(tmp_path)
        # An ordinary project: the measured 12,408-point namespace. Skipping
        # rather than asserting on a genuinely full runner keeps the test
        # honest - it has nothing to say about a volume that cannot hold the
        # run either way.
        ordinary = 12_408
        needed = DISK_FLOOR_BYTES + ordinary * BYTES_PER_POINT_ESTIMATE
        assert free > needed, (
            "this runner's volume cannot fit an ordinary project; the "
            f"comparison is meaningless here (free={free}, needed={needed})"
        )

        ensure_disk_headroom(tmp_path, new_points=ordinary)

    def test_the_flat_floor_would_not_have_told_them_apart(
        self, tmp_path: Path
    ) -> None:
        """Both runs clear the host floor; only the estimate separates them.

        Without this the pair above proves only that a huge number and a
        small number differ. The point is that the flat host floor admits
        BOTH, so removing the estimate would silently admit the impossible
        run - which is exactly the regression to guard against.
        """
        from ..index_profiles import get_index_support_profile

        free = self._free_bytes_of(tmp_path)
        host_floor = get_index_support_profile("managed-service")
        assert free >= host_floor.minimum_free_disk_bytes

        ordinary = DISK_FLOOR_BYTES + 12_408 * BYTES_PER_POINT_ESTIMATE
        assert ordinary < host_floor.minimum_free_disk_bytes


@contextmanager
def _store_paths(tmp_path: Path, *, server_mode: bool) -> Generator[Path]:
    """Select a store backend with every managed path under *tmp_path*.

    The qdrant storage dir is relocated because the identity sidecar and the
    machine-scoped service lock both derive from it; leaving it at the
    default would reach the operator's real managed dir.
    """
    storage = tmp_path / "managed" / "qdrant-server" / "storage"
    values = {
        EnvVar.QDRANT_STORAGE_DIR.value: str(storage),
        EnvVar.STATUS_DIR.value: str(tmp_path / "status"),
        EnvVar.QDRANT_SERVER.value: "1",
        EnvVar.LOCAL_ONLY.value: "0" if server_mode else "1",
    }
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        os.environ.pop(EnvVar.QDRANT_URL.value, None)
        reset_config()
        yield storage
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


class TestProbeStoreVolume:
    """The headroom probe must measure where the store WRITES.

    The indexed tree and the vector store routinely live on different
    volumes - indexing a project on one drive while the managed store sits
    under the home directory on another is the ordinary case, not an exotic
    one. A probe anchored on the project root reports a free-space figure
    that has nothing to do with the requirement being enforced.
    """

    def test_server_mode_resolves_the_managed_storage_dir(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        with _store_paths(tmp_path, server_mode=True) as storage:
            assert store_volume_path(project) == storage
            # The negative half: the project root is NOT what gets measured.
            assert store_volume_path(project) != project

    def test_local_mode_resolves_the_per_project_store(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        with _store_paths(tmp_path, server_mode=False):
            resolved = store_volume_path(project)
            assert resolved.is_relative_to(project)
            # Local mode's store is under the project, but still the store
            # directory rather than the project root itself.
            assert resolved != project

    def test_absent_storage_dir_measures_its_nearest_existing_ancestor(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        with _store_paths(tmp_path, server_mode=True) as storage:
            assert not storage.exists()
            probed = probe_store_volume(project)

        # A first index on a fresh install has no storage dir yet; an
        # ancestor on the same volume answers the same question, and
        # reporting "unknown" there would disable the check needlessly.
        assert probed.path == storage
        assert probed.measured_path is not None
        assert probed.measured_path in storage.parents
        assert probed.free_bytes is not None
        assert probed.free_bytes > 0

    def test_remote_store_reports_unknown_rather_than_a_local_volume(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        with _store_paths(tmp_path, server_mode=True):
            os.environ[EnvVar.QDRANT_URL.value] = "http://qdrant.internal:6333"
            reset_config()
            probed = probe_store_volume(project)

        # This host cannot see a remote server's disk. Measuring the local
        # managed dir instead would decide admission on a volume the store
        # never writes to.
        assert probed.free_bytes is None
        assert probed.measured_path is None

    def test_loopback_url_is_the_managed_server_and_stays_measurable(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        with _store_paths(tmp_path, server_mode=True) as storage:
            storage.mkdir(parents=True)
            # The daemon publishes its own supervised child's URL; that is
            # the managed local server, not a remote one.
            os.environ[EnvVar.QDRANT_URL.value] = "http://127.0.0.1:6333"
            reset_config()
            probed = probe_store_volume(project)

        assert probed.measured_path == storage
        assert probed.free_bytes is not None

    def test_describe_names_the_measured_location(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        with _store_paths(tmp_path, server_mode=True) as storage:
            probed = probe_store_volume(project)

        described = probed.describe()
        assert str(storage) in described
        # The role is what tells an operator WHICH of the two write targets
        # the figure belongs to; without it a correct number still reads as
        # a contradiction of the drive they were looking at.
        assert "vector store" in described
        if probed.volume:
            assert f"volume {probed.volume}" in described

    def test_storage_selection_ignores_the_working_directory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The invocation's CWD must not influence which volume is measured.

        This is the reported defect in miniature: the command was run from a
        project on one drive while the managed store sat on another, and the
        preflight reported the drive it was standing in. Both the CWD and the
        project root are pointed away from the storage dir here, so the
        assertion fails if either one leaks back into the selection.
        """
        project = tmp_path / "elsewhere" / "project"
        project.mkdir(parents=True)
        with _store_paths(tmp_path, server_mode=True) as storage:
            storage.mkdir(parents=True)
            monkeypatch.chdir(project)
            probed = probe_store_volume(project)

        assert probed.measured_path == storage
        assert probed.path == storage
        assert probed.path != project
        assert not probed.path.is_relative_to(project)

    def test_workspace_probe_measures_the_project_data_dir(
        self, tmp_path: Path
    ) -> None:
        """The second write target is the project's own data dir.

        An index writes its run ledger and metadata there, so it is a real
        target with a real requirement - but a distinct one, reported under
        its own role rather than folded into the store's figure.
        """
        project = tmp_path / "project"
        project.mkdir()
        with _store_paths(tmp_path, server_mode=True) as storage:
            probed = probe_workspace_volume(project)

        assert probed.path.is_relative_to(project)
        assert probed.path != storage
        assert probed.role == "project data dir"
        assert probed.free_bytes is not None
