"""Unit tests for DaemonRotatingFileHandler and install helper."""

from __future__ import annotations

import contextlib
import logging
import os
from typing import TYPE_CHECKING, cast

import pytest

from ..logging_config import (
    MANAGED_LOG_TRUNCATION_MARKER,
    MAX_MANAGED_LOG_RECORD_BYTES,
    MAX_MANAGED_LOG_SOURCE_BYTES,
    DaemonRotatingFileHandler,
    InvalidManagedLogSourceError,
    ManagedLogGroup,
    install_daemon_log_rotation,
    log_event,
    query_managed_logs,
    read_managed_logs,
    validate_managed_log_payload,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_managed_log_reader_discovers_sparse_generations_and_groups_sources(
    tmp_path: Path,
) -> None:
    (tmp_path / "service.log.5").write_text("service-oldest\n", encoding="utf-8")
    (tmp_path / "service.log.3").write_text("service-older\n", encoding="utf-8")
    (tmp_path / "service.log.1").write_text("service-newer\n", encoding="utf-8")
    (tmp_path / "service.log").write_text("service-active\n", encoding="utf-8")
    (tmp_path / "service.log.previous").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "qdrant.log.4").write_text("qdrant-oldest\n", encoding="utf-8")
    (tmp_path / "qdrant.log.2").write_text("qdrant-newer\n", encoding="utf-8")
    (tmp_path / "qdrant.log").write_text("qdrant-active\n", encoding="utf-8")

    groups = read_managed_logs(10, status_dir=tmp_path)

    assert groups == [
        {
            "source": "service",
            "lines": [
                "service-oldest",
                "service-older",
                "service-newer",
                "service-active",
            ],
        },
        {
            "source": "qdrant",
            "lines": ["qdrant-oldest", "qdrant-newer", "qdrant-active"],
        },
    ]


def test_managed_log_reader_applies_limit_independently_per_source(
    tmp_path: Path,
) -> None:
    (tmp_path / "service.log.2").write_text("s1\ns2\n", encoding="utf-8")
    (tmp_path / "service.log").write_text("s3\ns4\n", encoding="utf-8")
    (tmp_path / "qdrant.log.1").write_text("q1\nq2\n", encoding="utf-8")
    (tmp_path / "qdrant.log").write_text("q3\nq4\n", encoding="utf-8")

    groups = read_managed_logs(3, status_dir=tmp_path)

    assert groups == [
        {"source": "service", "lines": ["s2", "s3", "s4"]},
        {"source": "qdrant", "lines": ["q2", "q3", "q4"]},
    ]


def test_managed_log_reader_selects_one_source_and_retains_empty_group(
    tmp_path: Path,
) -> None:
    (tmp_path / "service.log").write_text("service-only\n", encoding="utf-8")

    assert read_managed_logs(10, source="service", status_dir=tmp_path) == [
        {"source": "service", "lines": ["service-only"]}
    ]
    assert read_managed_logs(10, source="qdrant", status_dir=tmp_path) == [
        {"source": "qdrant", "lines": []}
    ]


def test_managed_log_reader_non_positive_limit_retains_selected_groups(
    tmp_path: Path,
) -> None:
    (tmp_path / "service.log").write_text("not-returned\n", encoding="utf-8")
    (tmp_path / "qdrant.log").write_text("not-returned\n", encoding="utf-8")

    assert read_managed_logs(0, status_dir=tmp_path) == [
        {"source": "service", "lines": []},
        {"source": "qdrant", "lines": []},
    ]


def test_managed_log_reader_rejects_malformed_source(tmp_path: Path) -> None:
    with pytest.raises(
        InvalidManagedLogSourceError,
        match=r"^source must be one of service, qdrant, all\.$",
    ):
        read_managed_logs(10, source="database", status_dir=tmp_path)


@pytest.mark.parametrize("trailing_newline", [False, True])
def test_managed_log_reader_preserves_multibyte_record_across_read_blocks(
    tmp_path: Path,
    *,
    trailing_newline: bool,
) -> None:
    record = "é" * 30_000
    suffix = "\n" if trailing_newline else ""
    (tmp_path / "service.log").write_text(
        f"older-record\n{record}{suffix}",
        encoding="utf-8",
    )

    assert read_managed_logs(1, source="service", status_dir=tmp_path) == [
        {"source": "service", "lines": [record]}
    ]


def test_managed_log_query_caps_one_oversized_record_and_marks_truncation(
    tmp_path: Path,
) -> None:
    prefix = "record-start job_id=bounded "
    suffix = " record-end"
    (tmp_path / "service.log").write_text(
        prefix + ("x" * (MAX_MANAGED_LOG_RECORD_BYTES * 2)) + suffix,
        encoding="utf-8",
    )

    payload = query_managed_logs(1, source="service", status_dir=tmp_path)
    group = cast("list[ManagedLogGroup]", payload["groups"])[0]

    assert group.get("truncated") is True
    assert group.get("marker") == MANAGED_LOG_TRUNCATION_MARKER
    assert len(group["lines"][0].encode("utf-8")) <= MAX_MANAGED_LOG_RECORD_BYTES
    assert group["lines"][0].startswith(prefix)
    assert group["lines"][0].endswith(suffix)
    details = group.get("truncation")
    assert details is not None
    assert details["record_truncations"] == 1
    assert details["source_budget_exhausted"] is False
    assert details["returned_content_bytes"] <= MAX_MANAGED_LOG_SOURCE_BYTES


