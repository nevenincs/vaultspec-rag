"""Unit tests for the issue-242 write-path guards.

Pure logic: real exceptions, real closures, real tmp paths - no store, no
GPU, no Qdrant. The classification, bounded retry, and disk-headroom
contracts are what turned the incident's silent completed=0 wedge into a
loud, classified job failure.
"""

from __future__ import annotations

import errno
from typing import TYPE_CHECKING

import pytest

from .._store_writes import (
    BYTES_PER_POINT_ESTIMATE,
    InsufficientDiskSpaceError,
    classify_write_error,
    ensure_disk_headroom,
    run_write_with_retry,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_DISK_FULL_TEXT = (
    "Error processing request: Service internal error: No space left on "
    "device: WAL buffer size exceeds available disk space"
)


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
        delays: list[float] = []

        def op() -> str:
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError("refused")
            return "ok"

        result = run_write_with_retry(
            op, description="test", attempts=5, sleep=delays.append
        )
        assert result == "ok"
        assert len(calls) == 3
        # Exponential backoff between attempts.
        assert delays == [0.5, 1.0]

    def test_unrecoverable_raises_immediately_without_retry(self) -> None:
        calls: list[int] = []
        delays: list[float] = []

        def op() -> None:
            calls.append(1)
            raise RuntimeError(_DISK_FULL_TEXT)

        with pytest.raises(RuntimeError, match="No space left on device"):
            run_write_with_retry(
                op, description="test", attempts=5, sleep=delays.append
            )
        assert len(calls) == 1
        assert delays == []

    def test_transient_exhaustion_raises_original_error(self) -> None:
        calls: list[int] = []

        def op() -> None:
            calls.append(1)
            raise ConnectionError("refused")

        with pytest.raises(ConnectionError, match="refused"):
            run_write_with_retry(
                op, description="test", attempts=3, sleep=lambda _s: None
            )
        assert len(calls) == 3


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
