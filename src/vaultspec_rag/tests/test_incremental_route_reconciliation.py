"""Receipt-backed route reconciliation touches only confirmed changed identities."""

from __future__ import annotations

import hashlib
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from .._store_models import CodeChunk, DocumentChunk, DocumentPayload
from ..config._settings import get_config
from ..config._types import EnvVar
from ..indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._document_checkpoint import (
    DocumentRunCheckpoint,
    DocumentRunConfiguration,
    DocumentRunOpenRequest,
)
from ..indexer._document_identity import document_point_id
from ..indexer._publication_proof import ProofReceiptState
from ..indexer._resolved_policy import (
    IndexPolicyResolutionOptions,
    ResolvedIndexPolicy,
    resolve_index_policy,
)
from ..indexer._route_migration import (
    RouteScanOptions,
    iter_stored_route_pages,
    reconcile_checkpoint_routes,
    reconcile_generation_storage,
)
from ..indexer._run_ledger_models import CommitUnitKind, RunAuthority, RunOperation
from ..indexer._run_ledger_publication_identity import compatibility_for_signature
from ..indexer._run_policy import RunPolicy
from ..store_runtime import VaultStore
from ._store_fixtures import get_all_document_content_ids
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path
    from types import FrameType

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _RouteStore:
    root: Path
    store: VaultStore
    policy: ResolvedIndexPolicy


@dataclass(frozen=True)
class _RouteScroll:
    source: str
    paths: frozenset[str] | None


@contextmanager
def _observed_route_scrolls() -> Generator[list[_RouteScroll]]:
    """Observe real scroll calls while leaving storage behavior untouched."""
    calls: list[_RouteScroll] = []
    methods = {
        VaultStore.scroll_code_content.__code__: "code",
        VaultStore.scroll_document_content.__code__: "document",
        VaultStore.scroll_index_audit_content.__code__: "audit",
    }

    def observe(frame: FrameType, event: str, _argument: object) -> None:
        if event != "call" or frame.f_code not in methods:
            return
        raw_paths: object = frame.f_locals["source_paths"]
        paths = None if raw_paths is None else frozenset(cast("set[str]", raw_paths))
        source = methods[frame.f_code]
        if source == "audit":
            store = cast("VaultStore", frame.f_locals["self"])
            source = (
                "code"
                if frame.f_locals["collection"] == store.CODE_TABLE_NAME
                else "document"
            )
        calls.append(_RouteScroll(source, paths))

    previous = sys.getprofile()
    sys.setprofile(observe)
    try:
        yield calls
    finally:
        sys.setprofile(previous)


@pytest.fixture
def route_store(tmp_path: Path) -> Iterator[_RouteStore]:
    with (
        managed_env(
            **{
                EnvVar.QDRANT_URL.value: None,
                EnvVar.LOCAL_ONLY.value: "1",
                EnvVar.EMBEDDING_DIMENSION.value: "4",
            }
        ),
        VaultStore(tmp_path) as store,
    ):
        policy = resolve_index_policy(
            tmp_path,
            IndexPolicyResolutionOptions(
                content_policy=RootContentPolicy(
                    SourceProfileVersion.EXPLICIT_ONLY_V1,
                    (
                        ContentRoute("*.txt", ContentKind.DOCUMENT),
                        ContentRoute("*.py", ContentKind.CODE),
                    ),
                )
            ),
        )
        yield _RouteStore(tmp_path, store, policy)


def _document(path: str, content: str) -> DocumentChunk:
    digest = hashlib.blake2b(content.encode("utf-8")).hexdigest()
    return DocumentChunk(
        id=document_point_id(
            source_path=path,
            unit_ordinal=0,
            content_fingerprint=digest,
            locator=None,
        ),
        payload=DocumentPayload(path, 0, digest, content),
        vector=[0.1, 0.2, 0.3, 0.4],
    )


def _code(path: str) -> CodeChunk:
    return CodeChunk(
        id=f"legacy:{path}",
        path=path,
        language="python",
        content="value = 1",
        line_start=1,
        line_end=1,
        vector=[0.1, 0.2, 0.3, 0.4],
    )