def test_newline_free_log_read_scans_only_finite_source_tail(tmp_path: Path) -> None:
    record_bytes = MAX_MANAGED_LOG_SOURCE_BYTES * 3
    (tmp_path / "service.log").write_bytes(b"z" * record_bytes)

    payload = query_managed_logs(1, source="service", status_dir=tmp_path)
    group = cast("list[ManagedLogGroup]", payload["groups"])[0]
    details = group.get("truncation")
    assert details is not None

    assert group.get("marker") == MANAGED_LOG_TRUNCATION_MARKER
    assert details["scanned_bytes"] == MAX_MANAGED_LOG_SOURCE_BYTES
    assert details["source_budget_exhausted"] is True
    assert details["omitted_bytes_at_least"] >= (
        record_bytes - MAX_MANAGED_LOG_SOURCE_BYTES
    )
    assert details["returned_content_bytes"] <= MAX_MANAGED_LOG_SOURCE_BYTES


def test_managed_log_query_caps_each_source_response_independently(
    tmp_path: Path,
) -> None:
    line = ("q" * 1020) + "\n"
    records = (MAX_MANAGED_LOG_SOURCE_BYTES // len(line.encode("utf-8"))) + 500
    for name in ("service.log", "qdrant.log"):
        with (tmp_path / name).open("w", encoding="utf-8") as stream:
            for index in range(records):
                stream.write(f"{index:06d} {line}")

    payload = query_managed_logs(5_000, status_dir=tmp_path)

    for group in cast("list[ManagedLogGroup]", payload["groups"]):
        details = group.get("truncation")
        assert details is not None
        assert group.get("marker") == MANAGED_LOG_TRUNCATION_MARKER
        assert details["scanned_bytes"] <= MAX_MANAGED_LOG_SOURCE_BYTES
        assert details["returned_content_bytes"] <= MAX_MANAGED_LOG_SOURCE_BYTES
        assert group["lines"][-1].startswith(f"{records - 1:06d}")


def test_live_payload_validation_rejects_unbounded_record_without_metadata() -> None:
    payload: dict[str, object] = {
        "source": "service",
        "limit": 1,
        "groups": [
            {
                "source": "service",
                "lines": ["x" * (MAX_MANAGED_LOG_RECORD_BYTES + 1)],
            }
        ],
        "filters": {},
    }

    assert (
        validate_managed_log_payload(
            payload,
            source="service",
            limit=1,
            filters={},
        )
        is None
    )


def test_live_payload_validation_rejects_unbounded_source_without_metadata() -> None:
    line = "x" * MAX_MANAGED_LOG_RECORD_BYTES
    payload: dict[str, object] = {
        "source": "service",
        "limit": 40,
        "groups": [{"source": "service", "lines": [line] * 40}],
        "filters": {},
    }

    assert (
        validate_managed_log_payload(
            payload,
            source="service",
            limit=40,
            filters={},
        )
        is None
    )


def test_live_payload_validation_rejects_unexpected_source_group() -> None:
    payload: dict[str, object] = {
        "source": "service",
        "limit": 1,
        "groups": [
            {"source": "service", "lines": ["expected"]},
            {"source": "qdrant", "lines": ["unexpected"]},
        ],
        "filters": {},
    }

    assert (
        validate_managed_log_payload(
            payload,
            source="service",
            limit=1,
            filters={},
        )
        is None
    )


def test_live_payload_validation_rejects_more_records_than_limit() -> None:
    payload: dict[str, object] = {
        "source": "service",
        "limit": 1,
        "groups": [
            {"source": "service", "lines": ["newer", "newest"]},
        ],
        "filters": {},
    }

    assert (
        validate_managed_log_payload(
            payload,
            source="service",
            limit=1,
            filters={},
        )
        is None
    )


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


def test_daemon_install_replaces_console_sink_without_duplicate_records(
    tmp_path: Path,
) -> None:
    """The production configure/install sequence writes one canonical record."""
    import subprocess
    import sys

    log_path = tmp_path / "service.log"
    code = r"""
import logging
import os
import sys
from pathlib import Path

from vaultspec_rag.logging_config import configure_logging, install_daemon_log_rotation

log_path = Path(sys.argv[1])
saved_stdout = os.dup(1)
saved_stderr = os.dup(2)
try:
    configure_logging(level="INFO")
    root = logging.getLogger()
    assert root.handlers, "configure_logging must install its normal sink"
    handler = install_daemon_log_rotation(log_path, max_bytes=4096, backup_count=2)
    assert root.handlers == [handler]
    logging.getLogger("vaultspec_rag.test").info("__ONE_CANONICAL_RECORD__")
    logging.getLogger("httpx").info("__ROUTINE_HTTP_NOISE__")
    os.write(2, b"__RAW_STDERR_RECORD__\n")
    handler.flush()
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
finally:
    os.dup2(saved_stdout, 1)
    os.dup2(saved_stderr, 2)
    os.close(saved_stdout)
    os.close(saved_stderr)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", code, str(log_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"daemon logging probe exceeded 20 seconds: {exc}")
    assert result.returncode == 0, result.stderr
    rendered = log_path.read_text(encoding="utf-8")
    assert rendered.count("__ONE_CANONICAL_RECORD__") == 1
    assert "__ROUTINE_HTTP_NOISE__" not in rendered
    assert rendered.count("__RAW_STDERR_RECORD__") == 1
