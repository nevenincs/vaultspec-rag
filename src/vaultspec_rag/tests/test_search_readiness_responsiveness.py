"""Cold publication reads never block the search handler's event loop."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest

from .. import _publication_state
from .._search_state import FreshnessWaitPolicy
from .._source_types import PublicSourceType
from ..config._types import EnvVar
from ..server import _routes
from ..server._routes_search import SearchRequest, _execute_search_route
from ..service import ServiceRegistry
from ._config_fixtures import reset_config
from .test_search_readiness_restore import _no_jobs, _published

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("policy", list(FreshnessWaitPolicy))
async def test_concrete_search_heartbeat_runs_while_cold_proof_read_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy: FreshnessWaitPolicy,
) -> None:
    _published(tmp_path, "document")
    monkeypatch.setenv(EnvVar.WATCH_ENABLED.value, "0")
    reset_config()
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    acquire = _publication_state.acquire_publication_snapshot

    def blocked_proof_reader(
        root: Path,
        source: PublicSourceType,
    ) -> _publication_state.PublicationSnapshot:
        entered.set()
        # A bounded release keeps a synchronous-call mutant from wedging pytest.
        release.wait(timeout=1)
        finished.set()
        return acquire(root, source)

    def empty_backend(self: ServiceRegistry, root: Path) -> int:
        del self, root
        return 0

    async def heartbeat() -> bool:
        while not entered.is_set():
            await asyncio.sleep(0)
        return not finished.is_set()

    monkeypatch.setattr(
        _publication_state, "acquire_publication_snapshot", blocked_proof_reader
    )
    monkeypatch.setattr(ServiceRegistry, "document_chunk_count", empty_backend)
    monkeypatch.setattr(_routes, "canonical_job_snapshot", _no_jobs)
    beat = asyncio.create_task(heartbeat())
    searching = asyncio.create_task(
        _execute_search_route(
            SearchRequest(
                tmp_path,
                "empty documents",
                1,
                {},
                PublicSourceType.DOCUMENT,
                "responsive-cold-publication",
                freshness_policy=policy,
                freshness_wait_seconds=0,
            ),
            None,
            registry,
        )
    )
    try:
        responsive = await asyncio.wait_for(beat, timeout=3)
        # Mutating either actual handler back to a synchronous snapshot makes
        # the heartbeat resume only after the blocked reader has finished.
        assert responsive, (
            "cold readiness proof read must leave the event loop responsive"
        )
    finally:
        release.set()
        result = await asyncio.wait_for(searching, timeout=5)
        registry.readiness_registry.close()
        reset_config()
    assert result.status_code == 200
    assert result.result["results"] == []
    assert finished.is_set()