def _checkpoint(harness: _RouteStore, operation: RunOperation) -> DocumentRunCheckpoint:
    return DocumentRunCheckpoint.open_generation(
        DocumentRunOpenRequest(
            data_root=harness.root / get_config().data_dir,
            root_dir=harness.root,
            policy=harness.policy,
            run_policy=RunPolicy(no_progress_timeout_seconds=60),
            operation=operation,
            authority=(
                RunAuthority.REBUILD
                if operation is RunOperation.FULL
                else RunAuthority.PUBLICATION
            ),
            clean=operation is RunOperation.FULL,
            model_identity="route-reconciliation-test",
            backend_identity=harness.store.backend_identity,
            dense_dimensions=4,
            configuration=DocumentRunConfiguration(
                slice_max_chunks=1,
                source_bytes=1,
                generated_chunks=1,
                weighted_bytes=1,
                sparse_enabled=False,
                sparse_dimension=1,
                encode_batch_size=1,
            ),
        )
    )


def _write(
    harness: _RouteStore,
    checkpoint: DocumentRunCheckpoint,
    chunks: list[DocumentChunk],
) -> None:
    for chunk in chunks:
        unit = checkpoint.unit_for(
            chunk.payload.source_path,
            chunk.payload.content_fingerprint,
            0,
            is_file_end=True,
            point_ids=(chunk.id,),
        )
        lifecycle = checkpoint.mutation_lifecycle(unit)
        if lifecycle is not None:
            assert lifecycle.prepare()
        harness.store.upsert_document_content_chunks([chunk], write_policy=None)
        if lifecycle is not None:
            lifecycle.mark_applied()
            lifecycle.confirm()
        checkpoint.record_confirmed_slice(unit)


def _publish_parent(harness: _RouteStore, chunks: list[DocumentChunk]) -> None:
    checkpoint = _checkpoint(harness, RunOperation.FULL)
    _write(harness, checkpoint, chunks)
    checkpoint.publish_proof_transition()
    checkpoint.publish_generation()


def _delete_superseded(
    harness: _RouteStore,
    checkpoint: DocumentRunCheckpoint,
    chunk: DocumentChunk,
) -> None:
    path = chunk.payload.source_path
    lifecycle = checkpoint.deletion_lifecycle(
        path, CommitUnitKind.DELETE_STALE, (chunk.id,)
    )
    assert lifecycle is not None and lifecycle.prepare()
    harness.store.delete_document_content_chunks([chunk.id])
    lifecycle.mark_applied()
    lifecycle.confirm()
    checkpoint.record_confirmed_stale_deletion(path, (chunk.id,))


def test_incremental_cleanup_preserves_unchanged_and_unrelated_stale_rows(
    route_store: _RouteStore,
) -> None:
    """Scope removal lost the sentinel; disabling full scans left it behind.

    Each mutation failed its retained-row or removal-count assertion, and the
    restored implementation passed before the next mutation.
    Omitting the raw audit projection's path filter failed the observed scope
    assertion; restoring the filter passed against the same real store.
    """
    old = _document("changed.txt", "old source")
    unchanged = _document("unchanged.txt", "unchanged source")
    stale = _document("changed.txt", "unpublished stale row")
    sentinel = _document("unrelated.txt", "unrelated stale sentinel")
    replacement = _document("changed.txt", "new source")
    _publish_parent(route_store, [old, unchanged])
    route_store.store.upsert_document_content_chunks(
        [stale, sentinel], write_policy=None
    )
    incremental = _checkpoint(route_store, RunOperation.INCREMENTAL)
    _write(route_store, incremental, [replacement])
    _delete_superseded(route_store, incremental, old)

    with _observed_route_scrolls() as calls:
        result = reconcile_generation_storage(
            route_store.store,
            incremental,
            route_store.policy,
            ContentKind.DOCUMENT,
        )

    assert {call.source for call in calls} == {"code", "document"}
    assert all(call.paths == frozenset({"changed.txt"}) for call in calls)

    assert get_all_document_content_ids(route_store.store) == {
        replacement.id,
        unchanged.id,
        sentinel.id,
    }
    assert result == (0, 1, 0)
    incremental.publish_proof_transition()
    incremental.publish_generation()
    key = compatibility_for_signature(incremental.generation.signature)
    proof = incremental.ledger.publication_proof(key)
    assert proof.aggregate.indexed_identities == proof.aggregate.retained_points == 2

    rebuilt = _checkpoint(route_store, RunOperation.FULL)
    _write(route_store, rebuilt, [replacement, unchanged])
    assert reconcile_generation_storage(
        route_store.store, rebuilt, route_store.policy, ContentKind.DOCUMENT
    ) == (0, 1, 0)
    assert get_all_document_content_ids(route_store.store) == {
        replacement.id,
        unchanged.id,
    }


