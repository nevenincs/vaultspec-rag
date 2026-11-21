"""Admission refuses an incremental run its published proof cannot parent.

Real run ledgers, real publication proofs opened through production
checkpoint code, real policy resolution and a real job manager; no doubles.

MUTATION PROOF, each run in one uninterrupted sequence:

- Deleting the ``refuse_incompatible_incremental`` call from
  ``index_job_spec`` fails
  ``test_an_edited_declared_input_refuses_before_a_job_exists`` on its
  ``pytest.raises`` and ``test_watcher_refusal_creates_no_job`` on its
  refused-state assertion.
- Deleting the same call also fails
  ``test_drift_repair_refused_at_admission_reports_rebuild_required`` on its
  status assertion: the repair job is created instead.
- Comparing only the chunking identity in the preflight fails
  ``test_preflight_refuses_exactly_where_checkpoint_open_refuses`` on the
  admission-side ``pytest.raises`` while checkpoint open still refuses.

Restoring each returns the module to green.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from .. import jobs as _jobs
from .._job_admission import (
    IncompatibleIncrementalError,
    admit_index_job,
    index_job_spec,
)
from .._job_errors import JobErrorKind
from .._source_types import PublicSourceType
from ..indexer._run_ledger_models import (
    RunAuthority,
    RunLedgerCompatibilityError,
    RunOperation,
)
from ..job_models import JobMode, JobSource
from ..registry import get_registry
from ..service import ServiceRegistry
from ..watcher_controller import (
    ControllerReason,
    ControllerSnapshot,
    ControllerState,
    WatcherController,
)
from ..watcher_execution import controller_scope_from_retry_state, submit_watcher_job
from ..watcher_retry import (
    WatcherPathEvent,
    WatcherPathObservation,
    WatcherScopeRefusal,
    WatcherSource,
)
from ..watcher_retry_policy import WatcherRetryPolicy
from ..watcher_runtime import WatcherConvergenceSlot
from ._hook_publication import (
    edit_hook_script,
    open_document_generation,
    publish_empty_document_proof,
    publish_one_document,
    write_hook_root,
)
from ._state_fixtures import reset_registry

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def isolated_registry() -> Generator[ServiceRegistry]:
    """Build and discard the process-wide registry around one admission."""
    reset_registry()
    registry = get_registry()
    try:
        yield registry
    finally:
        reset_registry()


@pytest.fixture
def published_hook_root(tmp_path: Path, isolated_registry: ServiceRegistry) -> Path:
    """A hook root whose document source holds a committed proof."""
    del isolated_registry
    root = write_hook_root((tmp_path / "project").resolve())
    publish_empty_document_proof(root)
    return root


def _incremental(root: Path, *, initiator_kind: str = "cli") -> None:
    index_job_spec(
        root,
        source=JobSource.DOCUMENT,
        clean=False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind=initiator_kind,
    )


def test_an_unchanged_policy_admits_the_incremental(published_hook_root: Path) -> None:
    spec = index_job_spec(
        published_hook_root,
        source=JobSource.DOCUMENT,
        clean=False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="cli",
    )
    assert spec.mode is JobMode.INCREMENTAL
    assert not spec.is_first_build


def test_an_edited_declared_input_refuses_before_a_job_exists(
    published_hook_root: Path,
) -> None:
    _jobs.reset()
    edit_hook_script(published_hook_root)

    with pytest.raises(IncompatibleIncrementalError) as caught:
        admit_index_job(
            published_hook_root,
            source=JobSource.DOCUMENT,
            clean=False,
            authority=RunAuthority.PUBLICATION,
            initiator_kind="cli",
        )

    refusal = caught.value
    assert refusal.error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert refusal.changed_identities == ("content_identity",)
    assert refusal.rebuild_command.endswith("index --rebuild --type document")
    assert str(published_hook_root) in refusal.rebuild_command
    assert refusal.rebuild_command in refusal.detail
    assert refusal.as_payload()["remediation"] == [refusal.rebuild_command]
    assert _jobs.get_job_manager().list_jobs() == []


@pytest.mark.parametrize("initiator_kind", ["cli", "watcher", "integrity"])
def test_every_origin_is_refused_and_none_escalates(
    published_hook_root: Path, initiator_kind: str
) -> None:
    edit_hook_script(published_hook_root)
    with pytest.raises(IncompatibleIncrementalError):
        _incremental(published_hook_root, initiator_kind=initiator_kind)


def test_an_explicit_rebuild_is_never_refused(published_hook_root: Path) -> None:
    edit_hook_script(published_hook_root)
    spec = index_job_spec(
        published_hook_root,
        source=JobSource.DOCUMENT,
        clean=True,
        authority=RunAuthority.REBUILD,
        initiator_kind="cli",
    )
    assert spec.mode is JobMode.REBUILD


def test_the_other_source_keeps_its_incremental(published_hook_root: Path) -> None:
    """A document hook edit leaves the code content identity untouched.

    The root has no code proof, so admission reads a never-built code source
    and admits it as the first build rather than refusing it.
    """
    edit_hook_script(published_hook_root)
    spec = index_job_spec(
        published_hook_root,
        source=JobSource.CODE,
        clean=False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="cli",
    )
    assert spec.is_first_build


def test_an_unresolvable_policy_admits_for_checkpoint_open_to_decide(
    published_hook_root: Path,
) -> None:
    (published_hook_root / "tools" / "extract.py").unlink()
    # The declared input is gone, so the policy cannot be resolved here. The
    # request is admitted unchanged; policy validation reports the defect.
    _incremental(published_hook_root)


def test_preflight_refuses_exactly_where_checkpoint_open_refuses(
    published_hook_root: Path,
) -> None:
    edit_hook_script(published_hook_root)
    with pytest.raises(IncompatibleIncrementalError):
        _incremental(published_hook_root)
    with pytest.raises(RunLedgerCompatibilityError):
        open_document_generation(
            published_hook_root,
            operation=RunOperation.INCREMENTAL,
            authority=RunAuthority.PUBLICATION,
        )

    (published_hook_root / "tools" / "extract.py").write_text(
        "print('v1')\n", encoding="utf-8"
    )
    _incremental(published_hook_root)
    checkpoint = open_document_generation(
        published_hook_root,
        operation=RunOperation.INCREMENTAL,
        authority=RunAuthority.PUBLICATION,
    )
    assert checkpoint.generation.parent_generation_id is not None


def _document_binding(
    root: Path, registry: ServiceRegistry
) -> tuple[WatcherConvergenceSlot, WatcherController, WatcherRetryPolicy]:
    pdf = root / "docs" / "a.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\n")
    policy = WatcherRetryPolicy.for_root(root, WatcherSource.DOCUMENT)
    policy.mark_scope_pending(
        (
            WatcherPathObservation(
                relative_path="docs/a.pdf",
                source=WatcherSource.DOCUMENT,
                first_observed_at=time.time(),
                latest_observed_at=time.time(),
                event_kinds=frozenset({WatcherPathEvent.MODIFIED}),
                generation=1,
            ),
        ),
        now=time.time(),
    )
    controller = WatcherController(
        ControllerSnapshot(
            canonical_root=str(root),
            source=WatcherSource.DOCUMENT,
            state=ControllerState.READY,
            reason=ControllerReason.QUIET_TREE_DEADLINE,
            scope=controller_scope_from_retry_state(policy.state),
            observed_at=time.time(),
            monotonic_at=time.monotonic(),
            next_decision_at=time.monotonic(),
            freshness_deadline=time.monotonic() + 300.0,
        ),
        monotonic=time.monotonic,
        wall_clock=time.time,
    )
    slot = WatcherConvergenceSlot(JobSource.DOCUMENT, root, registry, policy)
    return slot, controller, policy


async def test_watcher_refusal_creates_no_job(
    published_hook_root: Path, isolated_registry: ServiceRegistry
) -> None:
    _jobs.reset()
    slot, controller, policy = _document_binding(published_hook_root, isolated_registry)
    edit_hook_script(published_hook_root)

    await submit_watcher_job(
        slot,
        controller=controller,
        now=time.monotonic(),
        secondary_graph_cache=None,
    )

    snapshot = controller.snapshot
    assert snapshot.state is ControllerState.REFUSED
    assert snapshot.reason is ControllerReason.FULL_REINDEX_REQUIRED
    assert snapshot.remediation is not None
    assert snapshot.remediation.endswith("index --rebuild --type document")
    assert policy.state.scope_refusal is WatcherScopeRefusal.FULL_REINDEX_REQUIRED
    # The captured path is back in pending scope for the rebuild to cover.
    assert [item.relative_path for item in policy.state.pending_paths] == ["docs/a.pdf"]
    assert slot.job_id is None
    assert _jobs.get_job_manager().list_jobs() == []
    assert not policy.admit(now=time.time() + 1000.0).admitted


def test_a_never_built_document_source_is_still_a_first_build(
    tmp_path: Path, isolated_registry: ServiceRegistry
) -> None:
    del isolated_registry
    root = write_hook_root((tmp_path / "fresh").resolve())
    spec = index_job_spec(
        root,
        source=JobSource.DOCUMENT,
        clean=False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="cli",
    )
    assert spec.is_first_build
    assert PublicSourceType(spec.source.value) is PublicSourceType.DOCUMENT


def test_drift_repair_refused_at_admission_reports_rebuild_required(
    tmp_path: Path,
) -> None:
    from .._search_drift import SearchDriftAuditor
    from .._search_freshness import DriftedFile
    from ..config._types import EnvVar
    from ..store_runtime import VaultStore
    from .conftest import managed_env

    root = write_hook_root((tmp_path / "project").resolve())
    pdf = root / "docs" / "a.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4\n")
    with managed_env(
        **{
            EnvVar.QDRANT_URL.value: None,
            EnvVar.LOCAL_ONLY.value: "1",
            EnvVar.EMBEDDING_DIMENSION.value: "4",
            EnvVar.INDEX_SUPPORT_PROFILE.value: "embedded-local",
        }
    ):
        with VaultStore(root) as store:
            publish_one_document(root, "docs/a.pdf", store)
        edit_hook_script(root)
        registry = ServiceRegistry()
        auditor = SearchDriftAuditor()
        diagnostics: list[dict[str, object]] = []
        try:
            auditor.note_served(
                root,
                (DriftedFile("document", "docs/a.pdf", "content_changed"),),
                registry,
            )
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                diagnostics = auditor.snapshot(root, registry, port=9876)
                if diagnostics and diagnostics[0]["status"] != "pending":
                    break
                time.sleep(0.05)
            created = registry.create_job_manager().list_jobs()
        finally:
            auditor.close()
            registry.close_all()
    _jobs.reset()

    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic["status"] == "rebuild_required", diagnostic
    assert diagnostic["repair_job_id"] is None
    assert created == []
    # The admission refusal names the stale identity, which a refused
    # checkpoint open or an audit verdict never does.
    assert "content_identity" in str(diagnostic["reason"]), diagnostic
    assert "--rebuild --type document --port 9876" in str(diagnostic["remediation"])
