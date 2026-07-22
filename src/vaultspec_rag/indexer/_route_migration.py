"""Bounded, destination-first reconciliation across content collections."""

from __future__ import annotations

import hashlib
import itertools
import json
import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from .. import store_schema
from ._content_policy import ContentKind
from ._run_ledger import RunLedger, index_run_ledger_path

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..store import VaultStore
    from ._file_state import FileState
    from ._resolved_policy import ResolvedIndexPolicy
    from ._run_policy import RunPolicy

__all__ = [
    "RouteMigration",
    "RouteMigrationJournal",
    "RouteMigrationPhase",
    "StoredRouteRow",
    "iter_stored_route_pages",
    "origin_point_ids",
    "prior_stored_owners",
    "purge_unpublished_rows",
    "reconcile_checkpoint_routes",
    "reconcile_generation_storage",
    "reconcile_origin_after_destination",
    "resume_pending_migrations",
]

_DEFAULT_PAGE_SIZE = 256
_LEDGER_LOOKUP_BATCH = 256
_MIGRATION_JOURNAL_FILENAME = "route_migrations.sqlite3"


class DestinationCheckpoint(Protocol):
    """Minimum generation authority required for cross-kind cleanup."""

    @property
    def generation_id(self) -> str: ...

    @property
    def ledger(self) -> RunLedger: ...

    @property
    def run_policy(self) -> RunPolicy: ...


class RouteMigrationPhase(StrEnum):
    """Durable destination-first migration boundaries."""

    DESTINATION_CONFIRMED = "destination_confirmed"
    ORIGIN_DELETED = "origin_deleted"


@dataclass(frozen=True, slots=True)
class RouteMigration:
    """One idempotent target flip persisted outside collection sidecars."""

    migration_id: str
    rel_path: str
    origin_kind: ContentKind
    destination_kind: ContentKind
    destination_generation_id: str
    point_ids: tuple[str, ...]
    phase: RouteMigrationPhase


class RouteMigrationJournal:
    """Small CPU-only authority for target-flip cleanup replay."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS route_migrations (
                    migration_id TEXT PRIMARY KEY,
                    rel_path TEXT NOT NULL,
                    origin_kind TEXT NOT NULL,
                    destination_kind TEXT NOT NULL,
                    destination_generation_id TEXT NOT NULL,
                    point_ids_json TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS route_migrations_phase
                    ON route_migrations(phase, updated_at);
                """
            )

    def begin(
        self,
        *,
        rel_path: str,
        origin_kind: ContentKind,
        destination_kind: ContentKind,
        destination_generation_id: str,
        point_ids: tuple[str, ...],
    ) -> RouteMigration:
        """Persist origin identities only after destination confirmation."""
        migration_id = _migration_id(
            rel_path,
            origin_kind,
            destination_kind,
            destination_generation_id,
            point_ids,
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM route_migrations WHERE migration_id = ?",
                (migration_id,),
            ).fetchone()
            if existing is None:
                if not point_ids:
                    raise ValueError("a new route migration requires origin point IDs")
                now = time.time()
                connection.execute(
                    """
                    INSERT INTO route_migrations (
                        migration_id, rel_path, origin_kind, destination_kind,
                        destination_generation_id, point_ids_json, phase,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        migration_id,
                        rel_path,
                        origin_kind.value,
                        destination_kind.value,
                        destination_generation_id,
                        json.dumps(tuple(sorted(point_ids)), separators=(",", ":")),
                        RouteMigrationPhase.DESTINATION_CONFIRMED.value,
                        now,
                        now,
                    ),
                )
                existing = connection.execute(
                    "SELECT * FROM route_migrations WHERE migration_id = ?",
                    (migration_id,),
                ).fetchone()
            assert existing is not None
            return _migration_from_row(existing)

    def mark_origin_deleted(self, migration_id: str) -> RouteMigration:
        """Commit origin deletion after the idempotent store call returns."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE route_migrations
                SET phase = ?, updated_at = ?
                WHERE migration_id = ?
                """,
                (
                    RouteMigrationPhase.ORIGIN_DELETED.value,
                    time.time(),
                    migration_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM route_migrations WHERE migration_id = ?",
                (migration_id,),
            ).fetchone()
        if row is None:
            raise KeyError(migration_id)
        return _migration_from_row(row)

    def pending(self) -> Iterator[RouteMigration]:
        """Yield destination-confirmed cleanup obligations row by row."""
        last_key: tuple[float, str] | None = None
        while True:
            with self._connect() as connection:
                if last_key is None:
                    rows = connection.execute(
                        """
                        SELECT * FROM route_migrations
                        WHERE phase = ? ORDER BY updated_at, migration_id
                        LIMIT ?
                        """,
                        (
                            RouteMigrationPhase.DESTINATION_CONFIRMED.value,
                            _DEFAULT_PAGE_SIZE,
                        ),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT * FROM route_migrations
                        WHERE phase = ? AND (updated_at, migration_id) > (?, ?)
                        ORDER BY updated_at, migration_id LIMIT ?
                        """,
                        (
                            RouteMigrationPhase.DESTINATION_CONFIRMED.value,
                            *last_key,
                            _DEFAULT_PAGE_SIZE,
                        ),
                    ).fetchall()
            if not rows:
                return
            for row in rows:
                yield _migration_from_row(row)
            last = rows[-1]
            last_key = (float(last["updated_at"]), str(last["migration_id"]))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection


