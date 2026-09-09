"""Cross-component guards for explicit full-reindex authority."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ..._source_types import PublicSourceType
from ...indexer._run_ledger_models import RunOperation, RunSignature
from ...indexer._run_policy import DurableProgressKind, RunPolicy
from ...store_runtime import VaultStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _signature(root: Path, backend_identity: str) -> RunSignature:
    return RunSignature(
        root_identity=str(root.resolve()),
        collection_identity="codebase_docs",
        source_type=PublicSourceType.CODE,
        operation=RunOperation.FULL,
        clean=False,
        model_identity="model",
        dense_dimensions=8,
        embedding_schema=1,
        payload_schema=1,
        content_epoch="content",
        membership_epoch="membership",
        preprocessing_identity="preprocess",
        configuration_fingerprint="configuration",
        policy_fingerprint="policy",
        backend_identity=backend_identity,
    )


def test_local_store_identity_invalidates_server_evidence(tmp_path: Path) -> None:
    store = VaultStore(tmp_path)
    try:
        local = _signature(tmp_path, store.backend_identity)
        server = replace(local, backend_identity="qdrant-server:http://127.0.0.1:6333")

        assert store.backend_identity.startswith("qdrant-local:")
        assert local.content_compatibility_fingerprint != (
            server.content_compatibility_fingerprint
        )
    finally:
        store.close()


def test_committed_reconciliation_batches_extend_liveness() -> None:
    policy = RunPolicy(no_progress_timeout_seconds=1.0)

    snapshot = policy.record_durable_progress(
        kind=DurableProgressKind.RECONCILIATION_BATCH_COMMITTED,
        label="stale route purge committed",
    )

    assert snapshot.durable_progress_count == 1
    assert snapshot.last_progress_kind is (
        DurableProgressKind.RECONCILIATION_BATCH_COMMITTED
    )
    assert not snapshot.expired
