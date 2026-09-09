"""Deterministic cost checks for exact-path publication reads."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
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


@pytest.mark.parametrize("parent_size", [10, 10_000])
def test_exact_path_read_has_constant_statement_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_size: int,
) -> None:
    ledger, key = _seed(tmp_path, parent_size)
    statements: list[str] = []
    original = _run_ledger_publication.ledger_connection

    @contextmanager
    def traced(path: Path) -> Generator[sqlite3.Connection]:
        with original(path) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(_run_ledger_publication, "ledger_connection", traced)
    target = f"src/file-{parent_size - 1:06d}.py"

    evidence = ledger.publication_evidence_for_paths(key, (target,))

    selects = [
        statement for statement in statements if statement.lstrip().startswith("SELECT")
    ]
    assert evidence[target].point_ids == (f"point-{parent_size - 1}",)
    assert len(selects) == 2


def test_large_parent_single_identity_read_is_indexed(
    tmp_path: Path,
) -> None:
    ledger, key = _seed(tmp_path, 25_000)
    with _run_ledger_publication.ledger_connection(ledger.path) as connection:
        plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT rel_path FROM publication_evidence
            WHERE source_type = ? AND root_identity = ?
              AND backend_identity = ? AND collection_identity = ?
              AND rel_path = ?
            """,
            (
                key.source_type.value,
                key.root_identity,
                key.backend_identity,
                key.collection_identity,
                "src/file-024999.py",
            ),
        ).fetchall()

    assert any("SEARCH publication_evidence" in str(row[3]) for row in plan)
    assert all("SCAN publication_evidence" not in str(row[3]) for row in plan)


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
