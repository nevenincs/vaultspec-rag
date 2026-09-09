"""Deterministic cost checks for exact-path publication reads."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pytest

from .._source_types import PublicSourceType
from ..indexer import _run_ledger_publication
from ..indexer._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofCompatibilityKey,
    ProofEvidence,
)
from ..indexer._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunAuthority,
    RunOperation,
    RunSignature,
)
from ..indexer._run_ledger_runtime import RunLedger

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Generator
    from pathlib import Path

pytestmark = pytest.mark.unit


def _signature(root: Path) -> RunSignature:
    return RunSignature(
        root_identity=str(root.resolve()),
        collection_identity="codebase_docs",
        source_type=PublicSourceType.CODE,
        operation=RunOperation.FULL,
        clean=True,
        model_identity="model",
        dense_dimensions=8,
        embedding_schema=3,
        payload_schema=3,
        content_epoch="content",
        membership_epoch="membership",
        preprocessing_identity="preprocessing",
        configuration_fingerprint="configuration",
        policy_fingerprint="policy",
        backend_identity="backend",
    )


def _seed(root: Path, size: int) -> tuple[RunLedger, ProofCompatibilityKey]:
    ledger = RunLedger(root / "runs.sqlite3")
    generation = ledger.start_generation(_signature(root))
    evidence = tuple(
        ProofEvidence(
            f"src/file-{index:06d}.py",
            f"content-{index}",
            (f"point-{index}",),
        )
        for index in range(size)
    )
    proof = ledger.establish_verified_publication(
        generation.generation_id,
        RunAuthority.REBUILD,
        evidence,
    )
    return ledger, proof.compatibility_key


@dataclass(slots=True)
class _ReadCost:
    """What one exact-path read actually made SQLite do."""

    vm_steps: int
    """Virtual-machine instructions retired. Grows with rows examined."""

    selects: list[str]
    """The SELECT statements production issued, as SQLite expanded them."""


@contextmanager
def _measured(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[_ReadCost]:
    """Meter the ledger connection production opens for the block's duration.

    The progress handler is the measurement that matters. A statement counter
    cannot see a scan - reading one row and reading a million are both one
    SELECT - so counting statements gates an N+1 pattern and nothing else.
    Instruction count is a direct proxy for rows examined, and it is what
    separates a seek from a scan.
    """
    cost = _ReadCost(vm_steps=0, selects=[])
    statements: list[str] = []
    original = _run_ledger_publication.ledger_connection

    def count() -> None:
        cost.vm_steps += 1

    @contextmanager
    def traced(path: Path) -> Generator[sqlite3.Connection]:
        with original(path) as connection:
            connection.set_trace_callback(statements.append)
            connection.set_progress_handler(count, 1)
            try:
                yield connection
            finally:
                connection.set_progress_handler(None, 0)
                connection.set_trace_callback(None)

    monkeypatch.setattr(_run_ledger_publication, "ledger_connection", traced)
    yield cost
    cost.selects.extend(
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    )


def test_an_exact_path_read_examines_the_same_work_at_any_parent_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The steady-state read cost must not follow the size of the collection.

    This is the proportionality claim itself, and it is asserted against
    instructions retired rather than statements issued. The two parent sizes
    differ by a thousand-fold; a read that seeks does identical work in both,
    so the bound is generous - twice the small-parent cost - and still orders
    of magnitude below what any scan can achieve.

    Proven able to fail, in both directions, against the exact regression this
    exists to catch. Replacing ``_evidence_rows_for_paths`` with one that
    selects the whole ``publication_evidence`` table and filters in Python -
    a real collection-wide scan, still one SELECT, still two statements -
    takes the measurement from 147 instructions at both sizes to 369 and
    270,099, and fails this on the bound at 732x. Restoring the production
    implementation returns it to 147 and 147, and it passes. The statement
    counter this replaced stayed green throughout that mutation.
    """
    small_ledger, small_key = _seed(tmp_path / "small", 10)
    large_ledger, large_key = _seed(tmp_path / "large", 10_000)

    with _measured(monkeypatch) as small_cost:
        small = small_ledger.publication_evidence_for_paths(
            small_key, ("src/file-000009.py",)
        )
    with _measured(monkeypatch) as large_cost:
        large = large_ledger.publication_evidence_for_paths(
            large_key, ("src/file-009999.py",)
        )

    assert small["src/file-000009.py"].point_ids == ("point-9",)
    assert large["src/file-009999.py"].point_ids == ("point-9999",)
    assert small_cost.vm_steps > 0, "the progress handler recorded nothing"
    assert large_cost.vm_steps <= small_cost.vm_steps * 2, (
        f"a read over a 10,000-path parent retired {large_cost.vm_steps} "
        f"instructions against {small_cost.vm_steps} over a 10-path parent; "
        "the exact-path read is examining the collection rather than seeking"
    )


