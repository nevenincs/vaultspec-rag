"""Watcher evidence for prior ownership and independent content-kind intake."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from watchfiles import Change

from ... import store_schema
from ...config import get_config
from ...indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ...indexer._file_state import FileState
from ...indexer._resolved_policy import resolve_index_policy
from ...indexer._run_ledger import (
    CommitUnit,
    CommitUnitKind,
    RunLedger,
    RunOperation,
    RunSignature,
    index_run_ledger_path,
)
from ...job_models import JobSource
from ...service import ServiceRegistry
from ...watcher import _record_watcher_changes, _WatcherConvergenceSlot
from ...watcher_retry import WatcherRetryPolicy, WatcherSource

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]


def _policy(root: Path):
    return resolve_index_policy(
        root,
        content_policy=RootContentPolicy(
            SourceProfileVersion.EXPLICIT_ONLY_V1,
            (ContentRoute("removed.txt", ContentKind.DOCUMENT),),
        ),
    )


def _slots(root: Path, registry: ServiceRegistry):
    vault = _WatcherConvergenceSlot(
        JobSource.VAULT,
        root,
        registry,
        WatcherRetryPolicy.for_root(root, WatcherSource.VAULT),
    )
    code = _WatcherConvergenceSlot(
        JobSource.CODE,
        root,
        registry,
        WatcherRetryPolicy.for_root(root, WatcherSource.CODE),
    )
    document = _WatcherConvergenceSlot(
        JobSource.DOCUMENT,
        root,
        registry,
        WatcherRetryPolicy.for_root(root, WatcherSource.DOCUMENT),
    )
    return vault, code, document


def _record_prior_code_owner(root: Path, rel_path: str) -> None:
    ledger = RunLedger(index_run_ledger_path(root / get_config().data_dir))
    signature = RunSignature(
        root_identity=str(root.resolve()),
        collection_identity=store_schema.CODE_COLLECTION,
        source_type=ContentKind.CODE,
        operation=RunOperation.FULL,
        clean=False,
        model_identity="watcher-prior-owner-test",
        dense_dimensions=4,
        embedding_schema=1,
        payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
        content_epoch="content",
        membership_epoch="membership",
        preprocessing_identity="preprocessing",
        configuration_fingerprint="configuration",
        policy_fingerprint="policy",
    )
    generation = ledger.start_generation(signature)
    digest = hashlib.blake2b(rel_path.encode("utf-8")).hexdigest()
    ledger.record_storage_confirmed_unit(
        generation.generation_id,
        CommitUnit(
            rel_path=rel_path,
            kind=CommitUnitKind.UPSERT,
            source_digest=digest,
            segment_ordinal=0,
            is_file_end=True,
            point_ids=("prior-code-point",),
        ),
    )
    ledger.record_file_state(
        generation.generation_id,
        FileState.indexed(rel_path, ContentKind.CODE, digest),
    )


def test_deleted_path_uses_prior_ledger_owner_not_current_route(
    clean_config: None,
    tmp_path: Path,
) -> None:
    del clean_config
    rel_path = "removed.txt"
    deleted = tmp_path / rel_path
    _record_prior_code_owner(tmp_path, rel_path)
    registry = ServiceRegistry()
    try:
        vault, code, document = _slots(tmp_path, registry)

        observed = _record_watcher_changes(
            [(Change.deleted, str(deleted))],
            root_dir=tmp_path,
            vault_dir=tmp_path / ".vault",
            policy=_policy(tmp_path),
            vault_slot=vault,
            code_slot=code,
            document_slot=document,
        )

        assert observed == (False, True, False)
        assert code.dirty_paths() == frozenset({deleted})
        assert document.dirty_paths() == frozenset()
    finally:
        registry.close_all()


def test_policy_control_event_schedules_code_and_document_independently(
    clean_config: None,
    tmp_path: Path,
) -> None:
    del clean_config
    control = tmp_path / ".vaultragignore"
    control.write_text("generated/**\n", encoding="utf-8")
    registry = ServiceRegistry()
    try:
        vault, code, document = _slots(tmp_path, registry)

        observed = _record_watcher_changes(
            [(Change.modified, str(control))],
            root_dir=tmp_path,
            vault_dir=tmp_path / ".vault",
            policy=_policy(tmp_path),
            vault_slot=vault,
            code_slot=code,
            document_slot=document,
        )

        assert observed == (False, True, True)
        assert code.dirty_paths() == frozenset({control})
        assert document.dirty_paths() == frozenset({control})
        assert code.retry_policy.state.source is WatcherSource.CODE
        assert document.retry_policy.state.source is WatcherSource.DOCUMENT
    finally:
        registry.close_all()
