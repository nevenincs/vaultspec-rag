"""A source mid-reset answers one typed retryable transition on every surface.

A real server answers over loopback with a real service registry, a real local
store and a real run ledger. The reset in progress is the exact durable state
a rebuild leaves between recording its intent and recording completion. The
raw route, the command line in JSON mode and an MCP process started the way an
agent host starts one all ask while the reset is in flight, and each receives
the service's one envelope: no results, the ``index_transition`` code, a
retry, and a readiness fact naming the transition. A sibling source keeps
answering throughout.

MUTATION PROOF: narrowing the typed-refusal handler in
``run_search_with_availability`` to ``StorageGeometryError`` alone failed
``test_a_source_mid_reset_answers_one_transition_on_every_surface`` on its
``status == 503`` assertion (the route answered 500); restoring it passed.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ..._source_types import PublicSourceType
from ...cli import app
from ..test_search_reset_fence import record_reset_intent
from ._service_jobs_support import _canonical_resilience_server
from ._service_search_diagnostics_support import raw_search
from .test_service_search_diagnostics_mcp import _official_search_call

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()


@pytest.fixture(name="served")
def _served(tmp_path: Path) -> Generator[tuple[int, str, Path]]:
    """Serve a local-storage root over real HTTP; yield port, token and root."""
    from ...config._settings import get_config

    root = (tmp_path / "project").resolve()
    (root / ".vault").mkdir(parents=True)
    (root / ".vaultspec").mkdir()
    with _canonical_resilience_server(tmp_path) as (port, token):
        get_config(
            {
                "local_only": True,
                "qdrant_url": None,
                "embedding_dimension": 2,
                "sparse_enabled": False,
                "watch_enabled": False,
            }
        )
        yield port, token, root


def _assert_transition(body: dict[str, object], source: str) -> None:
    assert body["ok"] is False
    assert body["error"] == "index_transition"
    assert body["retryable"] is True
    assert "results" not in body
    readiness = cast("dict[str, object]", body["readiness"])
    (fact,) = cast("list[dict[str, object]]", readiness["sources"])
    assert fact["source"] == source
    assert fact["reason_code"] == "index_transition"
    assert fact["absence_authority"] == "non_authoritative"


def _search(
    port: int, token: str, root: Path, search_type: str
) -> tuple[int, dict[str, object]]:
    status, _headers, body = raw_search(
        port,
        token,
        {"query": "needle", "type": search_type, "project_root": str(root)},
        timeout=60,
    )
    return status, body


def test_a_source_mid_reset_answers_one_transition_on_every_surface(
    served: tuple[int, str, Path], tmp_path: Path
) -> None:
    port, token, root = served
    record_reset_intent(root, PublicSourceType.VAULT)

    status, body = _search(port, token, root, "vault")
    assert status == 503
    _assert_transition(body, "vault")
    index_state = cast("dict[str, object]", body["index_state"])
    assert index_state["status"] == "rebuilding"
    assert "indexed_count" not in index_state

    sibling_status, sibling = _search(port, token, root, "code")
    del sibling_status
    assert sibling.get("error") != "index_transition"

    cli = runner.invoke(
        app,
        [
            "--target",
            str(root),
            "search",
            "needle",
            "--type",
            "vault",
            "--port",
            str(port),
            "--json",
        ],
    )
    assert cli.exit_code == 1
    emitted = json.loads(cli.output)
    _assert_transition(emitted, "vault")

    mcp = asyncio.run(
        _official_search_call(
            port=port,
            status_dir=tmp_path / "resilience-status",
            root=root,
            tool_name="search_vault",
        )
    )
    assert mcp.is_error is False
    structured = dict(cast("dict[str, object]", mcp.structured_content))
    _assert_transition(structured, "vault")


def test_combined_search_keeps_answering_around_a_source_mid_reset(
    served: tuple[int, str, Path],
) -> None:
    """The fan-out carries the transition for one domain and the rest succeed."""
    port, token, root = served
    record_reset_intent(root, PublicSourceType.CODE)

    status, body = _search(port, token, root, "combined")

    domains = cast("dict[str, dict[str, object]]", body["domains"])
    assert domains["code"]["ok"] is False
    assert domains["code"]["error_kind"] == "index_transition"
    assert domains["vault"]["ok"] is True
    readiness = cast("dict[str, object]", body["readiness"])
    facts = {
        fact["source"]: fact
        for fact in cast("list[dict[str, object]]", readiness["sources"])
    }
    assert facts["code"]["reason_code"] == "index_transition"
    assert facts["code"]["retryable"] is True
    # Every domain is empty, so the answer is the dominant typed failure.
    assert status == 503
    assert body["error"] == "index_transition"
    assert body["retryable"] is True