def test_noop_reconciliation_performs_no_route_scrolls(
    route_store: _RouteStore,
) -> None:
    """An unscoped no-op failed the observed-read assertion; restoration passed."""
    unchanged = _document("unchanged.txt", "unchanged source")
    sentinel = _document("unrelated.txt", "unrelated stale sentinel")
    _publish_parent(route_store, [unchanged])
    route_store.store.upsert_document_content_chunks([sentinel], write_policy=None)
    incremental = _checkpoint(route_store, RunOperation.INCREMENTAL)

    with _observed_route_scrolls() as calls:
        try:
            result = reconcile_generation_storage(
                route_store.store,
                incremental,
                route_store.policy,
                ContentKind.DOCUMENT,
            )
        finally:
            assert calls == [], "a no-op must not scan content collections"

    assert result == (0, 0, 0)
    assert get_all_document_content_ids(route_store.store) == {
        unchanged.id,
        sentinel.id,
    }
    receipt = incremental.ledger.publication_receipt_for_generation(
        incremental.generation_id
    )
    assert receipt is not None and receipt.state is ProofReceiptState.ROLLED_BACK


def test_more_than_one_batch_reconciles_only_affected_paths(
    route_store: _RouteStore,
) -> None:
    unchanged = _document("unchanged.txt", "unchanged source")
    sentinel = _document("unrelated.txt", "unrelated stale sentinel")
    _publish_parent(route_store, [unchanged])
    replacements = [
        _document(f"changed-{ordinal:03d}.txt", "new source") for ordinal in range(257)
    ]
    stale = [
        _document(chunk.payload.source_path, "unpublished stale row")
        for chunk in replacements
    ]
    route_store.store.upsert_document_content_chunks(
        [*stale, sentinel], write_policy=None
    )
    incremental = _checkpoint(route_store, RunOperation.INCREMENTAL)
    _write(route_store, incremental, replacements)

    with _observed_route_scrolls() as calls:
        result = reconcile_generation_storage(
            route_store.store,
            incremental,
            route_store.policy,
            ContentKind.DOCUMENT,
        )

    assert result == (0, 257, 0)
    assert get_all_document_content_ids(route_store.store) == {
        unchanged.id,
        sentinel.id,
        *(chunk.id for chunk in replacements),
    }
    affected = frozenset(chunk.payload.source_path for chunk in replacements)
    assert calls
    assert all(call.paths is not None and 0 < len(call.paths) <= 256 for call in calls)
    for source in ("code", "document"):
        batches = {call.paths for call in calls if call.source == source}
        assert len(batches) >= 2
        assert frozenset().union(*(batch for batch in batches if batch)) == affected


