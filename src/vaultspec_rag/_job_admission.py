"""Admitting an index job, and the policy checks it has to clear first.

Whether the root's content policy is valid, whether this host meets the
selected profile, and whether the corpus fits it. A refusal here names the
missing resource or the offending route rather than the job, because that is
what an operator can act on.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING

from ._job_progress import record_progress
from .job_control import NO_RUN_CONTROL
from .job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobOutcomeStatus,
    JobSource,
    JobSpec,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .index_profiles import SupportMeasurement
    from .indexer._codebase_indexer import (
        CodeIndexPreflight,
        CodeScopedPreflight,
        ContentScanResult,
    )
    from .indexer._document_indexer import (
        DocumentIndexPreflight,
        DocumentScopedPreflight,
    )
    from .job_control import RunControl
    from .job_manager.manager import JobManager


def admit_index_job(
    root: Path,
    *,
    source: JobSource,
    clean: bool,
    initiator_kind: str,
) -> tuple[JobManager, str, bool]:
    # Imported inside the call rather than at module scope: the registry
    # surface imports this module to admit a job, so naming it at import time
    # would close a cycle. The call happens long after both modules are built.
    from .jobs import get_job_manager, record_start

    manager = get_job_manager()
    resolved_root = root.resolve()
    commands = {
        JobSource.VAULT: "reindex_vault",
        JobSource.CODE: "reindex_codebase",
        JobSource.DOCUMENT: "reindex_documents",
    }
    command = commands[source]
    requested_id = uuid.uuid4().hex
    outcome = manager.create(
        JobSpec(
            operation=JobOperation.INDEX,
            source=source,
            project_root=str(resolved_root),
            mode=JobMode.REBUILD if clean else JobMode.INCREMENTAL,
        ),
        JobInitiator(
            kind=initiator_kind,
            command=command,
            project_root=str(resolved_root),
        ),
        job_id=requested_id,
    )
    if outcome.status is JobOutcomeStatus.ERROR or outcome.job is None:
        raise RuntimeError(outcome.message)
    job_id = outcome.job.id
    created = outcome.code == "job_created"
    if created:
        record_start(
            source,
            "tool",
            project_root=resolved_root,
            command=command,
            initiator_kind=initiator_kind,
            _record_id=job_id,
        )
        record_progress(job_id, "queued")
    return manager, job_id, created


def validate_scoped_code_index_policy(
    root: Path,
    changed_paths: tuple[Path, ...] | frozenset[Path],
) -> CodeScopedPreflight:
    """Validate one exact scoped path set without a full-tree discovery."""
    from .indexer._content_discovery import CodeContentDiscovery

    return CodeContentDiscovery(root.resolve()).preflight_changed_paths(changed_paths)


def validate_code_index_policy(root: Path) -> CodeIndexPreflight:
    """Resolve and discover code work before a job mutates durable state."""
    from .indexer._content_discovery import CodeContentDiscovery

    return CodeContentDiscovery(root.resolve()).preflight_content()


def validate_code_support_profile(
    root: Path,
    preflight: CodeIndexPreflight | CodeScopedPreflight,
) -> SupportMeasurement:
    """Enforce the named code profile before any model or mutable resource."""
    import psutil

    from ._store_writes import probe_store_volume, probe_workspace_volume
    from .config._settings import get_config
    from .index_profiles import (
        AdmissionEnvironment,
        IndexDomain,
        validate_profile_admission,
    )
    from .indexer._codebase_indexer import CodeIndexPreflight

    discovered = (
        preflight.scan.measurement
        if isinstance(preflight, CodeIndexPreflight)
        else preflight.measurement
    )
    cfg = get_config()
    measurement = replace(
        discovered,
        queue_bytes=int(cfg.index_queue_max_bytes),
        rss_bytes=int(psutil.Process(os.getpid()).memory_info().rss),
    )
    validate_profile_admission(
        cfg.index_support_profile,
        IndexDomain.CODE,
        measurement,
        AdmissionEnvironment(
            backend="server" if cfg.effective_server_mode() else "local",
            available_ram_bytes=int(psutil.virtual_memory().total),
            store_volume=probe_store_volume(root),
            workspace_volume=probe_workspace_volume(root),
        ),
    )
    return measurement


def validate_code_job_admission(root: Path) -> CodeIndexPreflight:
    """Return code authority only after policy and profile admission."""
    preflight = validate_code_index_policy(root)
    measurement = validate_code_support_profile(root, preflight)
    return replace(
        preflight,
        scan=replace(preflight.scan, measurement=measurement),
    )


def validate_document_index_policy(
    root: Path,
    *,
    run_control: RunControl = NO_RUN_CONTROL,
) -> DocumentIndexPreflight:
    """Resolve and discover document work before durable mutation."""
    from .indexer import DocumentIndexer

    return DocumentIndexer.for_preflight(root.resolve()).preflight_content(
        run_control=run_control
    )


def validate_scoped_document_index_policy(
    root: Path,
    changed_paths: tuple[Path, ...] | frozenset[Path],
    *,
    run_control: RunControl = NO_RUN_CONTROL,
) -> DocumentScopedPreflight:
    """Validate one exact document watcher scope without full discovery."""
    from .indexer import DocumentIndexer

    return DocumentIndexer.for_preflight(root.resolve()).preflight_changed_paths(
        changed_paths,
        run_control=run_control,
    )


def validate_document_support_profile(
    root: Path,
    preflight: DocumentIndexPreflight | DocumentScopedPreflight,
    *,
    run_control: RunControl = NO_RUN_CONTROL,
) -> None:
    """Enforce the named document profile before any model or mutable resource."""
    import psutil

    from ._store_writes import probe_store_volume, probe_workspace_volume
    from .config._settings import get_config
    from .index_profiles import (
        AdmissionEnvironment,
        IndexDomain,
        SupportMeasurement,
        validate_profile_admission,
    )
    from .indexer._document_indexer import DocumentIndexPreflight

    paths = (
        preflight.files
        if isinstance(preflight, DocumentIndexPreflight)
        else preflight.changed_paths
    )
    run_control.checkpoint()
    source_files = 0
    source_bytes = 0
    for path in paths:
        run_control.checkpoint()
        if path.is_file():
            source_files += 1
            source_bytes += path.stat().st_size
        run_control.checkpoint()
    run_control.checkpoint()
    cfg = get_config()
    measurement = SupportMeasurement(
        source_files=source_files,
        source_bytes=source_bytes,
        queue_bytes=int(cfg.index_queue_max_bytes),
        rss_bytes=int(psutil.Process(os.getpid()).memory_info().rss),
    )
    validate_profile_admission(
        cfg.index_support_profile,
        IndexDomain.DOCUMENT,
        measurement,
        AdmissionEnvironment(
            backend="server" if cfg.effective_server_mode() else "local",
            available_ram_bytes=int(psutil.virtual_memory().total),
            store_volume=probe_store_volume(root),
            workspace_volume=probe_workspace_volume(root),
        ),
    )


def validate_document_job_admission(
    root: Path,
    *,
    run_control: RunControl = NO_RUN_CONTROL,
) -> DocumentIndexPreflight:
    """Return document authority only after policy and profile admission."""
    preflight = validate_document_index_policy(root, run_control=run_control)
    validate_document_support_profile(root, preflight, run_control=run_control)
    return preflight


def scan_code_index_preflight(root: Path) -> ContentScanResult:
    """Return bounded admission from the production structured scanner."""
    return validate_code_index_policy(root).scan
