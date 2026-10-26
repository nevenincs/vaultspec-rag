"""Bounded stale-hit diagnosis, incremental authority and adapter rendering."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.requests import Request

from .. import _index_integrity, _search_drift, jobs
from .._job_errors import JobError, JobErrorKind
from .._search_drift import SearchDriftAuditor, _Audit, _diagnose, served_stale_files
from .._search_freshness import DriftedFile
from ..cli._search import _handle_service_results, _ServiceSearchRenderRequest
from ..indexer._run_ledger_models import RunAuthority
from ..mcp._tools import SearchResults
from ..server import _routes_search, create_http_app
from ..server._routes_search import SearchRouteResult, _search_route_response
from ..server._runtime import ServerRouteRuntime
from ..service import ServiceRegistry
from ._search_readiness_scenarios import (
    SEARCH_READINESS_SCENARIOS,
    canonical_service_envelope,
)

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.types import Message, Scope

pytestmark = pytest.mark.unit


def _audit(root: Path) -> _Audit:
    return _Audit(
        root, "code", (DriftedFile("code", "src/a.py", "content_changed"),), 0.0
    )


def test_consistent_projection_requests_incremental_with_runtime_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Flipping clean=False to True failed assert_called_once_with; restoration passed.
    registry = ServiceRegistry()
    audit_projection = Mock(return_value={"status": "consistent"})
    still_drifted = Mock(return_value=_audit(tmp_path).files)
    starter = Mock(return_value="repair-1")
    monkeypatch.setattr(_index_integrity, "audit_index_sources", audit_projection)
    monkeypatch.setattr(_search_drift, "_recheck", still_drifted)
    monkeypatch.setattr(jobs, "start_reindex_codebase", starter)
    result = _diagnose(_audit(tmp_path), registry)
    assert result.status == "incremental_requested"
    assert result.job_id == "repair-1"
    starter.assert_called_once_with(
        tmp_path,
        False,
        authority=RunAuthority.PUBLICATION,
        initiator_kind="integrity",
        registry=registry,
    )


@pytest.mark.parametrize("status", ["rebuild_required", "drift", "conflict"])
def test_projection_blockers_never_admit_a_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    # Mutation: letting a blocked audit fall through to starters must fail here.
    projection = Mock(
        return_value={
            "status": status,
            "domains": {"code": {"error_kind": "incompatible"}},
        }
    )
    starter = Mock(return_value="must-not-run")
    monkeypatch.setattr(_index_integrity, "audit_index_sources", projection)
    monkeypatch.setattr(jobs, "start_reindex_codebase", starter)
    result = _diagnose(_audit(tmp_path), ServiceRegistry())
    assert result.status == ("deferred" if status == "conflict" else "rebuild_required")
    starter.assert_not_called()


def test_repaired_or_unreadable_file_does_not_request_indexing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _index_integrity,
        "audit_index_sources",
        Mock(return_value={"status": "consistent"}),
    )
    monkeypatch.setattr(_search_drift, "_recheck", Mock(return_value=()))
    starter = Mock()
    monkeypatch.setattr(jobs, "start_reindex_codebase", starter)
    assert (
        _diagnose(_audit(tmp_path), ServiceRegistry()).status
        == "resolved_or_unverifiable"
    )
    starter.assert_not_called()


def test_temporarily_missing_audit_proof_defers_without_rebuild_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = Mock(
        return_value={
            "status": "rebuild_required",
            "domains": {"code": {"error_kind": "missing"}},
        }
    )
    monkeypatch.setattr(_index_integrity, "audit_index_sources", projection)
    result = _diagnose(_audit(tmp_path), ServiceRegistry())
    assert result.status == "deferred"


def test_shutdown_closes_intake_and_prevents_late_repair_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auditor = SearchDriftAuditor()
    projection = Mock(return_value={"status": "consistent"})
    monkeypatch.setattr(_index_integrity, "audit_index_sources", projection)
    monkeypatch.setattr(
        _search_drift, "_recheck", Mock(return_value=_audit(tmp_path).files)
    )
    starter = Mock(return_value="must-not-run")
    monkeypatch.setattr(jobs, "start_reindex_codebase", starter)
    auditor.close()
    result = _diagnose(_audit(tmp_path), ServiceRegistry(), auditor._closing)
    assert result.status == "deferred"
    assert result.reason == "service_stopping"
    starter.assert_not_called()
    auditor.note_served(tmp_path, _audit(tmp_path).files, ServiceRegistry())
    assert auditor.snapshot(tmp_path, ServiceRegistry()) == []


def test_delivery_coalesces_audits_and_surfaces_typed_rebuild_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    calls: list[_Audit] = []

    def blocked(
        audit: _Audit,
        _registry: ServiceRegistry,
        _closing: threading.Event,
    ) -> _Audit:
        calls.append(audit)
        entered.set()
        assert release.wait(5.0)
        raise JobError(JobErrorKind.FULL_REINDEX_REQUIRED, "content policy changed")

    monkeypatch.setattr(_search_drift, "_diagnose", blocked)
    auditor = SearchDriftAuditor()
    registry = ServiceRegistry()
    original = auditor._drain

    def witnessed_drain() -> None:
        try:
            original()
        finally:
            finished.set()

    monkeypatch.setattr(auditor, "_drain", witnessed_drain)
    files = _audit(tmp_path).files
    try:
        auditor.note_served(tmp_path, files, registry)
        assert entered.wait(5.0)
        for _ in range(20):
            auditor.note_served(tmp_path, files, registry)
        assert len(calls) == 1
        assert auditor.snapshot(tmp_path, registry)[0]["status"] == "pending"
    finally:
        release.set()
        assert finished.wait(5.0)
    diagnostic = auditor.snapshot(tmp_path, registry)[0]
    assert diagnostic["status"] == "rebuild_required"
    assert diagnostic["reason"] == "full_reindex_required: content policy changed"
    assert "--rebuild --type code" in str(diagnostic["remediation"])
    assert str(tmp_path) in str(diagnostic["remediation"])
    auditor.note_served(tmp_path, files, registry)
    assert len(calls) == 1


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
    registry = Mock(spec=ServiceRegistry)
    registry.create_job_manager.return_value.get.return_value = Mock(
        error_kind="full_reindex_required",
        result="policy requires rebuild",
    )
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


async def test_service_starts_audit_only_after_response_body_is_sent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".vault").mkdir()
    registry = ServiceRegistry()
    runtime = ServerRouteRuntime("token", registry, 8765)
    app = create_http_app(runtime, lifespan=None)
    payload: dict[str, object] = {
        "results": [
            {
                "source": "codebase",
                "path": "src/a.py",
                "freshness": "stale",
                "stale_reason": "content_changed",
            }
        ]
    }
    completed = SearchRouteResult(payload, 200, 0.01, None)
    monkeypatch.setattr(
        _routes_search,
        "_execute_search_until_disconnect",
        AsyncMock(return_value=completed),
    )
    messages: list[Message] = []

    def note(
        root: Path, files: tuple[DriftedFile, ...], active: ServiceRegistry
    ) -> None:
        assert root == tmp_path.resolve()
        assert active is registry
        assert files == _audit(tmp_path).files
        assert messages[-1]["type"] == "http.response.body"
        assert messages[-1].get("more_body", False) is False

    observed = Mock(side_effect=note)
    monkeypatch.setattr(runtime.drift_auditor, "note_served", observed)
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "path": "/search",
        "server": ("127.0.0.1", 8765),
        "headers": [],
        "app": app,
    }

    async def receive() -> Message:
        return {
            "type": "http.request",
            "body": json.dumps(
                {
                    "query": "query",
                    "type": "code",
                    "project_root": str(tmp_path),
                }
            ).encode(),
            "more_body": False,
        }

    async def send(message: Message) -> None:
        messages.append(message)

    response = await _search_route_response(Request(scope, receive))
    observed.assert_not_called()
    await response(scope, receive, send)
    observed.assert_called_once()
