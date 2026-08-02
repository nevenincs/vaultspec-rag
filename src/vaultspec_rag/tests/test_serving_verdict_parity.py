"""The CLI's serving verdict must agree with the service's own.

`server start` stopped waiting for `/health` to report the literal word
`ready`, because that word is also lowered by job history and a single stale
failure held it down indefinitely. It now decides from the payload's structured
infrastructure fields instead.

That is correct today and bounded exactly to job history - but it means the CLI
carries a second copy of a service-domain verdict, and nothing held the two
together. Add a third infrastructure degradation reason server-side - a schema
gate, a reranker that failed to load, a store that will not open - and the CLI
would not know about it: `server start` would exit 0 against a daemon that
cannot answer a query, silently, with the whole suite green.

These tests are that binding. They drive both implementations from one table of
inputs and require them to agree, so a reason added on one side and not the
other fails here rather than in production. No mocks: the real
`_service_health_status` runs against real registry-health mappings and real
runtime states, and the CLI reads the payload shape the real health handler
builds from those same objects.
"""

from __future__ import annotations

import pytest

from ..cli._service_start import _daemon_is_serving
from ..qdrant_runtime._constants import QdrantRuntimeState
from ..server._lifespan import _service_health_status
from ..service import ServiceHealth
from ._quiesce_helpers import running_quiesce_snapshot

pytestmark = [pytest.mark.unit]


def _registry_health(*, model_loaded: bool) -> ServiceHealth:
    """The mapping `ServiceRegistry.health` returns, in its declared type."""
    return ServiceHealth(
        model_loaded=model_loaded,
        reranker_loaded=True,
        cuda=True,
        project_count=1,
        projects=["main"],
        nonconforming=[],
    )


def _health_payload(
    reg_health: ServiceHealth,
    qdrant_state: QdrantRuntimeState,
) -> dict[str, object]:
    """Build the payload the real health handler publishes from these inputs.

    Mirrors the two fields the CLI verdict reads. Keeping this derivation in
    one place is what makes the comparison below meaningful: both sides start
    from the same objects rather than from two hand-written literals that could
    drift apart without either test noticing.
    """
    return {
        "models_loaded": reg_health["model_loaded"],
        "qdrant": qdrant_state.to_dict(),
    }


#: Every reachable combination of the two conditions the service treats as
#: infrastructure degradation. `alive=None` is the no-supervised-child case,
#: which is why it is listed separately from an explicitly dead child.
_CASES = [
    (
        "server backend, models up, child alive",
        True,
        QdrantRuntimeState(mode="server", alive=True),
    ),
    (
        "server backend, models up, child dead",
        True,
        QdrantRuntimeState(mode="server", alive=False),
    ),
    (
        "server backend, models down, child alive",
        False,
        QdrantRuntimeState(mode="server", alive=True),
    ),
    (
        "server backend, models down, child dead",
        False,
        QdrantRuntimeState(mode="server", alive=False),
    ),
    ("local backend, models up", True, QdrantRuntimeState(mode="local", alive=None)),
    ("local backend, models down", False, QdrantRuntimeState(mode="local", alive=None)),
]


@pytest.mark.parametrize(
    ("label", "model_loaded", "qdrant_state"),
    _CASES,
    ids=[case[0] for case in _CASES],
)
def test_the_cli_serves_exactly_when_the_service_reports_no_infrastructure_fault(
    label: str,
    model_loaded: bool,
    qdrant_state: QdrantRuntimeState,
) -> None:
    """The two verdicts agree on every reachable infrastructure combination.

    The service's own status word is deliberately NOT the comparison: it also
    carries job history, which is the whole reason the CLI stopped reading it.
    The binding is against the service's infrastructure *reasons*, which is the
    half the CLI claims to reproduce.
    """
    reg_health = _registry_health(model_loaded=model_loaded)
    _, infrastructure_reasons = _service_health_status(
        reg_health, qdrant_state, running_quiesce_snapshot()
    )
    payload = _health_payload(reg_health, qdrant_state)

    service_sees_a_fault = bool(infrastructure_reasons)
    cli_says_serving = _daemon_is_serving(payload)

    assert cli_says_serving is not service_sees_a_fault, (
        f"the CLI and the service disagree about {label!r}: the service "
        f"reported {infrastructure_reasons or 'no infrastructure fault'} while "
        f"the CLI said serving={cli_says_serving}. A degradation reason added "
        "to the service must be taught to the CLI verdict too, or `server "
        "start` will exit 0 against a daemon that cannot answer a query."
    )


def test_a_job_history_fault_is_not_an_infrastructure_fault() -> None:
    """Job history must stay outside the parity above.

    This is the property the readiness change bought, and it is asserted here
    so the binding cannot be satisfied by making the CLI read the status word
    again - which would reintroduce the stale-failure timeout the change fixed.
    """
    reg_health = _registry_health(model_loaded=True)
    state = QdrantRuntimeState(mode="server", alive=True)
    _, infrastructure_reasons = _service_health_status(
        reg_health, state, running_quiesce_snapshot()
    )
    assert infrastructure_reasons == []

    payload = _health_payload(reg_health, state)
    # The daemon is degraded by history alone; the CLI must still serve.
    payload["status"] = "degraded"
    payload["degraded_reasons"] = ["the latest indexing job failed: other"]
    assert _daemon_is_serving(payload) is True