def test_the_read_production_issues_seeks_every_table_it_touches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plan is taken from the statement production ran, not a copy of it.

    A test that writes its own SQL and explains that instead is explaining
    itself. The predecessor did exactly this: it planned a single-table
    ``rel_path = ?`` lookup while production ran a two-table LEFT JOIN with
    ``rel_path IN (...)``, so the join side was never planned at all and the
    query under test was one no caller issues.

    Both tables are asserted, because a seek on the evidence side and a scan
    on the points side is still a read that walks the collection.

    Proven able to fail: the whole-table scan described above is captured and
    explained here too, and fails this on the SCAN assertion, naming
    ``SCAN evidence``. Restoring production returns both rows to SEARCH.
    """
    ledger, key = _seed(tmp_path, 25_000)
    target = "src/file-024999.py"

    with _measured(monkeypatch) as cost:
        ledger.publication_evidence_for_paths(key, (target,))

    assert cost.selects, "production issued no SELECT to plan"
    with _run_ledger_publication.ledger_connection(ledger.path) as connection:
        plan = connection.execute(f"EXPLAIN QUERY PLAN {cost.selects[-1]}").fetchall()

    details = [str(row[3]) for row in plan]
    assert details, "the captured statement produced no plan"
    scans = [detail for detail in details if detail.lstrip().startswith("SCAN")]
    assert not scans, f"the exact-path read scans a table: {scans}"
    assert all(detail.lstrip().startswith("SEARCH") for detail in details), details


@pytest.mark.parametrize("parent_size", [10, 10_000])
def test_single_identity_commit_has_bounded_statement_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_size: int,
) -> None:
    ledger, key = _seed(tmp_path, parent_size)
    parent = ledger.publication_proof(key)
    successor = ledger.start_generation(
        replace(
            _signature(tmp_path),
            operation=RunOperation.INCREMENTAL,
            clean=False,
        )
    )
    receipt = ledger.reserve_publication_receipt(
        key,
        successor.generation_id,
        expected_parent_revision=parent.revision,
    )
    target = f"src/file-{parent_size - 1:06d}.py"
    old = ledger.publication_evidence_for_paths(key, (target,))[target]
    new = ProofEvidence(target, "content-replaced", ("point-replaced",))
    unit = CommitUnit(
        rel_path=target,
        kind=CommitUnitKind.UPSERT,
        source_digest=new.content_identity,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=new.point_ids,
    )
    stale = CommitUnit(
        rel_path=target,
        kind=CommitUnitKind.DELETE_STALE,
        segment_ordinal=0,
        is_file_end=True,
        point_ids=old.point_ids,
    )
    for mutation in (unit, stale):
        ledger.prepare_publication_mutation(receipt.receipt_id, mutation)
        ledger.mark_publication_mutation_applied(receipt.receipt_id, mutation)
        ledger.confirm_publication_mutation(receipt.receipt_id, mutation)
    ledger.seal_publication_receipt(
        receipt.receipt_id,
        (
            PathDelta(
                PathOutcome.MODIFY,
                receipt.parent_revision,
                target,
                old=old,
                new=new,
            ),
        ),
    )
    ledger.advance_finalization(
        successor.generation_id,
        FinalizationPhase.STALE_RECONCILED,
    )
    statements: list[str] = []
    original = _run_ledger_publication.ledger_connection

    @contextmanager
    def traced(path: Path) -> Generator[sqlite3.Connection]:
        with original(path) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(_run_ledger_publication, "ledger_connection", traced)
    committed = ledger.commit_publication_receipt(receipt.receipt_id)

    assert committed.aggregate.indexed_identities == parent_size
    assert len(statements) <= 40
    assert not any(
        statement.startswith("SELECT rel_path FROM publication_evidence")
        and "rel_path IN" not in statement
        for statement in statements
    )
