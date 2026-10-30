"""Coalesce served stale-hit reports into background diagnosis and index jobs."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from ._job_errors import JobError, JobErrorKind
from ._operator_commands import IndexCommandOptions, index_command
from ._search_freshness import DriftedFile, capture_hit_publications, verify_search_hits
from ._source_types import INDEX_SOURCES, IndexSource, PublicSourceType
from .indexer._run_ledger_models import RunAuthority
from .search._models import DocumentSearchResult, SearchResult

if TYPE_CHECKING:
    from pathlib import Path

    from .service import ServiceRegistry

logger = logging.getLogger(__name__)
MAX_AUDITS = 128
AUDIT_INTERVAL_SECONDS = 600.0
_RESULT_SOURCES: dict[str, IndexSource] = {
    "codebase": "code",
    "vault": "vault",
    "document": "document",
}


def served_stale_files(response: dict[str, object]) -> tuple[DriftedFile, ...]:
    """Recover only confirmed, actually delivered file locators for auditing."""
    rows = response.get("results")
    if not isinstance(rows, list):
        return ()
    files: dict[tuple[IndexSource, str], DriftedFile] = {}
    for raw in cast("list[object]", rows):
        if not isinstance(raw, dict):
            continue
        row = cast("dict[str, object]", raw)
        if row.get("freshness") != "stale":
            continue
        raw_source = row.get("source")
        source = (
            _RESULT_SOURCES.get(raw_source) if isinstance(raw_source, str) else None
        )
        path = row.get("source_path") or row.get("path")
        if source is None or not isinstance(path, str):
            continue
        files[source, path] = DriftedFile(
            source, path, str(row.get("stale_reason") or "content_changed")
        )
    return tuple(files.values())


@dataclass(frozen=True, slots=True)
class _Audit:
    root: Path
    source: IndexSource
    files: tuple[DriftedFile, ...]
    requested_at: float
    status: str = "pending"
    reason: str | None = None
    job_id: str | None = None
    details: dict[str, object] | None = None


def _recheck(audit: _Audit) -> tuple[DriftedFile, ...]:
    results: list[SearchResult | DocumentSearchResult] = []
    for file in audit.files:
        result: SearchResult | DocumentSearchResult
        if file.source == "document":
            result = DocumentSearchResult("", file.path, "", 0.0, "")
        else:
            result = SearchResult(
                "",
                file.path,
                "",
                0.0,
                "",
                "codebase" if file.source == "code" else "vault",
            )
        results.append(result)
    return verify_search_hits(
        audit.root, results, capture_hit_publications(audit.root, (audit.source,))
    )


def _diagnose(
    audit: _Audit,
    registry: ServiceRegistry,
    closing: threading.Event | None = None,
) -> _Audit:
    from ._index_integrity import AuditVerdict, audit_index_sources
    from .jobs import (
        start_reindex_codebase,
        start_reindex_documents,
        start_reindex_vault,
    )

    source = PublicSourceType(audit.source)
    outcome = audit_index_sources(
        audit.root,
        source,
        RunAuthority.AUDIT_VERIFICATION,
        lambda: registry.lease_store(audit.root),
    )
    status = outcome["status"]
    domains = outcome.get("domains")
    domain = (
        cast("dict[str, object]", domains).get(audit.source)
        if isinstance(domains, dict)
        else None
    )
    details = cast("dict[str, object]", domain) if isinstance(domain, dict) else {}
    audit = replace(audit, details=details)
    if status == AuditVerdict.DRIFT or (
        status == AuditVerdict.REBUILD_REQUIRED
        and details.get("error_kind")
        in {
            "incompatible",
            "corrupt_receipt",
            "unexplained_drift",
            "RunLedgerCompatibilityError",
            "RunLedgerCorruptionError",
        }
    ):
        return replace(
            audit,
            status="rebuild_required",
            reason=str(details.get("message") or details.get("error_kind") or status),
        )
    if status != AuditVerdict.CONSISTENT:
        return replace(audit, status="deferred", reason=str(status))
    if not _recheck(audit):
        return replace(audit, status="resolved_or_unverifiable")
    starters = {
        "code": start_reindex_codebase,
        "vault": start_reindex_vault,
        "document": start_reindex_documents,
    }
    if closing is not None and closing.is_set():
        return replace(audit, status="deferred", reason="service_stopping")
    job_id = starters[audit.source](
        audit.root,
        False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="integrity",
        registry=registry,
    )
    return replace(audit, status="incremental_requested", job_id=job_id)


class SearchDriftAuditor:
    """One bounded, single-worker audit queue owned by an HTTP runtime.

    The queue contains only file locators, never candidate content or vectors.
    Durable repair execution and retry authority remain with the job manager.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._audits: dict[tuple[Path, IndexSource], _Audit] = {}
        self._pending: deque[tuple[_Audit, ServiceRegistry]] = deque()
        self._running = False
        self._closing = threading.Event()

    def close(self) -> None:
        """Discard queued audits and prevent a finishing audit from admitting work."""
        self._closing.set()
        with self._lock:
            self._pending.clear()

    def _reserve(
        self,
        root: Path,
        files: tuple[DriftedFile, ...],
        now: float,
    ) -> _Audit | None:
        source = files[0].source
        key = (root, source)
        previous = self._audits.get(key)
        if previous is not None and (
            previous.status == "pending"
            or now - previous.requested_at < AUDIT_INTERVAL_SECONDS
        ):
            return None
        if len(self._audits) >= MAX_AUDITS and key not in self._audits:
            candidates = [
                key for key, item in self._audits.items() if item.status != "pending"
            ]
            if not candidates:
                return None
            del self._audits[candidates[0]]
        audit = _Audit(root, source, files, now)
        self._audits[key] = audit
        return audit

    def note_served(
        self, root: Path, files: tuple[DriftedFile, ...], registry: ServiceRegistry
    ) -> None:
        """Record confirmed stale delivery after the response has been sent."""
        now = time.monotonic()
        with self._lock:
            if self._closing.is_set():
                return
            for source in INDEX_SOURCES:
                selected = tuple(file for file in files if file.source == source)
                if not selected:
                    continue
                audit = self._reserve(root, selected, now)
                if audit is not None:
                    self._pending.append((audit, registry))
            if not self._pending or self._running:
                return
            self._running = True
            threading.Thread(
                target=self._drain, name="search-drift-audit", daemon=True
            ).start()

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._running = False
                    return
                audit, registry = self._pending.popleft()
            try:
                diagnosed = _diagnose(audit, registry, self._closing)
            except JobError as exc:
                diagnosed = replace(
                    audit,
                    status=(
                        "rebuild_required"
                        if exc.error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
                        else "deferred"
                    ),
                    reason=str(exc),
                )
            except Exception:
                logger.warning(
                    "stale-hit audit failed for %s/%s",
                    audit.root,
                    audit.source,
                    exc_info=True,
                )
                diagnosed = replace(
                    audit, status="deferred", reason="audit_unavailable"
                )
            with self._lock:
                key = (audit.root, audit.source)
                if self._audits.get(key) is audit:
                    self._audits[key] = diagnosed

    def _retire(self, audit: _Audit) -> None:
        with self._lock:
            key = (audit.root, audit.source)
            if self._audits.get(key) is audit:
                del self._audits[key]

    def snapshot(
        self,
        root: Path,
        registry: ServiceRegistry,
        delivered: dict[str, object] | None = None,
        port: int | None = None,
    ) -> list[dict[str, object]]:
        """Project diagnoses and the canonical repair job's typed blockers."""
        with self._lock:
            audits = [
                audit for (path, _), audit in self._audits.items() if path == root
            ]
        result: list[dict[str, object]] = []
        current = _current_files(delivered or {})
        for audit in audits:
            if all((audit.source, file.path) in current for file in audit.files):
                self._retire(audit)
                continue
            result.append(_project_audit(audit, registry, port))
        diagnosed_sources = {item["source"] for item in result}
        pending: dict[IndexSource, list[str]] = {}
        for file in served_stale_files(delivered or {}):
            pending.setdefault(file.source, []).append(file.path)
        for source, paths in pending.items():
            if source not in diagnosed_sources:
                result.append(
                    {
                        "source": source,
                        "status": "pending",
                        "paths": paths,
                    }
                )
        return result


