"""Exact durable collection tests for watcher controller intake."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from watchfiles import Change

from ..job_models import JobSource
from ..service import ServiceRegistry
from ..watcher_controller import ControllerState
from ..watcher_intake import (
    _ClassifiedWatcherChange,
    _classify_watcher_changes,
    _ControllerBinding,
    _new_controller,
    _persist_and_observe_batch,
    _WatcherEventBatch,
)
from ..watcher_retry import (
    WatcherPathEvent,
    WatcherRetryPolicy,
    WatcherSource,
)
from ..watcher_runtime import WatcherChangeRouting, WatcherConvergenceSlot

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _binding(
    root: Path,
    source: WatcherSource,
    registry: ServiceRegistry,
) -> _ControllerBinding:
    policy = WatcherRetryPolicy.for_root(root, source)
    slot = WatcherConvergenceSlot(JobSource(source.value), root, registry, policy)
    return _ControllerBinding(_new_controller(policy), slot, policy)


def test_classification_is_immutable_and_does_not_acknowledge_slots(
    tmp_path: Path,
) -> None:
    registry = ServiceRegistry()
    vault = _binding(tmp_path, WatcherSource.VAULT, registry)
    code = _binding(tmp_path, WatcherSource.CODE, registry)
    document = _binding(tmp_path, WatcherSource.DOCUMENT, registry)
    vault_path = tmp_path / ".vault" / "adr" / "decision.md"
    code_path = tmp_path / ".gitignore"
    code_path.write_text("generated/\n", encoding="utf-8")

    batch = _classify_watcher_changes(
        [(Change.modified, str(vault_path)), (Change.added, str(code_path))],
        routing=WatcherChangeRouting(
            root_dir=tmp_path,
            vault_dir=tmp_path / ".vault",
            policy=None,
            vault_slot=vault.slot,
            code_slot=code.slot,
            document_slot=document.slot,
        ),
    )

    assert [(change.source, change.path, change.event) for change in batch.changes] == [
        (WatcherSource.VAULT, vault_path, WatcherPathEvent.MODIFIED),
        (WatcherSource.CODE, code_path, WatcherPathEvent.ADDED),
        (WatcherSource.DOCUMENT, code_path, WatcherPathEvent.ADDED),
    ]
    assert vault.slot.dirty_paths() == frozenset()
    assert code.slot.dirty_paths() == frozenset()


async def test_exact_scope_is_durable_before_legacy_slot_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ServiceRegistry()
    binding = _binding(tmp_path.resolve(), WatcherSource.CODE, registry)
    changed = tmp_path.resolve() / "src" / "example.py"
    persisted_before_ack: list[bool] = []

    async def persist(policy, observations, **_kwargs):
        persisted_before_ack.append(binding.slot.dirty_paths() == frozenset())
        policy.mark_scope_pending(observations, now=time.time())
        return False

    monkeypatch.setattr(
        "vaultspec_rag.watcher_intake.persist_watcher_observations", persist
    )
    batch = _WatcherEventBatch(
        (
            _ClassifiedWatcherChange(
                WatcherSource.CODE,
                changed,
                WatcherPathEvent.MODIFIED,
            ),
        )
    )

    cancelled = await _persist_and_observe_batch(
        batch,
        (binding,),
        root_dir=tmp_path.resolve(),
    )

    assert cancelled is False
    assert persisted_before_ack == [True]
    assert binding.slot.dirty_paths() == frozenset({changed})
    state = binding.retry_policy.state
    assert [(item.relative_path, item.event_kinds) for item in state.pending_paths] == [
        ("src/example.py", frozenset({WatcherPathEvent.MODIFIED}))
    ]
    assert binding.controller.snapshot.state is ControllerState.COLLECTING
    assert binding.controller.snapshot.next_decision_at is not None


async def test_cancellation_is_delivered_after_every_source_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ServiceRegistry()
    root = tmp_path.resolve()
    code = _binding(root, WatcherSource.CODE, registry)
    document = _binding(root, WatcherSource.DOCUMENT, registry)
    committed: list[WatcherSource] = []

    async def persist(policy, observations, *, source, **_kwargs):
        policy.mark_scope_pending(observations, now=time.time())
        committed.append(source)
        return source is WatcherSource.CODE

    monkeypatch.setattr(
        "vaultspec_rag.watcher_intake.persist_watcher_observations", persist
    )
    batch = _WatcherEventBatch(
        (
            _ClassifiedWatcherChange(
                WatcherSource.CODE, root / "src" / "a.py", WatcherPathEvent.ADDED
            ),
            _ClassifiedWatcherChange(
                WatcherSource.DOCUMENT,
                root / "docs" / "a.pdf",
                WatcherPathEvent.ADDED,
            ),
        )
    )

    cancelled = await _persist_and_observe_batch(
        batch,
        (code, document),
        root_dir=root,
    )

    assert cancelled is True
    assert committed == [WatcherSource.CODE, WatcherSource.DOCUMENT]
    assert code.retry_policy.state.pending_paths
    assert document.retry_policy.state.pending_paths