def test_cross_kind_cleanup_requires_the_confirmed_destination_to_exist(
    route_store: _RouteStore,
) -> None:
    """Bypassing destination evidence lost an origin; restoration retained it."""
    unchanged = _document("unchanged.txt", "unchanged source")
    _publish_parent(route_store, [unchanged])
    valid = _document("valid.txt", "complete destination")
    lost = _document("lost.txt", "formerly confirmed destination")
    origins = [_code("valid.txt"), _code("lost.txt"), _code("unchanged.txt")]
    route_store.store.upsert_code_chunks(origins, write_policy=None)
    incremental = _checkpoint(route_store, RunOperation.INCREMENTAL)
    _write(route_store, incremental, [valid, lost])
    route_store.store.delete_document_content_chunks([lost.id])

    result = reconcile_generation_storage(
        route_store.store, incremental, route_store.policy, ContentKind.DOCUMENT
    )
    assert route_store.store.get_all_code_ids() == {origins[1].id, origins[2].id}
    assert result == (0, 0, 1)
    assert get_all_document_content_ids(route_store.store) == {
        unchanged.id,
        valid.id,
    }


@pytest.mark.parametrize("kind", [ContentKind.CODE, ContentKind.DOCUMENT])
def test_route_scan_limits_each_source_to_requested_paths(
    route_store: _RouteStore, kind: ContentKind
) -> None:
    """Removing either real-store filter returned an extra path; restoration passed."""
    if kind is ContentKind.CODE:
        wanted, unrelated = "wanted.py", "unrelated.py"
        route_store.store.upsert_code_chunks(
            [_code(wanted), _code(unrelated)], write_policy=None
        )
    else:
        wanted, unrelated = "wanted.txt", "unrelated.txt"
        route_store.store.upsert_document_content_chunks(
            [_document(wanted, "wanted"), _document(unrelated, "unrelated")],
            write_policy=None,
        )

    pages = list(
        iter_stored_route_pages(
            route_store.store,
            route_store.policy,
            kind,
            options=RouteScanOptions(source_paths=frozenset({wanted})),
        )
    )

    assert {row.source_path for page in pages for row in page} == {wanted}


def test_route_scan_refuses_an_oversized_path_selection(
    route_store: _RouteStore,
) -> None:
    """Removing the selection limit failed to raise; restoration rejected it."""
    with pytest.raises(
        ValueError, match=r"^route path selection exceeds the bounded lookup batch$"
    ):
        list(
            iter_stored_route_pages(
                route_store.store,
                route_store.policy,
                ContentKind.DOCUMENT,
                options=RouteScanOptions(
                    source_paths=frozenset(
                        f"source-{ordinal}.txt" for ordinal in range(257)
                    )
                ),
            )
        )


def test_cross_kind_reconciliation_rejects_private_origin_collection(
    route_store: _RouteStore,
) -> None:
    """Removing the origin guard failed to raise; restoration retained all rows."""
    unchanged = _document("unchanged.txt", "unchanged source")
    _publish_parent(route_store, [unchanged])
    destination = _document("changed.txt", "confirmed destination")
    incremental = _checkpoint(route_store, RunOperation.INCREMENTAL)
    _write(route_store, incremental, [destination])
    shared_origin = _code("changed.txt")
    served_only = _code("served-only.txt")
    private_only = _code("private-only.txt")
    private_collection = route_store.store.DERIVED_CODE_TABLE_NAME + "_gprivate"
    route_store.store.upsert_code_chunks(
        [shared_origin, served_only], write_policy=None
    )
    route_store.store.upsert_code_chunks(
        [shared_origin, private_only],
        write_policy=None,
        collection=private_collection,
    )

    with (
        _observed_route_scrolls() as calls,
        pytest.raises(
            ValueError,
            match=r"^cross-kind reconciliation requires served origin collections$",
        ),
    ):
        reconcile_checkpoint_routes(
            route_store.store,
            incremental,
            route_store.policy,
            ContentKind.DOCUMENT,
            options=RouteScanOptions(code_collection=private_collection),
        )

    assert calls == []
    assert route_store.store.get_all_code_ids() == {shared_origin.id, served_only.id}
    assert route_store.store.get_all_code_ids(private_collection) == {
        shared_origin.id,
        private_only.id,
    }
    assert get_all_document_content_ids(route_store.store) == {
        unchanged.id,
        destination.id,
    }