def _project_audit(
    audit: _Audit,
    registry: ServiceRegistry,
    port: int | None,
) -> dict[str, object]:
    status, reason = audit.status, audit.reason
    if audit.job_id is not None:
        job = registry.create_job_manager().get(audit.job_id)
        if job is not None and job.error_kind == JobErrorKind.FULL_REINDEX_REQUIRED:
            status, reason = "rebuild_required", job.result
    item: dict[str, object] = {
        "source": audit.source,
        "status": status,
        "reason": reason,
        "repair_job_id": audit.job_id,
        "paths": [file.path for file in audit.files],
        "drift_reasons": {file.path: file.reason for file in audit.files},
        "audit": audit.details,
    }
    if status == "rebuild_required":
        item["remediation"] = index_command(
            PublicSourceType(audit.source),
            IndexCommandOptions(target=str(audit.root), rebuild=True, port=port),
        )
    return item


def _current_files(response: dict[str, object]) -> set[tuple[IndexSource, str]]:
    rows = response.get("results")
    if not isinstance(rows, list):
        return set()
    return {
        (
            cast(
                "IndexSource",
                "code" if row.get("source") == "codebase" else row.get("source"),
            ),
            str(row.get("source_path") or row.get("path")),
        )
        for row in cast("list[dict[str, object]]", rows)
        if row.get("freshness") == "current"
    }