@dataclass(frozen=True, slots=True)
class StoredRouteRow:
    """One stored point freshly classified by the current policy."""

    point_id: str
    source_path: str
    stored_kind: ContentKind
    current_kind: ContentKind | None
    admitted: bool


def iter_stored_route_pages(
    store: VaultStore,
    policy: ResolvedIndexPolicy,
    stored_kind: ContentKind,
    *,
    page_size: int = _DEFAULT_PAGE_SIZE,
    run_policy: RunPolicy | None = None,
) -> Iterator[tuple[StoredRouteRow, ...]]:
    """Yield freshly classified store rows without trusting a sidecar."""
    if isinstance(page_size, bool) or page_size <= 0 or page_size > 1000:
        raise ValueError("route migration page size must be between 1 and 1000")
    offset: object | None = None
    while True:
        if run_policy is not None:
            run_policy.checkpoint(f"{stored_kind.value} route page before scroll")
        if stored_kind is ContentKind.CODE:
            rows, next_offset = store.scroll_code_content(
                limit=page_size,
                offset=offset,
            )
            path_key = "path"
            id_key = "chunk_id"
        else:
            rows, next_offset = store.scroll_document_content(
                limit=page_size,
                offset=offset,
            )
            path_key = "source_path"
            id_key = "document_id"
        page: list[StoredRouteRow] = []
        for row in rows:
            raw_path = row["payload"].get(path_key)
            if not isinstance(raw_path, str) or not raw_path:
                continue
            disposition = policy.classify(raw_path).disposition
            page.append(
                StoredRouteRow(
                    point_id=str(row["payload"].get(id_key) or row["id"]),
                    source_path=raw_path,
                    stored_kind=stored_kind,
                    current_kind=disposition.kind,
                    admitted=disposition.admitted,
                )
            )
        if page:
            yield tuple(page)
        if run_policy is not None:
            run_policy.checkpoint(f"{stored_kind.value} route page after scroll")
        if next_offset is None:
            return
        offset = next_offset


