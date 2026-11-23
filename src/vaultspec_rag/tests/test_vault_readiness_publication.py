"""Vault public indexing notifies readiness only after durable publication."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest

from .._publication_state import acquire_publication_snapshot
from .._source_types import PublicSourceType
from ..config._types import EnvVar
from ..graph_cache import GraphCache
from ..indexer import _vault_incremental, _vault_indexer
from ..indexer._run_ledger_models import RunTerminalState
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..indexer._vault_indexer import VaultIndexer
from ..job_models import JobSource
from ..progress import NullProgressReporter
from ..service import ProjectSlot, ServiceRegistry
from ._config_fixtures import reset_config

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..store_runtime import VaultStore

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path: Path) -> Generator[VaultStore]:
    """Open a real local store for *tmp_path* with two-wide dense vectors."""
    from ..config._settings import get_config
    from ..store_runtime import VaultStore

    get_config({"qdrant_url": None, "embedding_dimension": 2, "sparse_enabled": False})
    with VaultStore(tmp_path.resolve(), embedding_dim=2) as opened:
        yield opened


def _no_encode(request: object) -> dict[str, int]:
    del request
    return {}


def _empty_indexer(
    store: VaultStore,
    monkeypatch: pytest.MonkeyPatch,
) -> VaultIndexer:
    # Only model work is substituted. Discovery, checkpoint, receipts, the
    # store, public full/scoped entry and durable publication stay production.
    root = store.root_dir
    root.joinpath(".vault").mkdir(exist_ok=True)
    indexer = VaultIndexer(
        root,
        cast("EmbeddingModel", Mock(device="cpu")),
        store,
    )
    monkeypatch.setattr(indexer, "_resolve_reuse", lambda: (None, None))
    for module in (_vault_indexer, _vault_incremental):
        monkeypatch.setattr(module, "_stream_encode_and_upsert_vault", _no_encode)
    return indexer


@pytest.mark.parametrize("operation", ["full", "incremental", "scoped"])
async def test_actual_vault_publication_wakes_the_pending_target_after_durable(
    store: VaultStore,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    root = store.root_dir
    indexer = _empty_indexer(store, monkeypatch)
    indexer.full_index(reporter=NullProgressReporter())
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    events: list[str] = []

    def notify(published_root: Path, generation: str) -> None:
        proof = acquire_publication_snapshot(published_root, PublicSourceType.VAULT)
        proof.validate()
        completed = proof.ledger.generation(generation)
        assert completed.terminal_state is RunTerminalState.SUCCEEDED
        notified = ServiceRegistry._publish_readiness(
            readiness, JobSource.VAULT, published_root, generation
        )
        assert notified is not None
        assert notified.published_generation == proof.proof.generation_id
        events.append(proof.proof.generation_id)

    indexer._publish_readiness = notify
    try:
        readiness.snapshot(root, "vault")
        pending = readiness.notify_controller(root, "vault").publication_target()
        assert pending is not None
        waiting = asyncio.create_task(
            readiness.published_at_least((pending,), timeout_seconds=2)
        )
        await asyncio.sleep(0)
        assert readiness._observers
        if operation == "full":
            result = indexer.full_index(reporter=NullProgressReporter())
        else:
            result = indexer.incremental_index(
                reporter=NullProgressReporter(),
                changed_paths=[] if operation == "scoped" else None,
            )
        # Mutation: omitting notification in any actual publication caller
        # leaves the target pending despite a durable no-op publication.
        assert len(events) == 1, "vault publication notifies exactly once"
        assert await waiting, "durable vault publication wakes bounded freshness"
        assert result.total == 0
        assert readiness.snapshot(root, "vault").published_generation == events[0]
    finally:
        readiness.close()


@pytest.mark.parametrize("boundary", ["proof", "generation"])
async def test_failed_vault_publication_emits_no_notification(
    store: VaultStore,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    indexer = _empty_indexer(store, monkeypatch)
    events: list[str] = []

    def notify(root: Path, generation: str) -> None:
        del root
        events.append(generation)

    indexer._publish_readiness = notify

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError(f"{boundary} publication failed")

    monkeypatch.setattr(
        VaultRunCheckpoint,
        f"publish_{'proof_transition' if boundary == 'proof' else 'generation'}",
        fail,
    )
    with pytest.raises(OSError, match=f"{boundary} publication failed"):
        indexer.full_index(reporter=NullProgressReporter())
    # Mutation: moving notification before the durable boundary violates this.
    assert events == [], "failed publication cannot notify readiness"


async def test_actual_runtime_construction_wires_vault_publication(
    tmp_path: Path,
    store: VaultStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(EnvVar.RERANKER_ENABLED.value, "0")
    reset_config()
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    model = cast("EmbeddingModel", Mock(device="cpu"))

    def load_model(self: ServiceRegistry, model_name: str | None) -> None:
        del model_name
        self._model = model

    monkeypatch.setattr(ServiceRegistry, "_load_model", load_model)
    slot = ProjectSlot(store, GraphCache())
    try:
        runtime = registry._create_compute_runtime(tmp_path, slot, None)
        callback = runtime.vault_indexer._publish_readiness
        # Mutation: dropping the actual constructor keyword loses this wiring.
        assert callback is not None, "runtime constructor wires vault publication"
        monkeypatch.setattr(
            runtime.vault_indexer, "_resolve_reuse", lambda: (None, None)
        )
        monkeypatch.setattr(
            _vault_indexer, "_stream_encode_and_upsert_vault", _no_encode
        )
        runtime.vault_indexer.full_index(reporter=NullProgressReporter())
        proof = acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT)
        assert (
            registry.readiness_registry.snapshot(tmp_path, "vault").published_generation
            == proof.proof.generation_id
        )
        assert (
            registry.readiness_registry.snapshot(
                tmp_path, "document"
            ).published_generation
            is None
        )
    finally:
        registry.readiness_registry.close()
        reset_config()
