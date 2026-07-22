"""Unit tests for the store write-path guards.

Pure logic: real exceptions, real closures, real tmp paths - no store, no
GPU, no Qdrant. The classification, bounded retry, and disk-headroom
contracts are what turned the incident's silent completed=0 wedge into a
loud, classified job failure.
"""

from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from .._job_errors import JobError, JobErrorKind
from .._store_writes import (
    BYTES_PER_POINT_ESTIMATE,
    InsufficientDiskSpaceError,
    StoreWritePolicy,
    classify_write_error,
    ensure_disk_headroom,
    run_write_with_retry,
)
from ..config import EnvVar, reset_config

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
            result = run_write_with_retry(op, description="test", policy=None)
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
            run_write_with_retry(op, description="test", policy=None)
        assert len(calls) == 1

    def test_transient_exhaustion_raises_original_error(self) -> None:
        calls: list[int] = []
        original = ConnectionError("refused")

        def op(_attempt_timeout: int) -> None:
            calls.append(1)
            raise original

        with (
            _retry_policy(attempts=3, base_delay=0.001, max_delay=0.001),
            pytest.raises(ConnectionError, match="refused") as caught,
        ):
            run_write_with_retry(op, description="test", policy=None)
        assert len(calls) == 3
        assert caught.value is original

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
            result = run_write_with_retry(
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
            run_write_with_retry(
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
            run_write_with_retry(
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
            run_write_with_retry(
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
