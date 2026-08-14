"""test index run ledger: the concurrency half."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from .._job_errors import JobErrorKind, classify_error_text
from ..indexer._content_policy import ContentKind
from ..indexer._run_ledger_models import (
    INDEX_RUN_LEDGER_FILENAME,
    LEDGER_CONTENTION_ATTEMPTS,
    RunLedgerContentionError,
    with_contention_retry,
)
from ..indexer._run_ledger_runtime import RunLedger
from .test_index_run_ledger import (
    _signature,
    _unit,
)

pytestmark = [pytest.mark.unit]


def _seed_units(ledger: RunLedger, generation_id: str, *, files: int) -> None:
    """Fill the ledger until scanning it is real work rather than a no-op.

    Contention only has a window while a reader holds its lock across
    something. A ledger of three rows cannot express the condition these tests
    exist to catch, which is why the fixture has a size at all.
    """
    for index in range(files):
        path = f"src/seeded-{index:04d}.py"
        ledger.record_storage_confirmed_units(
            generation_id,
            tuple(_unit(path, ordinal, 3) for ordinal in range(3)),
        )


def _blocking_reader(
    path: Path,
    *,
    holding: threading.Event,
    release: threading.Event,
    journal_mode: str,
) -> threading.Thread:
    """Start a thread holding one open read over the whole point-id table.

    The cursor is deliberately left unexhausted: that is what holds SQLite's
    shared lock for the life of the block rather than the life of the call,
    which is the shape both a paging iterator and a full-database integrity
    scan have in production.
    """

    def hold() -> None:
        connection = sqlite3.connect(path, timeout=30.0)
        try:
            connection.execute(f"PRAGMA journal_mode = {journal_mode}")
            cursor = connection.execute("SELECT * FROM commit_point_ids")
            cursor.fetchone()
            holding.set()
            release.wait(timeout=30.0)
            cursor.close()
        finally:
            connection.close()

    thread = threading.Thread(target=hold, name="ledger-blocking-reader")
    thread.start()
    return thread


def test_a_long_reader_cannot_fail_a_concurrent_ledger_commit(tmp_path: Path) -> None:
    """A read outlasting a commit delays it at most; it must not fail it.

    The production defect at unit scale. Under a rollback journal a commit
    escalates its reserved lock to an exclusive one, which cannot happen while
    any reader holds a shared lock - so the commit, not the read, is what dies.
    """
    ledger = RunLedger(tmp_path / "index" / INDEX_RUN_LEDGER_FILENAME)
    generation = ledger.start_generation(_signature(tmp_path))
    _seed_units(ledger, generation.generation_id, files=120)
    late = _unit("src/committed-under-contention.py", 0, 1)

    holding = threading.Event()
    release = threading.Event()
    reader = _blocking_reader(
        ledger.path, holding=holding, release=release, journal_mode="WAL"
    )
    try:
        assert holding.wait(timeout=10.0), "reader never took its lock"
        assert (
            ledger.record_storage_confirmed_units(generation.generation_id, (late,))
            == 1
        )
    finally:
        release.set()
        reader.join(timeout=10.0)

    assert ledger.unit_committed(generation.generation_id, late)


def test_the_contention_harness_starves_a_rollback_journal_commit(
    tmp_path: Path,
) -> None:
    """The failing direction, kept executable instead of merely described.

    Same overlap and the same busy budget as the test above; only the journal
    mode differs. Under a rollback journal the commit is starved and reports
    SQLite's own wording, which is the text the service must read as transient
    contention rather than as a terminal fault.
    """
    path = tmp_path / "rollback.sqlite3"
    seed = sqlite3.connect(path, timeout=5.0)
    seed.execute("PRAGMA journal_mode = DELETE")
    seed.execute("CREATE TABLE commit_point_ids (point_id TEXT PRIMARY KEY)")
    seed.executemany(
        "INSERT INTO commit_point_ids(point_id) VALUES(?)",
        [(f"point-{index}",) for index in range(50_000)],
    )
    seed.commit()
    seed.close()

    holding = threading.Event()
    release = threading.Event()
    reader = _blocking_reader(
        path, holding=holding, release=release, journal_mode="DELETE"
    )
    writer = sqlite3.connect(path, timeout=1.0)
    try:
        assert holding.wait(timeout=10.0), "reader never took its lock"
        with pytest.raises(sqlite3.OperationalError, match="locked") as failure:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO commit_point_ids(point_id) VALUES('late')")
            writer.commit()
        assert classify_error_text(str(failure.value)) is JobErrorKind.LEDGER_CONTENDED
    finally:
        writer.close()
        release.set()
        reader.join(timeout=10.0)


def test_a_held_read_blocks_neither_kind_on_the_shared_ledger(
    tmp_path: Path,
) -> None:
    """One root, one ledger file, three content kinds - and no cross-starving.

    A document run's recovery scan reads the whole shared file, which includes
    everything code has ever written. Under a rollback journal that read fails
    a code commit landing in the same window: cross-kind interference arriving
    through durable state rather than through admission or storage. Both kinds
    must keep working while that read is held.
    """
    ledger_path = tmp_path / "index" / INDEX_RUN_LEDGER_FILENAME
    ledger = RunLedger(ledger_path)
    code = ledger.start_generation(_signature(tmp_path))
    _seed_units(ledger, code.generation_id, files=120)

    holding = threading.Event()
    release = threading.Event()
    reader = _blocking_reader(
        ledger_path, holding=holding, release=release, journal_mode="WAL"
    )
    try:
        assert holding.wait(timeout=10.0), "reader never took its lock"

        for index in range(20):
            assert (
                ledger.record_storage_confirmed_units(
                    code.generation_id,
                    (_unit(f"src/concurrent-{index:03d}.py", 0, 1),),
                )
                == 1
            )

        document = ledger.start_generation(
            replace(
                _signature(tmp_path),
                source_type=ContentKind.DOCUMENT,
                collection_identity="document-v1",
            )
        )
        assert (
            ledger.record_storage_confirmed_units(
                document.generation_id,
                (_unit("docs/guide.md", 0, 1),),
            )
            == 1
        )
    finally:
        release.set()
        reader.join(timeout=10.0)

    assert ledger.latest_generation(ContentKind.CODE) == ledger.generation(
        code.generation_id
    )


_CONCURRENT_LEDGER_WRITER = """
import hashlib
import sys

