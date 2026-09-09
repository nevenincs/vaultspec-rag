"""Large-parent benchmark for one exact incremental publication identity."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from ..._source_types import PublicSourceType
from ...indexer._publication_proof import ProofEvidence
from ...indexer._run_ledger_models import RunAuthority, RunOperation, RunSignature
from ...indexer._run_ledger_runtime import RunLedger

if TYPE_CHECKING:
    from pathlib import Path

_PARENT_IDENTITIES = 50_000


@pytest.mark.unit
def test_single_identity_read_from_large_parent_is_constant_work(
    tmp_path: Path,
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = RunSignature(
        root_identity=str(tmp_path.resolve()),
        collection_identity="codebase_docs",
        source_type=PublicSourceType.CODE,
        operation=RunOperation.FULL,
        clean=True,
        model_identity="benchmark-model",
        dense_dimensions=8,
        embedding_schema=3,
        payload_schema=3,
        content_epoch="content",
        membership_epoch="membership",
        preprocessing_identity="preprocessing",
        configuration_fingerprint="configuration",
        policy_fingerprint="policy",
        backend_identity="benchmark-backend",
    )
    generation = ledger.start_generation(signature)
    proof = ledger.establish_verified_publication(
        generation.generation_id,
        RunAuthority.REBUILD,
        tuple(
            ProofEvidence(
                f"src/file-{index:06d}.py",
                f"content-{index}",
                (f"point-{index}",),
            )
            for index in range(_PARENT_IDENTITIES)
        ),
    )

    target = f"src/file-{_PARENT_IDENTITIES - 1:06d}.py"
    started = time.perf_counter()
    result = ledger.publication_evidence_for_paths(
        proof.compatibility_key,
        (target,),
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert result[target].point_ids == (f"point-{_PARENT_IDENTITIES - 1}",)
    print(
        f"\n[incremental-publication benchmark] parent={_PARENT_IDENTITIES} "
        f"changed=1 lookup_ms={elapsed_ms:.3f}"
    )
