"""Managed-log query and daemon capture tests."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import pytest

from ..logging_config import (
    MANAGED_LOG_TRUNCATION_MARKER,
    MAX_MANAGED_LOG_RECORD_BYTES,
    MAX_MANAGED_LOG_SOURCE_BYTES,
    POLLED_ROUTES,
    InvalidManagedLogSourceError,
    PolledAccessFilter,
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
    group = payload["groups"][0]

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
    group = payload["groups"][0]
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

    for group in payload["groups"]:
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

from vaultspec_rag.logging_config import (  # absolute-import-ok
    configure_logging,
    install_daemon_log_capture,
)

log_path = Path(sys.argv[1])
capture = None
try:
    configure_logging(level="INFO")
    root = logging.getLogger()
    assert root.handlers, "configure_logging must install its normal sink"
    capture = install_daemon_log_capture(log_path, max_bytes=4096, backup_count=2)
    assert root.handlers == [capture.handler]
    logging.getLogger("vaultspec_rag.test").info("__ONE_CANONICAL_RECORD__")
    logging.getLogger("httpx").info("__ROUTINE_HTTP_NOISE__")
    os.write(2, b"__RAW_STDERR_RECORD__\n")
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
finally:
    if capture is not None and not capture.close(timeout=10.0):
        os._exit(71)
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


def test_raw_stdio_alone_drives_live_bounded_rollover(tmp_path: Path) -> None:
    """Raw fd writes rotate live without any later Python logging record."""
    import subprocess
    import sys

    log_path = tmp_path / "service.log"
    max_bytes = 512
    code = r"""
import os
import sys
import time
from pathlib import Path

from vaultspec_rag.logging_config import (  # absolute-import-ok
    configure_logging,
    install_daemon_log_capture,
)

log_path = Path(sys.argv[1])
capture = None
try:
    configure_logging(level="INFO")
    capture = install_daemon_log_capture(log_path, max_bytes=512, backup_count=2)
    for index in range(400):
        fd = 1 if index % 2 == 0 else 2
        payload = f"raw-only-{index:04d}-".encode() + (b"x" * 48) + b"\n"
        os.write(fd, payload)
    # Rotation renames service.log.1 onto service.log.2 on every rollover,
    # so no single generation exists continuously while writing continues.
    # Latch the first observation instead of re-reading it: a name a
    # rollover is free to move cannot be sampled twice and still mean the
    # same thing. The union is the stable form - the shift publishes .2 in
    # the same atomic replace that removes .1, so once rotation has started
    # one of the two is always present.
    rotated = False
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not rotated:
        rotated = any(
            log_path.with_name(f"service.log.{generation}").exists()
            for generation in (1, 2)
        )
        if not rotated:
            time.sleep(0.01)
    if not rotated:
        os._exit(72)
    os.write(1, b"__FINAL_RAW_STDOUT_MARKER__\n")
    os.write(2, b"__FINAL_RAW_STDERR_MARKER__\n")
finally:
    if capture is not None and not capture.close(timeout=10.0):
        os._exit(73)
if capture is None or capture.persistence_error is not None:
    os._exit(74)
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
        pytest.fail(f"raw daemon log probe exceeded 20 seconds: {exc}")

    assert result.returncode == 0, result.stderr
    generations = sorted(tmp_path.glob("service.log*"))
    assert {path.name for path in generations} == {
        "service.log",
        "service.log.1",
        "service.log.2",
    }
    assert all(path.stat().st_size <= max_bytes for path in generations)
    retained = b"".join(path.read_bytes() for path in generations)
    assert retained.count(b"__FINAL_RAW_STDOUT_MARKER__") == 1
    assert retained.count(b"__FINAL_RAW_STDERR_MARKER__") == 1


def _access_record(method: str, path: str, status: int) -> logging.LogRecord:
    """Build one record shaped exactly as Uvicorn's access logger emits it."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1", method, path, "1.1", status),
        exc_info=None,
    )


def test_polled_access_filter_drops_only_successful_polled_reads() -> None:
    """A timer poll is dropped; a mutation, a failure, and any other route stay.

    The three retained cases are the point. Suppressing reads that tell an
    operator nothing must not suppress the request that changed state, the
    one that failed, or traffic to a route nobody polls - those are the
    records an operator opens the log to find.
    """
    log_filter = PolledAccessFilter()

    assert not log_filter.filter(_access_record("GET", "/jobs?limit=20", 200))
    assert not log_filter.filter(_access_record("GET", "/health", 200))
    assert not log_filter.filter(_access_record("GET", "/jobs/abc123", 204))

    assert log_filter.filter(_access_record("POST", "/jobs", 200))
    assert log_filter.filter(_access_record("DELETE", "/jobs/abc123", 200))
    assert log_filter.filter(_access_record("GET", "/jobs", 500))
    assert log_filter.filter(_access_record("GET", "/jobs", 404))
    assert log_filter.filter(_access_record("GET", "/search", 200))
    assert log_filter.filter(_access_record("GET", "/jobsomething", 200))


def test_polled_access_filter_passes_records_it_cannot_read() -> None:
    """An unrecognised record shape is never silently discarded."""
    log_filter = PolledAccessFilter()
    unreadable: tuple[object, ...] = (
        None,
        (),
        ("127.0.0.1:1", "GET", "/jobs"),
        ("127.0.0.1:1", "GET", "/jobs", "1.1", "200"),
        ("127.0.0.1:1", b"GET", "/jobs", "1.1", 200),
    )
    for args in unreadable:
        record = _access_record("GET", "/jobs", 200)
        record.args = cast("Any", args)
        assert log_filter.filter(record), f"discarded unreadable record args={args!r}"


def test_polled_routes_are_absolute_paths() -> None:
    """The filter matches on path prefixes, so a relative entry never fires."""
    assert POLLED_ROUTES
    assert all(route.startswith("/") for route in POLLED_ROUTES)
    assert all(not route.endswith("/") for route in POLLED_ROUTES)


def test_one_generation_never_exceeds_what_the_reader_can_return() -> None:
    """A rotation generation may not outgrow the reader's per-source budget.

    The reader walks back from the newest bytes and stops when the budget is
    spent. A larger generation therefore carries a head that is written,
    retained, rotated, and never returned through any operator surface -
    storage spent on bytes the service cannot show.
    """
    from ..config._settings import rag_default

    assert int(rag_default("managed_log_max_bytes")) <= MAX_MANAGED_LOG_SOURCE_BYTES
