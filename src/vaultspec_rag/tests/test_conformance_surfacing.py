"""Guard tests for reporting a nonconforming namespace to an operator.

A collection built by a superseded model answers every query and looks healthy
by every other signal, so the only thing standing between it and a silently
wrong answer is that the health surface says so. These tests defend that
sentence reaching an operator with the command that fixes it.

Every test here is a guard, so each has been observed failing for its intended
reason; the mutation each one catches is named in its own docstring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ..cli._status_labels import CONFORMANCE_FAMILY, MODELS_FAMILY, degradation_findings
from ..qdrant_runtime._constants import QdrantRuntimeState
from ..server._lifespan import _service_health_status

if TYPE_CHECKING:
    from ..service import ServiceHealth

pytestmark = [pytest.mark.unit]


def _health(**overrides: object) -> ServiceHealth:
    """Build a registry health dict, overriding named fields."""
    base: dict[str, object] = {
        "model_loaded": True,
        "reranker_loaded": True,
        "cuda": True,
        "project_count": 1,
        "projects": ["/proj"],
        "nonconforming": [],
    }
    base.update(overrides)
    return cast("ServiceHealth", base)


def _local_qdrant() -> QdrantRuntimeState:
    """A runtime state that contributes no degradation of its own."""
    return QdrantRuntimeState(mode="local")


class TestHealthAuthorsTheVerdict:
    def test_conforming_service_is_ready_with_no_reasons(self) -> None:
        status, reasons = _service_health_status(_health(), _local_qdrant())
        assert status == "ready"
        assert reasons == []

    def test_nonconforming_collection_degrades_the_service(self) -> None:
        """The whole point: a wrong-model index must stop reading as healthy.

        Mutation it catches: dropping the ``nonconforming`` branch from
        ``_service_health_status``. Without it the service reports ready while
        returning rankings computed against vectors from another model, which
        is the failure this feature exists to remove.
        """
        status, reasons = _service_health_status(
            _health(nonconforming=["/proj:vault_docs"]), _local_qdrant()
        )

        assert status == "degraded"
        assert any("different embedding model" in reason for reason in reasons)

    def test_reason_names_the_affected_collection(self) -> None:
        """An operator must be able to tell which index to rebuild."""
        _, reasons = _service_health_status(
            _health(nonconforming=["/proj:codebase_docs"]), _local_qdrant()
        )
        assert any("codebase_docs" in reason for reason in reasons)


class TestRemediationPairing:
    def test_conformance_reason_pairs_with_the_rebuild_command(self) -> None:
        """A rebuild is the only remedy; a warmup would waste the operator's time.

        Asserts the command attached to the CONFORMANCE CAUSE, not merely that
        a conformance finding exists somewhere in the list. The unclaimed sweep
        appends an unpaired family's finding anyway, so a family-presence
        assertion passes even when the wrong command is attached to this cause
        - an earlier revision asserted exactly that and was proven inert.

        Mutation it catches: removing the conformance family from the registry,
        which leaves this cause with no remedy at all.

        It deliberately does NOT claim to catch the family ORDERING. Reasons
        are resolved in emission order and the models reason is emitted first,
        so it claims the ``model`` stem before this reason is reached; no
        reachable input distinguishes the two orderings today. Asserting an
        ordering no input can exercise would be a test that cannot fail.
        """
        status, reasons = _service_health_status(
            _health(model_loaded=False, nonconforming=["/proj:vault_docs"]),
            _local_qdrant(),
        )

        findings = degradation_findings(
            {
                "status": status,
                "degraded_reasons": reasons,
                "models_loaded": False,
                "nonconforming": ["/proj:vault_docs"],
            }
        )

        conformance_cause = [
            f for f in findings if "different embedding model" in f.cause
        ]
        assert len(conformance_cause) == 1
        assert "--rebuild" in conformance_cause[0].command
        assert conformance_cause[0].family == CONFORMANCE_FAMILY

    def test_models_reason_keeps_its_own_remedy(self) -> None:
        """Two distinct problems must keep two distinct commands.

        Adding a conformance reason alongside must not cost the models reason
        its own remedy. Mutation it catches: unregistering the models family,
        which leaves that cause with no command - the operator is told the
        models are not loaded and given nothing to run.

        Note the stems share a dict keyed by stem text, so two families
        declaring the same stem silently collapse to one. That collision
        damages the conformance reason rather than this one, and is covered by
        the sibling test above.
        """
        status, reasons = _service_health_status(
            _health(model_loaded=False, nonconforming=["/proj:vault_docs"]),
            _local_qdrant(),
        )

        findings = degradation_findings(
            {
                "status": status,
                "degraded_reasons": reasons,
                "models_loaded": False,
                "nonconforming": ["/proj:vault_docs"],
            }
        )

        models_cause = [f for f in findings if "are not loaded" in f.cause]
        assert len(models_cause) == 1
        assert models_cause[0].family == MODELS_FAMILY
        assert models_cause[0].command

    def test_no_conformance_finding_when_nothing_is_nonconforming(self) -> None:
        """An empty list must prove nothing, so no finding is invented."""
        findings = degradation_findings(
            {
                "status": "degraded",
                "degraded_reasons": ["embedding models are not loaded"],
                "models_loaded": False,
                "nonconforming": [],
            }
        )
        assert all(f.family != CONFORMANCE_FAMILY for f in findings)