def origin_point_ids(
    store: VaultStore,
    origin_kind: ContentKind,
    rel_path: str,
    *,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> tuple[str, ...]:
    """Read at most one bounded page of identities for an origin path."""
    if isinstance(page_size, bool) or page_size <= 0 or page_size > 1000:
        raise ValueError("route migration page size must be between 1 and 1000")
    if origin_kind is ContentKind.CODE:
        rows, _next_offset = store.scroll_code_content(
            limit=page_size,
            source_paths={rel_path},
        )
    else:
        rows, _next_offset = store.scroll_document_content(
            limit=page_size,
            source_paths={rel_path},
        )
    id_key = "chunk_id" if origin_kind is ContentKind.CODE else "document_id"
    return tuple(sorted(str(row["payload"].get(id_key) or row["id"]) for row in rows))


def reconcile_origin_after_destination(
    store: VaultStore,
    checkpoint: DestinationCheckpoint,
    destination_kind: ContentKind,
    rel_path: str,
) -> int:
    """Delete a prior owner only after destination storage is confirmed."""
    if not checkpoint.ledger.file_complete(checkpoint.generation_id, rel_path):
        raise RuntimeError("destination is incomplete; origin cleanup is forbidden")
    origin_kind = (
        ContentKind.DOCUMENT
        if destination_kind is ContentKind.CODE
        else ContentKind.CODE
    )
    journal = RouteMigrationJournal(
        checkpoint.ledger.path.parent / _MIGRATION_JOURNAL_FILENAME
    )
    if not _destination_evidence_is_current(
        store,
        checkpoint.ledger,
        destination_generation_id=checkpoint.generation_id,
        destination_kind=destination_kind,
        rel_path=rel_path,
        run_policy=checkpoint.run_policy,
    ):
        return 0
    checkpoint.run_policy.checkpoint("route migration resume entry")
    removed = _resume_path_migrations(
        store,
        journal,
        rel_path=rel_path,
        origin_kind=origin_kind,
        destination_kind=destination_kind,
        destination_generation_id=checkpoint.generation_id,
    )
    while point_ids := origin_point_ids(store, origin_kind, rel_path):
        checkpoint.run_policy.checkpoint("route migration before journal")
        migration = journal.begin(
            rel_path=rel_path,
            origin_kind=origin_kind,
            destination_kind=destination_kind,
            destination_generation_id=checkpoint.generation_id,
            point_ids=point_ids,
        )
        checkpoint.run_policy.checkpoint("route migration before origin delete")
        _delete_origin_points(store, migration)
        journal.mark_origin_deleted(migration.migration_id)
        removed += len(migration.point_ids)
        checkpoint.run_policy.checkpoint("route migration after origin delete")
    return removed


def reconcile_checkpoint_routes(
    store: VaultStore,
    checkpoint: DestinationCheckpoint,
    policy: ResolvedIndexPolicy,
    destination_kind: ContentKind,
    *,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> int:
    """Reconcile complete destinations through one bounded origin scan."""
    origin_kind = (
        ContentKind.DOCUMENT
        if destination_kind is ContentKind.CODE
        else ContentKind.CODE
    )
    journal = RouteMigrationJournal(
        checkpoint.ledger.path.parent / _MIGRATION_JOURNAL_FILENAME
    )
    destination_evidence: dict[str, bool] = {}
    removed = 0
    for page in iter_stored_route_pages(
        store,
        policy,
        origin_kind,
        page_size=page_size,
        run_policy=checkpoint.run_policy,
    ):
        states = _file_states_for_rows(checkpoint, page)
        point_ids_by_path: dict[str, list[str]] = {}
        for row in page:
            state = states.get(row.source_path)
            if (
                state is None
                or state.kind is not destination_kind
                or not state.converged
            ):
                continue
            point_ids_by_path.setdefault(row.source_path, []).append(row.point_id)
        for rel_path, point_ids in point_ids_by_path.items():
            if rel_path not in destination_evidence:
                destination_evidence[rel_path] = _destination_evidence_is_current(
                    store,
                    checkpoint.ledger,
                    destination_generation_id=checkpoint.generation_id,
                    destination_kind=destination_kind,
                    rel_path=rel_path,
                    run_policy=checkpoint.run_policy,
                )
            if not destination_evidence[rel_path]:
                continue
            checkpoint.run_policy.checkpoint("route page before journal")
            migration = journal.begin(
                rel_path=rel_path,
                origin_kind=origin_kind,
                destination_kind=destination_kind,
                destination_generation_id=checkpoint.generation_id,
                point_ids=tuple(point_ids),
            )
            checkpoint.run_policy.checkpoint("route page before origin delete")
            _delete_origin_points(store, migration)
            journal.mark_origin_deleted(migration.migration_id)
            removed += len(migration.point_ids)
            checkpoint.run_policy.checkpoint("route page after origin delete")
    return removed


def prior_stored_owners(root_dir: Path, rel_path: str) -> frozenset[ContentKind]:
    """Return prior per-kind ownership for a path that may no longer exist."""
    from ..config import get_config

    ledger_path = index_run_ledger_path(root_dir.resolve() / get_config().data_dir)
    if not ledger_path.is_file():
        return frozenset()
    ledger = RunLedger(ledger_path)
    owners: set[ContentKind] = set()
    for kind, collection in (
        (ContentKind.CODE, store_schema.CODE_COLLECTION),
        (ContentKind.DOCUMENT, store_schema.DOCUMENT_COLLECTION),
    ):
        state = ledger.latest_file_state(
            kind,
            collection_identity=collection,
            rel_path=rel_path,
        )
        if state is not None and state.kind is kind:
            owners.add(kind)
    return frozenset(owners)


def purge_unpublished_rows(
    store: VaultStore,
    checkpoint: DestinationCheckpoint,
    policy: ResolvedIndexPolicy,
    stored_kind: ContentKind,
    *,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> int:
    """Remove stale same-kind or rejected rows through bounded store pages."""
    removed = 0
    for page in iter_stored_route_pages(
        store,
        policy,
        stored_kind,
        page_size=page_size,
        run_policy=checkpoint.run_policy,
    ):
        states = _file_states_for_rows(checkpoint, page)
        retained_ids = _retained_ids_for_rows(checkpoint, page)
        stale_ids = [
            row.point_id
            for row in page
            if not _stored_row_is_retained(
                row,
                stored_kind=stored_kind,
                state=states.get(row.source_path),
                retained_ids=retained_ids,
            )
        ]
        if not stale_ids:
            continue
        checkpoint.run_policy.checkpoint("route purge before stale delete")
        _delete_kind_points(store, stored_kind, stale_ids)
        removed += len(stale_ids)
        checkpoint.run_policy.checkpoint("route purge after stale delete")
    return removed


def reconcile_generation_storage(
    store: VaultStore,
    checkpoint: DestinationCheckpoint,
    policy: ResolvedIndexPolicy,
    destination_kind: ContentKind,
) -> tuple[int, int, int]:
    """Converge replay, same-kind storage, and cross-kind ownership in order."""
    resumed = resume_pending_migrations(
        store,
        checkpoint.ledger.path.parent,
        run_policy=checkpoint.run_policy,
    )
    purged = purge_unpublished_rows(
        store,
        checkpoint,
        policy,
        destination_kind,
    )
    migrated = reconcile_checkpoint_routes(
        store,
        checkpoint,
        policy,
        destination_kind,
    )
    return resumed, purged, migrated


def resume_pending_migrations(
    store: VaultStore,
    data_root: Path,
    *,
    run_policy: RunPolicy | None = None,
) -> int:
    """Replay every destination-confirmed cleanup after interruption."""
    journal_path = data_root.resolve() / _MIGRATION_JOURNAL_FILENAME
    if not journal_path.is_file():
        return 0
    journal = RouteMigrationJournal(journal_path)
    ledger_path = index_run_ledger_path(data_root.resolve())
    if not ledger_path.is_file():
        return 0
    ledger = RunLedger(ledger_path)
    destination_evidence: dict[tuple[str, ContentKind, str], bool] = {}
    completed = 0
    for migration in journal.pending():
        if run_policy is not None:
            run_policy.checkpoint("route migration replay before origin delete")
        evidence_key = (
            migration.destination_generation_id,
            migration.destination_kind,
            migration.rel_path,
        )
        if evidence_key not in destination_evidence:
            destination_evidence[evidence_key] = _destination_evidence_is_current(
                store,
                ledger,
                destination_generation_id=migration.destination_generation_id,
                destination_kind=migration.destination_kind,
                rel_path=migration.rel_path,
                run_policy=run_policy,
            )
        if not destination_evidence[evidence_key]:
            continue
        _delete_origin_points(store, migration)
        journal.mark_origin_deleted(migration.migration_id)
        completed += 1
        if run_policy is not None:
            run_policy.checkpoint("route migration replay after origin delete")
    return completed


def _file_states_for_rows(
    checkpoint: DestinationCheckpoint,
    rows: tuple[StoredRouteRow, ...],
) -> dict[str, FileState]:
    """Read one store page through bounded indexed ledger lookups."""
    rel_paths = tuple(dict.fromkeys(row.source_path for row in rows))
    states: dict[str, FileState] = {}
    for start in range(0, len(rel_paths), _LEDGER_LOOKUP_BATCH):
        checkpoint.run_policy.checkpoint("route page before ledger lookup")
        batch = rel_paths[start : start + _LEDGER_LOOKUP_BATCH]
        states.update(
            checkpoint.ledger.file_states_for_paths(
                checkpoint.generation_id,
                batch,
            )
        )
        checkpoint.run_policy.checkpoint("route page after ledger lookup")
    return states


def _retained_ids_for_rows(
    checkpoint: DestinationCheckpoint,
    rows: tuple[StoredRouteRow, ...],
) -> frozenset[str]:
    """Read retained IDs through bounded indexed ledger lookups."""
    point_ids = tuple(dict.fromkeys(row.point_id for row in rows))
    retained: set[str] = set()
    for start in range(0, len(point_ids), _LEDGER_LOOKUP_BATCH):
        checkpoint.run_policy.checkpoint("route page before retained-ID lookup")
        batch = point_ids[start : start + _LEDGER_LOOKUP_BATCH]
        retained.update(
            checkpoint.ledger.retained_point_ids_for_candidates(
                checkpoint.generation_id,
                batch,
            )
        )
        checkpoint.run_policy.checkpoint("route page after retained-ID lookup")
    return frozenset(retained)


def _delete_origin_points(store: VaultStore, migration: RouteMigration) -> None:
    _delete_kind_points(store, migration.origin_kind, list(migration.point_ids))


def _delete_kind_points(
    store: VaultStore,
    kind: ContentKind,
    point_ids: list[str],
) -> None:
    if kind is ContentKind.CODE:
        store.delete_code_chunks(point_ids)
    else:
        store.delete_document_content_chunks(point_ids)


def _stored_row_is_retained(
    row: StoredRouteRow,
    *,
    stored_kind: ContentKind,
    state: FileState | None,
    retained_ids: frozenset[str],
) -> bool:
    if row.admitted and row.current_kind is not stored_kind:
        return True
    if not row.admitted or row.current_kind is not stored_kind:
        return False
    if state is None:
        return False
    if not state.converged:
        return True
    return row.point_id in retained_ids


def _resume_path_migrations(
    store: VaultStore,
    journal: RouteMigrationJournal,
    *,
    rel_path: str,
    origin_kind: ContentKind,
    destination_kind: ContentKind,
    destination_generation_id: str,
) -> int:
    removed = 0
    for migration in journal.pending():
        if (
            migration.rel_path != rel_path
            or migration.origin_kind is not origin_kind
            or migration.destination_kind is not destination_kind
            or migration.destination_generation_id != destination_generation_id
        ):
            continue
        _delete_origin_points(store, migration)
        journal.mark_origin_deleted(migration.migration_id)
        removed += len(migration.point_ids)
    return removed


def _destination_evidence_is_current(
    store: VaultStore,
    ledger: RunLedger,
    *,
    destination_generation_id: str,
    destination_kind: ContentKind,
    rel_path: str,
    run_policy: RunPolicy | None,
) -> bool:
    """Require the exact checkpointed destination points before origin cleanup."""
    try:
        generation = ledger.generation(destination_generation_id)
    except KeyError:
        return False
    expected_collection = (
        store_schema.CODE_COLLECTION
        if destination_kind is ContentKind.CODE
        else store_schema.DOCUMENT_COLLECTION
    )
    if (
        generation.signature.source_type is not destination_kind
        or generation.signature.collection_identity != expected_collection
        or not ledger.file_complete(
            destination_generation_id,
            rel_path,
        )
    ):
        return False
    point_ids = ledger.iter_retained_point_ids(
        destination_generation_id,
        rel_path=rel_path,
    )
    found_any = False
    while batch := tuple(itertools.islice(point_ids, _DEFAULT_PAGE_SIZE)):
        found_any = True
        if run_policy is not None:
            run_policy.checkpoint("route destination evidence before retrieve")
        if destination_kind is ContentKind.CODE:
            if not store.code_content_ids_exist(batch):
                return False
        elif not store.document_content_ids_exist(batch):
            return False
        if run_policy is not None:
            run_policy.checkpoint("route destination evidence after retrieve")
    return found_any


def _migration_id(
    rel_path: str,
    origin_kind: ContentKind,
    destination_kind: ContentKind,
    destination_generation_id: str,
    point_ids: tuple[str, ...],
) -> str:
    payload = json.dumps(
        (
            rel_path,
            origin_kind.value,
            destination_kind.value,
            destination_generation_id,
            tuple(sorted(point_ids)),
        ),
        separators=(",", ":"),
    )
    return hashlib.blake2b(payload.encode("utf-8")).hexdigest()


def _migration_from_row(row: sqlite3.Row) -> RouteMigration:
    raw_ids = json.loads(str(row["point_ids_json"]))
    if not isinstance(raw_ids, list):
        raise ValueError("route migration point IDs are invalid")
    point_ids = cast("list[object]", raw_ids)
    if not all(isinstance(point_id, str) and point_id for point_id in point_ids):
        raise ValueError("route migration point IDs are invalid")
    return RouteMigration(
        migration_id=str(row["migration_id"]),
        rel_path=str(row["rel_path"]),
        origin_kind=ContentKind(str(row["origin_kind"])),
        destination_kind=ContentKind(str(row["destination_kind"])),
        destination_generation_id=str(row["destination_generation_id"]),
        point_ids=tuple(cast("str", point_id) for point_id in point_ids),
        phase=RouteMigrationPhase(str(row["phase"])),
    )
