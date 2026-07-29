"""CPU-only search-admission coverage for service resource quiesce."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..service import ServiceRegistry
from ..service_quiesce import (
    QuiesceAdmissionClosedError,
    QuiesceState,
    QuiesceTransitionCode,
)

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from pathlib import Path


def test_admission_ticket_must_drain_before_registry_becomes_quiesced() -> None:
    """A pre-pause compute ticket keeps the shared search boundary fail-closed."""
    registry = ServiceRegistry()
    ticket = registry._quiesce_controller.acquire_ticket()
    try:
        timed_out = registry.quiesce_resources(timeout_seconds=0)

        assert timed_out.code is QuiesceTransitionCode.DRAIN_TIMED_OUT
        assert registry.quiesce_snapshot().state is QuiesceState.PAUSING
        assert registry.quiesce_snapshot().active_compute_tickets == 1
        assert registry.snapshot() == []
        assert registry.health()["cuda"] is False
    finally:
        assert ticket.release()

    quiesced = registry.quiesce_resources(timeout_seconds=0)

    assert quiesced.achieved
    assert registry.quiesce_snapshot().state is QuiesceState.QUIESCED
    assert registry.quiesce_snapshot().active_compute_tickets == 0


def test_quiesced_search_lease_rejects_before_project_or_compute_construction(
    tmp_path: Path,
) -> None:
    """Closed search admission cannot construct a store, model, or reranker."""
    registry = ServiceRegistry()

    assert registry.quiesce_resources(timeout_seconds=0).achieved

    with pytest.raises(QuiesceAdmissionClosedError), registry.search_lease(tmp_path):
        pass

    assert registry.snapshot() == []
    assert registry.health()["model_loaded"] is False
    assert registry.health()["reranker_loaded"] is False
    assert registry.health()["cuda"] is False