from vaultspec_rag.indexer._run_ledger_models import CommitUnit, CommitUnitKind
from vaultspec_rag.indexer._run_ledger_runtime import RunLedger

ledger_path, generation_id, tag, units = sys.argv[1:5]
ledger = RunLedger(ledger_path)
# Every worker also scans the shared file, which is the read a recovering run
# takes. Under a rollback journal this is what starves the other workers.
ledger.verify_integrity()
for ordinal in range(int(units)):
    path = "src/%s-%03d.py" % (tag, ordinal)
    ledger.record_storage_confirmed_units(
        generation_id,
        (
            CommitUnit(
                rel_path=path,
                kind=CommitUnitKind.UPSERT,
                source_digest=hashlib.blake2b(path.encode("utf-8")).hexdigest(),
                segment_ordinal=0,
                is_file_end=True,
                point_ids=(path + ":0",),
            ),
        ),
    )
print("ok")
"""


def test_separate_processes_commit_to_one_ledger_without_starving(
    tmp_path: Path,
) -> None:
    """Concurrent processes on one ledger each land their work exactly once.

    Threads in one interpreter share a SQLite library and can mask a file-level
    mistake. Separate processes share only the database and its locks, which is
    what a CLI run, a service run, and a recovering run on one root actually
    share. Each worker also runs the full integrity scan, so every commit lands
    while other processes are reading the same file.

    Scope, stated honestly: this covers multi-process correctness - every unit
    committed exactly once, an exact final count, no corruption, no starvation
    at this size. It does NOT discriminate the journal mode; it passes under a
    rollback journal too, because the busy budget absorbs contention when no
    single read is long enough to exhaust it. The journal-mode guards are
    `test_a_long_reader_cannot_fail_a_concurrent_ledger_commit` and
    `test_a_held_read_blocks_neither_kind_on_the_shared_ledger`, both verified
    to fail without WAL. Do not treat this test as covering that property.
    """
    ledger_path = tmp_path / "index" / INDEX_RUN_LEDGER_FILENAME
    ledger = RunLedger(ledger_path)
    generation = ledger.start_generation(_signature(tmp_path))
    _seed_units(ledger, generation.generation_id, files=60)
    before = ledger.committed_unit_count(generation.generation_id)

    workers = 4
    per_worker = 15
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _CONCURRENT_LEDGER_WRITER,
                str(ledger_path),
                generation.generation_id,
                f"worker{index}",
                str(per_worker),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(workers)
    ]
    results = [process.communicate(timeout=180.0) for process in processes]

    for index, (process, (stdout, stderr)) in enumerate(
        zip(processes, results, strict=True)
    ):
        assert "locked" not in stderr.lower(), f"worker {index} was starved: {stderr}"
        assert process.returncode == 0, f"worker {index} failed: {stderr}"
        assert stdout.strip() == "ok"

    assert (
        ledger.committed_unit_count(generation.generation_id)
        == before + workers * per_worker
    )


def test_exhausted_contention_retry_stays_classifiable_as_transient() -> None:
    """Giving up must still say "retry me", not "this run is broken".

    The whole cost of the original defect was the classification: an
    unclassified failure discarded a generation holding storage-confirmed
    work. The typed error carries SQLite's wording so the service boundary
    still recognises the condition after the retries are spent.
    """
    attempts = 0

    def always_locked() -> int:
        nonlocal attempts
        attempts += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(RunLedgerContentionError) as failure:
        with_contention_retry(always_locked, path=Path("runs.sqlite3"))

    assert attempts == LEDGER_CONTENTION_ATTEMPTS
    assert classify_error_text(str(failure.value)) is JobErrorKind.LEDGER_CONTENDED


def test_contention_retry_reraises_an_unrelated_operational_error() -> None:
    """Only contention is replayed; a real fault must surface on first sight."""
    attempts = 0

    def broken() -> int:
        nonlocal attempts
        attempts += 1
        raise sqlite3.OperationalError("no such table: commit_units")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        with_contention_retry(broken, path=Path("runs.sqlite3"))

    assert attempts == 1
