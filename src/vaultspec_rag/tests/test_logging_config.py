"""Unit tests for DaemonRotatingFileHandler and install helper."""

from __future__ import annotations

import contextlib
import logging
import os
from typing import TYPE_CHECKING

import pytest

from ..logging_config import (
    DaemonRotatingFileHandler,
    install_daemon_log_rotation,
    log_event,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_log_event_emits_parseable_message_and_extra_fields(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    event_logger = logging.getLogger("vaultspec_rag.tests.event")

    with caplog.at_level(logging.INFO, logger="vaultspec_rag.tests.event"):
        log_event(
            event_logger,
            "service.search",
            "completed",
            request_id="abc123",
            root=tmp_path / "project with spaces",
            results=2,
            cache_hit=False,
        )

    record = caplog.records[-1]
    rendered = record.getMessage()
    assert rendered.startswith("service.search event=completed ")
    assert "request_id=abc123" in rendered
    assert "root=" in rendered
    assert "project with spaces" in rendered
    assert "results=2" in rendered
    assert "cache_hit=false" in rendered
    assert record.__dict__["vaultspec_event_namespace"] == "service.search"
    assert record.__dict__["vaultspec_event"] == "completed"
    assert record.__dict__["vaultspec_event_fields"]["request_id"] == "abc123"


def _clear_root_handlers() -> list[logging.Handler]:
    """Detach and return existing root handlers so tests can restore them."""
    root = logging.getLogger()
    saved = list(root.handlers)
    for h in saved:
        root.removeHandler(h)
    return saved


def _restore_root_handlers(saved: list[logging.Handler]) -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        with contextlib.suppress(Exception):
            h.close()
    for h in saved:
        root.addHandler(h)


def test_daemon_rotating_handler_do_rollover_re_dups_stdio(tmp_path: Path) -> None:
    """After doRollover, fds 1 and 2 point at the fresh (active) log file.

    Verification uses cross-platform marker bytes: we write directly to
    fds 1/2 via ``os.write`` and then read the file contents with
    ``Path.read_bytes``.  The original fds 1/2 are saved via
    ``os.dup`` and restored in ``finally`` so pytest's own captures
    keep working.
    """
    log_path = tmp_path / "service.log"
    saved_root = _clear_root_handlers()
    saved_stdout = os.dup(1)
    saved_stderr = os.dup(2)
    try:
        handler = DaemonRotatingFileHandler(
            str(log_path),
            maxBytes=64,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)

        # Initial dup2 so raw writes land in the active file.
        assert handler.stream is not None
        os.dup2(handler.stream.fileno(), 1)
        os.dup2(handler.stream.fileno(), 2)

        # Force at least one rollover by emitting a long record.
        logging.getLogger("test").warning("A" * 200)
        logging.getLogger("test").warning("B" * 200)
        handler.flush()

        # After rollover, write marker bytes directly to fds 1 and 2.
        os.write(1, b"__POST_ROLLOVER_MARKER__\n")
        os.write(2, b"__POST_ROLLOVER_STDERR__\n")
        # Flush OS buffers and handler.
        os.fsync(1)
        os.fsync(2)
        handler.flush()

        active = log_path.read_bytes()
        rotated_path = log_path.with_name(log_path.name + ".1")
        assert rotated_path.exists(), "Expected a rotated backup file"
        rotated = rotated_path.read_bytes()

        assert b"__POST_ROLLOVER_MARKER__" in active
        assert b"__POST_ROLLOVER_STDERR__" in active
        assert b"__POST_ROLLOVER_MARKER__" not in rotated
        assert b"__POST_ROLLOVER_STDERR__" not in rotated
    finally:
        os.dup2(saved_stdout, 1)
        os.dup2(saved_stderr, 2)
        os.close(saved_stdout)
        os.close(saved_stderr)
        _restore_root_handlers(saved_root)


def test_daemon_rotating_handler_rolls_when_active_file_is_pinned(
    tmp_path: Path,
) -> None:
    """Rollover succeeds even when another real file handle pins the log."""
    log_path = tmp_path / "service.log"
    saved_root = _clear_root_handlers()
    try:
        handler = DaemonRotatingFileHandler(
            str(log_path),
            maxBytes=64,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)

        logging.getLogger("test").warning("before rollover")
        handler.flush()

        with log_path.open("a", encoding="utf-8") as pinned:
            pinned.write("pinned handle\n")
            pinned.flush()
            handler.doRollover()

        logging.getLogger("test").warning("__AFTER_PINNED_ROLLOVER__")
        handler.flush()

        active = log_path.read_text(encoding="utf-8")
        rotated_path = log_path.with_name(log_path.name + ".1")
        assert rotated_path.exists(), "Expected a rotated backup file"
        rotated = rotated_path.read_text(encoding="utf-8")

        assert "__AFTER_PINNED_ROLLOVER__" in active
        assert "before rollover" in rotated
    finally:
        _restore_root_handlers(saved_root)


def test_install_attaches_to_root_logger_is_idempotent(tmp_path: Path) -> None:
    """First call attaches exactly one handler; second call leaves count at one."""
    log_path = tmp_path / "service.log"
    saved_root = _clear_root_handlers()
    saved_stdout = os.dup(1)
    saved_stderr = os.dup(2)
    try:
        h1 = install_daemon_log_rotation(
            log_path,
            max_bytes=4096,
            backup_count=2,
        )
        root = logging.getLogger()
        daemon_handlers = [
            h for h in root.handlers if isinstance(h, DaemonRotatingFileHandler)
        ]
        assert len(daemon_handlers) == 1

        h2 = install_daemon_log_rotation(
            log_path,
            max_bytes=4096,
            backup_count=2,
        )
        daemon_handlers = [
            h for h in root.handlers if isinstance(h, DaemonRotatingFileHandler)
        ]
        assert len(daemon_handlers) == 1
        assert h1 is h2
    finally:
        os.dup2(saved_stdout, 1)
        os.dup2(saved_stderr, 2)
        os.close(saved_stdout)
        os.close(saved_stderr)
        _restore_root_handlers(saved_root)
