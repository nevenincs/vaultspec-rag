"""Bounded stale-hit diagnosis, incremental authority and adapter rendering."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from .. import store_schema
from .._job_errors import FULL_REINDEX_REQUIRED_PHRASE, JobErrorKind
from .._search_drift import SearchDriftAuditor, _Audit, _diagnose, served_stale_files
from .._search_freshness import (
    DriftedFile,
    capture_hit_publications,
    verify_search_hits,
)
from ..cli._search import _handle_service_results, _ServiceSearchRenderRequest
from ..config._types import EnvVar
from ..indexer._run_ledger_models import RunAuthority, RunOperation
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..indexer._vault_fingerprint import fingerprint_bytes
from ..indexer._vault_prep import prepare_document, split_document
from ..job_control import NO_RUN_CONTROL
from ..job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec
from ..mcp._tools import SearchResults
from ..search._models import SearchResult
from ..service import ServiceRegistry
from ..store_runtime import VaultStore
from ._search_readiness_scenarios import (
    SEARCH_READINESS_SCENARIOS,
    canonical_service_envelope,
)
from .conftest import managed_env
from .test_document_index_escalation import _seed_document_proof

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


def _audit(root: Path) -> _Audit:
    return _Audit(
        root, "code", (DriftedFile("code", "src/a.py", "content_changed"),), 0.0
    )


@pytest.fixture(params=[".vault", "knowledge"])
def published_vault(
    tmp_path: Path, request: pytest.FixtureRequest
) -> Iterator[tuple[_Audit, ServiceRegistry]]:
    root = tmp_path / "project"
    docs_dir = cast("str", request.param)
    path = root / docs_dir / "adr" / "stored.document.md"
    path.parent.mkdir(parents=True)
    data = (
        b"---\nmodified: '2026-01-01'\n---\n"
        b"# Stored document\n\nComplete parent body.\n"
    )
    path.write_bytes(data)
    with managed_env(
        **{
            EnvVar.QDRANT_URL.value: None,
            EnvVar.LOCAL_ONLY.value: "1",
            EnvVar.EMBEDDING_DIMENSION.value: "4",
            "VAULTSPEC_DOCS_DIR": docs_dir,
        }
    ):
        document = prepare_document(path, root)
        assert document is not None
        assert document.id == "adr/stored.document"
        chunks = split_document(document, 50)
        for chunk in chunks:
            chunk.vector = [0.1, 0.2, 0.3, 0.4]
        with VaultStore(root) as store:
            checkpoint = VaultRunCheckpoint.open(
                root,
                backend_identity=store.backend_identity,
                authority=RunAuthority.REBUILD,
                operation=RunOperation.FULL,
                run_control=NO_RUN_CONTROL,
            )
            store.upsert_document_chunks(chunks, write_policy=None)
            checkpoint.record_confirmed_chunks(
                chunks, {chunks[0].doc_id: fingerprint_bytes(path, root, data)}
            )
            assert checkpoint.publish_proof_transition() == 1
            checkpoint.publish_generation()
        registry = ServiceRegistry()
        audit = _Audit(
            root,
            "vault",
            (
                DriftedFile(
                    "vault", f"{docs_dir}/adr/stored.document.md", "content_changed"
                ),
            ),
            0.0,
        )
        try:
            yield audit, registry
        finally:
            registry.close_all()


def test_projection_drift_requires_explicit_rebuild(
    published_vault: tuple[_Audit, ServiceRegistry],
) -> None:
    audit, registry = published_vault
    with registry.lease_store(audit.root) as store:
        store.delete_documents(["adr/stored.document"])
    result = _diagnose(audit, registry)
    assert result.status == "rebuild_required"
    assert result.reason == "unexplained_drift"
    assert result.job_id is None


def test_repaired_file_does_not_request_indexing(
    published_vault: tuple[_Audit, ServiceRegistry],
) -> None:
    audit, registry = published_vault
    hit = _vault_hit(audit)
    assert (
        verify_search_hits(
            audit.root, [hit], capture_hit_publications(audit.root, ("vault",))
        )
        == ()
    )
    assert hit.freshness == "current"
    result = _diagnose(audit, registry)
    assert result.status == "resolved_or_unverifiable"
    assert result.job_id is None


def test_vault_checkpoint_stamp_and_deleted_file_freshness(
    published_vault: tuple[_Audit, ServiceRegistry],
) -> None:
    audit, _registry = published_vault
    hit = _vault_hit(audit)
    snapshot = capture_hit_publications(audit.root, ("vault",))
    path = audit.root / hit.path
    path.write_bytes(path.read_bytes().replace(b"2026-01-01", b"2026-01-02"))
    assert verify_search_hits(audit.root, [hit], snapshot) == ()
    assert hit.freshness == "current"
    path.unlink()
    drift = verify_search_hits(audit.root, [hit], snapshot)
    assert len(drift) == 1
    assert hit.freshness == "stale"
    assert hit.stale_reason == "file_missing"


def test_vault_paths_outside_configured_docs_root_are_unverifiable(
    published_vault: tuple[_Audit, ServiceRegistry],
) -> None:
    audit, _registry = published_vault
    outside = audit.root / "elsewhere" / "stored.document.md"
    outside.parent.mkdir()
    outside.write_bytes(b"# Outside body\n")
    hit = replace(_vault_hit(audit), path="elsewhere/stored.document.md")
    assert (
        verify_search_hits(
            audit.root, [hit], capture_hit_publications(audit.root, ("vault",))
        )
        == ()
    )
    assert hit.freshness == "unverifiable"


def test_incompatible_proof_requires_rebuild_without_admitting_a_job(
    tmp_path: Path,
) -> None:
    _seed_document_proof(
        tmp_path, proof_storage_schema=store_schema.STORAGE_SCHEMA_VERSION + 1
    )
    audit = _Audit(
        tmp_path,
        "document",
        (DriftedFile("document", "report.pdf", "content_changed"),),
        0.0,
    )
    result = _diagnose(audit, ServiceRegistry())
    assert result.status == "rebuild_required"
    assert result.details is not None
    assert result.details["error_kind"] == "incompatible"
    assert result.job_id is None


def _vault_hit(audit: _Audit) -> SearchResult:
    return SearchResult("", audit.files[0].path, "Stored", 0.9, "indexed", "vault")


def test_temporarily_missing_audit_proof_defers_without_rebuild_request(
    tmp_path: Path,
) -> None:
    result = _diagnose(_audit(tmp_path), ServiceRegistry())
    assert result.status == "deferred"
    assert result.reason == "rebuild_required"
    assert result.details is not None
    assert result.details["error_kind"] == "missing"
    assert result.job_id is None


def test_open_publication_receipt_defers_diagnosis(
    published_vault: tuple[_Audit, ServiceRegistry],
) -> None:
    audit, registry = published_vault
    snapshot = capture_hit_publications(audit.root, ("vault",))["vault"]
    generation = snapshot.ledger.generation(snapshot.proof.generation_id)
    successor = snapshot.ledger.start_generation(
        replace(generation.signature, clean=False)
    )
    snapshot.ledger.reserve_publication_receipt(
        snapshot.proof.compatibility_key,
        successor.generation_id,
        expected_parent_revision=snapshot.proof.revision,
    )
    result = _diagnose(audit, registry)
    assert result.status == "deferred"
    assert result.reason == "conflict"
    assert result.job_id is None


def test_shutdown_prevents_late_repair_after_a_real_consistent_audit(
    published_vault: tuple[_Audit, ServiceRegistry],
) -> None:
    audit, registry = published_vault
    (audit.root / audit.files[0].path).write_bytes(b"# Changed body\n")
    hit = _vault_hit(audit)
    drift = verify_search_hits(
        audit.root, [hit], capture_hit_publications(audit.root, ("vault",))
    )
    assert len(drift) == 1
    assert hit.freshness == "stale"
    auditor = SearchDriftAuditor()
    auditor._pending.append((audit, registry))
    auditor.close()
    assert not auditor._pending
    result = _diagnose(audit, registry, auditor._closing)
    assert result.status == "deferred"
    assert result.reason == "service_stopping"
    assert result.job_id is None
    auditor.note_served(audit.root, audit.files, registry)
    assert auditor.snapshot(audit.root, registry) == []
    assert not auditor._pending
    assert auditor._running is False


def test_delivery_reservations_coalesce_pending_and_recent_audits(
    tmp_path: Path,
) -> None:
    # Disabling the reservation guard failed the first coalescing assertion;
    # restoring it passed in the same run.
    auditor = SearchDriftAuditor()
    files = _audit(tmp_path).files
    first = auditor._reserve(tmp_path, files, 1000.0)
    assert first is not None
    for now in (1001.0, 2000.0):
        assert auditor._reserve(tmp_path, files, now) is None
    auditor._audits[tmp_path, "code"] = replace(first, status="rebuild_required")
    assert auditor._reserve(tmp_path, files, 1001.0) is None
    later = auditor._reserve(tmp_path, files, 2000.0)
    assert later is not None
    assert later is not first
    assert later.status == "pending"


def test_only_actually_delivered_stale_rows_trigger_audit() -> None:
    response: dict[str, object] = {
        "results": [
            {
                "source": "codebase",
                "path": "src/a.py",
                "freshness": "stale",
                "stale_reason": "file_missing",
            },
            {
                "source": "codebase",
                "path": "src/a.py",
                "freshness": "stale",
                "stale_reason": "file_missing",
            },
            {"source": "codebase", "path": "src/b.py", "freshness": "current"},
            {"source": "codebase", "path": "src/c.py", "freshness": "unverifiable"},
        ]
    }
    assert served_stale_files(response) == (
        DriftedFile("code", "src/a.py", "file_missing"),
    )
    assert served_stale_files({"ok": False, "error": "rebuild_required"}) == ()


def test_repair_job_refusal_bubbles_and_verified_current_file_clears_observation(
    tmp_path: Path,
) -> None:
    auditor = SearchDriftAuditor()
    auditor._audits[tmp_path, "code"] = replace(
        _audit(tmp_path),
        status="incremental_requested",
        job_id="repair-1",
    )
    registry = ServiceRegistry()
    manager = registry.create_job_manager()
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(tmp_path),
            JobMode.INCREMENTAL,
            RunAuthority.PUBLICATION,
        ),
        JobInitiator("integrity", "stale-hit repair", str(tmp_path)),
        job_id="repair-1",
    )
    assert created.job is not None
    refused = manager.fail_unstarted("repair-1", result=FULL_REINDEX_REQUIRED_PHRASE)
    assert refused.job is not None
    assert refused.job.error_kind == JobErrorKind.FULL_REINDEX_REQUIRED
    diagnostic = auditor.snapshot(tmp_path, registry, port=9876)[0]
    assert diagnostic["status"] == "rebuild_required"
    assert "--rebuild --type code --port 9876" in str(diagnostic["remediation"])
    delivered: dict[str, object] = {
        "results": [
            {
                "path": "src/a.py",
                "source": "codebase",
                "freshness": "current",
            }
        ]
    }
    assert auditor.snapshot(tmp_path, registry, delivered) == []


def test_cli_and_mcp_preserve_stale_hits_and_operator_rebuild_request(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The indexed snippet must survive even if current disk lines contain it.
    (tmp_path / "a.py").write_text(
        "old text plus current disk suffix", encoding="utf-8"
    )
    payload = canonical_service_envelope(
        next(iter(SEARCH_READINESS_SCENARIOS.values()))
    )
    payload["results"] = [
        {
            "id": "point-0",
            "source": "codebase",
            "path": "a.py",
            "score": 0.9,
            "snippet": "old text",
            "line_start": 1,
            "freshness": "stale",
            "stale_reason": "content_changed",
        }
    ]
    payload["drift_audit"] = [
        {
            "source": "code",
            "status": "rebuild_required",
            "remediation": "vaultspec-rag index --rebuild --type code",
        }
    ]
    _handle_service_results(
        payload, _ServiceSearchRenderRequest("query", "code", False, False, tmp_path)
    )
    output = capsys.readouterr().out
    assert "[stale]" in output
    assert "rebuild required" in output
    assert "vaultspec-rag index --rebuild --type code" in output
    assert "old text" in output
    assert "current disk suffix" not in output
    envelope = SearchResults.model_validate(payload).model_dump(mode="json")
    assert envelope["drift_audit"] == payload["drift_audit"]
    assert (
        cast("list[dict[str, object]]", envelope["results"])[0]["freshness"] == "stale"
    )


def test_current_snapshot_cannot_retire_a_newer_audit(tmp_path: Path) -> None:
    # Unconditional removal fails the newer-observation assertion below.
    auditor = SearchDriftAuditor()
    first = auditor._reserve(tmp_path, _audit(tmp_path).files, 1000.0)
    assert first is not None
    finished = replace(first, status="resolved_or_unverifiable")
    auditor._audits[tmp_path, "code"] = finished
    newer = auditor._reserve(tmp_path, first.files, 2000.0)
    assert newer is not None
    auditor._retire(finished)
    assert auditor._audits.get((tmp_path, "code")) is newer
    auditor._retire(newer)
    assert (tmp_path, "code") not in auditor._audits
