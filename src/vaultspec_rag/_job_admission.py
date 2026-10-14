"""Admitting an index job, and the policy checks it has to clear first.

Whether the root's content policy is valid, whether this host meets the
selected profile, and whether the corpus fits it. A refusal here names the
missing resource or the offending route rather than the job, because that is
what an operator can act on.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Final

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

    from ._source_types import PublicSourceType
    from .index_profiles import SupportMeasurement
    from .indexer._codebase_indexer import (
        CodeIndexPreflight,
        CodeScopedPreflight,
    )
    from .indexer._document_indexer import (
        DocumentIndexPreflight,
        DocumentScopedPreflight,
    )
    from .indexer._run_ledger_models import RunAuthority
    from .job_control import RunControl
    from .job_manager.manager import JobManager

logger = logging.getLogger("vaultspec_rag.jobs")

#: Index origins that are never escalated to a first build. Automatic
#: convergence work converges the scope it was handed and reports a refusal
#: rather than spending a full corpus build nobody asked for. The watcher
#: builds its own specification and never reaches this module at all; naming
#: it here keeps the invariant true for any adapter that does, including the
#: HTTP routes, where the initiator is client-supplied text.
AUTOMATIC_INDEX_ORIGINS: Final = frozenset({"watcher", "integrity"})


class SourcePublication(StrEnum):
    """What the run ledger says about one source's completed publications."""

    #: A completed publication exists for this root, backend, and source.
    PUBLISHED = "published"
    #: No publication was ever completed for it.
    ABSENT = "absent"
    #: Publication state exists but cannot be read as this source's own:
    #: another backend's proof, an incompatible or corrupt ledger, or a
    #: receipt a run is holding open right now.
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class SourceAdmissionReading:
    """The two readings that decide whether a source has ever been built.

    ``stored_points`` is ``None`` when storage could not be counted at all,
    which is an absence of reading rather than a reading of zero.
    """

    publication: SourcePublication
    stored_points: int | None


def is_new_source(reading: SourceAdmissionReading) -> bool:
    """Return whether *reading* proves one source has never been built.

    Both readings have to agree. Stored points with no completed publication
    are exactly what the typed rebuild refusal exists for: something is in
    that collection and no evidence says what. Publication state that cannot
    be read is not absence either, so neither is an unreadable count.
    """
    return (
        reading.publication is SourcePublication.ABSENT and reading.stored_points == 0
    )


def read_source_admission(
    root: Path,
    source: PublicSourceType,
) -> SourceAdmissionReading:
    """Take both never-built readings for one concrete source at admission."""
    return SourceAdmissionReading(
        publication=_read_source_publication(root, source),
        stored_points=_count_stored_points(root, source),
    )


def _read_source_publication(
    root: Path,
    source: PublicSourceType,
) -> SourcePublication:
    """Classify the committed publication authority for one source."""
    from ._publication_state import acquire_publication_snapshot
    from .indexer._publication_proof import (
        ProofMissingError,
        ProofReadConflictError,
        ProofUnverifiableError,
    )
    from .indexer._run_ledger_models import RunLedgerError

    try:
        acquire_publication_snapshot(root, source).validate()
    except ProofMissingError:
        return SourcePublication.ABSENT
    except (ProofUnverifiableError, ProofReadConflictError, RunLedgerError):
        return SourcePublication.UNREADABLE
    return SourcePublication.PUBLISHED


def _count_stored_points(root: Path, source: PublicSourceType) -> int | None:
    """Count one source's stored points, or report that it cannot be read.

    The store lease takes the lifecycle lock and the count takes that one
    collection's lock, in that order. Any failure to reach storage is
    reported as no reading: escalating on a count nobody could take would
    reset a target whose contents are unknown.
    """
    from .registry import get_registry

    try:
        with get_registry().lease_store(root) as store:
            return store.count_source(source)
    except Exception:  # any unreachable backend is an absence of reading
        logger.warning(
            "could not count stored %s points for %s; "
            "treating the source as already built",
            source.value,
            root,
            exc_info=True,
        )
        return None


def index_job_spec(
    root: Path,
    *,
    source: JobSource,
    clean: bool,
    authority: RunAuthority,
    initiator_kind: str,
) -> JobSpec:
    """Return the specification admission creates for one index request.

    An explicit incremental request for a source that has never been built is
    admitted as that source's first full build. There is no publication for
    the incremental path to reconcile against, so it can only refuse; the
    first build runs the same reset-first lifecycle a rebuild runs, with
    nothing to discard. The requested mode is retained on the specification so
    the job record reports what was asked for next to what runs. Anything
    short of never-built keeps the typed refusal, and automatic origins are
    never escalated.
    """
    from .indexer._run_ledger_models import RunAuthority as _RunAuthority

    requested = JobMode.REBUILD if clean else JobMode.INCREMENTAL
    spec = JobSpec(
        operation=JobOperation.INDEX,
        source=source,
        project_root=str(root),
        mode=requested,
        authority=authority,
    )
    if (
        requested is JobMode.REBUILD
        or not source.is_corpus
        or initiator_kind in AUTOMATIC_INDEX_ORIGINS
    ):
        return spec
    from ._source_types import PublicSourceType as _Source

    if not is_new_source(read_source_admission(root, _Source(source.value))):
        return spec
    logger.info(
        "admitting the first %s index of %s as a full build", source.value, root
    )
    return replace(
        spec,
        mode=JobMode.REBUILD,
        authority=_RunAuthority.REBUILD,
        requested_mode=requested,
    )


def admit_index_job(
    root: Path,
    *,
    source: JobSource,
    clean: bool,
    authority: RunAuthority,
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
        index_job_spec(
            resolved_root,
            source=source,
            clean=clean,
            authority=authority,
            initiator_kind=initiator_kind,
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
