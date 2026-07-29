"""Record-framing and rollover guarantees for the managed log sink."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._managed_log_sink import RawRotatingLogSink

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

# A progress renderer's redraw: it returns the cursor instead of ending the
# record, so nothing terminates it. Verbatim in shape from a real capture.
_REDRAW = b"Batches:  19%|#8        | 3/16 [00:00<00:04,  3.05it/s]"
_RECORD = b"2026-07-25 12:15:44,073 ERROR    vaultspec_rag.watcher: reindex_failed"


def _sink(tmp_path: Path) -> RawRotatingLogSink:
    return RawRotatingLogSink(
        tmp_path / "service.log",
        max_bytes=1024 * 1024,
        backup_count=2,
    )


def test_consecutive_redraws_do_not_collapse_into_one_record(
    tmp_path: Path,
) -> None:
    """A burst of redraws lands as discrete records, not one endless line.

    Bounds of this guarantee: the sink sees one byte stream carrying every
    producer, so it can separate redraws from each other but cannot know that
    the last redraw ended and a different producer began. A redraw is not
    newline-terminated, so whatever is written next continues its line. Only
    the producer can close that gap, by not drawing progress into a file; the
    sink's job is to stop a redraw burst becoming a single unbounded record.
    """
    sink = _sink(tmp_path)
    try:
        for percent in (19, 25, 31):
            sink.write(b"\rBatches:  %d%%" % percent)
    finally:
        sink.close()

    lines = (tmp_path / "service.log").read_bytes().split(b"\n")
    assert [line for line in lines if line] == [
        b"Batches:  19%",
        b"Batches:  25%",
        b"Batches:  31%",
    ]


def test_crlf_split_across_writes_stays_one_record(tmp_path: Path) -> None:
    """A CRLF straddling two reads is one break, not two."""
    sink = _sink(tmp_path)
    try:
        sink.write(b"first record\r")
        sink.write(b"\nsecond record\n")
    finally:
        sink.close()

    assert (tmp_path / "service.log").read_bytes() == (b"first record\nsecond record\n")


def test_framing_never_buffers_more_than_one_byte(tmp_path: Path) -> None:
    """A producer that never emits a newline cannot grow state in the sink."""
    sink = _sink(tmp_path)
    try:
        for _ in range(500):
            sink.write(b"\r" + _REDRAW)
        assert len((tmp_path / "service.log").read_bytes()) >= 500 * len(_REDRAW)
    finally:
        sink.close()
