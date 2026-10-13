"""The monitor as one step of provisioning, and one row of readiness.

The monitor is obtained where the models and the server binary are obtained,
by the command that is already running, and reported in the same vocabulary
that reports them. These tests hold that it is there: in what a host install
and a host start consider, in the order the daemon needs, with the same
answer for a client installation that the other fetch-and-go dependencies
give, and as one row on the readiness dependency axis.

The environment is staged as every provisioning test stages it: the
installation role and the accelerator capability are pinned, and the monitor
the session names through the operator settings stands in for the one a
release provides.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pytest

from .._readiness import ReadinessStatus, _monitor_readiness
from .._sync_vocabulary import ProvisionAction
from ..cli._render import _render_provisioning_outcome
from ..commands._provision import (
    ProvisionOutcome,
    ProvisionStep,
    ProvisionStepResult,
    ensure_runtime_dependencies,
)
from ..config._types import EnvVar
from ..monitor_runtime._provision import MONITOR_PROVISION_FAILED
from ..operator_state._installation import ComputeCapability
from ..operator_state._service_environment import ServiceEnvironment
from ._provision_fixtures import result_for
from .conftest import managed_env

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: The judgement a host start has made by the time it reaches the step.
_HOST_READY = ServiceEnvironment("", ComputeCapability.READY)
#: A client installation, which runs no service and needs no monitor.
_CLIENT = ServiceEnvironment("", ComputeCapability.NOT_APPLICABLE)
#: A host whose accelerator stack is not usable yet.
_NOT_YET = ServiceEnvironment("", ComputeCapability.TORCH_MISSING)

#: Both monitor settings cleared. They name the session's stand-in, which
#: would otherwise answer every case here.
_NO_OPERATOR_MONITOR: dict[str, str | None] = {
    EnvVar.MONITOR_BINARY.value: None,
    EnvVar.MONITOR_BINARY_SHA256.value: None,
}


class TestAStartConsidersTheMonitor:
    @pytest.mark.usefixtures("inference_host")
    def test_the_monitor_is_one_step_of_what_a_start_fetches(self) -> None:
        """In the order the daemon needs: models, then the server, then it."""
        outcome = ensure_runtime_dependencies(
            environment=_HOST_READY,
            server_unneeded="the on-disk store is selected",
            qdrant_auto_provision=True,
        )

        steps = [result.step for result in outcome.steps]
        assert steps == [
            ProvisionStep.MODELS,
            ProvisionStep.QDRANT,
            ProvisionStep.MONITOR,
        ]
        monitor = result_for(outcome, ProvisionStep.MONITOR)
        assert monitor is not None
        assert monitor.action is ProvisionAction.UNCHANGED, monitor.detail

    @pytest.mark.usefixtures("client_installation")
    def test_a_client_is_told_it_needs_none(self) -> None:
        """The same answer the other fetch-and-go dependencies give a client.

        Mutation: asked the provisioner before the role. Observed this test
        and the one below it fail on the skipped-action assertion, the step
        reporting on a monitor rather than saying a client needs none.
        Restored; passes.
        """
        outcome = ensure_runtime_dependencies(
            environment=_CLIENT,
            server_unneeded="a client runs no server",
            qdrant_auto_provision=True,
        )

        monitor = result_for(outcome, ProvisionStep.MONITOR)
        assert monitor is not None
        assert monitor.action is ProvisionAction.SKIPPED
        assert "client" in monitor.detail
        qdrant = result_for(outcome, ProvisionStep.QDRANT)
        assert qdrant is not None
        # Mechanically the same branch, so the two read alike wherever they
        # are shown together.
        assert monitor.detail == qdrant.detail

    @pytest.mark.usefixtures("inference_host")
    def test_a_host_that_cannot_run_the_service_yet_fetches_nothing(self) -> None:
        """Told why, and that a start fetches it once the environment is ready."""
        outcome = ensure_runtime_dependencies(
            environment=_NOT_YET,
            server_unneeded=None,
            qdrant_auto_provision=True,
        )

        monitor = result_for(outcome, ProvisionStep.MONITOR)
        assert monitor is not None
        assert monitor.action is ProvisionAction.SKIPPED
        assert "cannot run the service yet" in monitor.detail

    @pytest.mark.usefixtures("inference_host")
    def test_an_installation_with_no_monitor_fails_the_step_under_its_own_code(
        self,
    ) -> None:
        """A start that cannot get a monitor is a failed start, with a code.

        The monitor is mandatory for a managed start, so this is a failure
        and not a warning. The code is the step's own, so a caller reports it
        under its own name rather than guessing from the text.
        """
        with managed_env(**_NO_OPERATOR_MONITOR):
            outcome = ensure_runtime_dependencies(
                environment=_HOST_READY,
                server_unneeded="the on-disk store is selected",
                qdrant_auto_provision=True,
            )

        monitor = result_for(outcome, ProvisionStep.MONITOR)
        assert monitor is not None
        assert monitor.action is ProvisionAction.FAILED
        assert monitor.code == MONITOR_PROVISION_FAILED
        assert not outcome.ok
        assert outcome.status == str(ProvisionAction.FAILED)

    @pytest.mark.usefixtures("inference_host")
    def test_a_failed_server_step_stops_before_the_monitor(self) -> None:
        """One failure is reported, not a list of consequences of it.

        The sequence stops at the first step that fails, so a host that
        cannot get its server is not also sent to fetch a monitor it has no
        service to run.
        """
        with managed_env(
            **{
                EnvVar.QDRANT_BINARY.value: "not-an-absolute-path",
                EnvVar.QDRANT_BINARY_SHA256.value: "0" * 64,
            }
        ):
            outcome = ensure_runtime_dependencies(
                environment=_HOST_READY,
                server_unneeded=None,
                qdrant_auto_provision=True,
            )

        qdrant = result_for(outcome, ProvisionStep.QDRANT)
        assert qdrant is not None
        assert qdrant.action is ProvisionAction.FAILED
        assert result_for(outcome, ProvisionStep.MONITOR) is None


def test_the_monitor_step_is_named_in_the_provisioning_summary() -> None:
    """One label, in the block that already names the other dependencies.

    Mutation: removed the monitor's label. Observed this test fail on the
    label assertion, the line reading "monitor: ..." in the step's own
    token instead of the operator's word for it. Restored; passes.
    """
    outcome = ProvisionOutcome(
        steps=[
            ProvisionStepResult(
                step=ProvisionStep.MONITOR,
                action=ProvisionAction.CREATED,
                detail="fetched and verified",
            )
        ]
    )
    buffer = io.StringIO()

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "vaultspec_rag.cli._render._plain",
            lambda line, **_: buffer.write(f"{line}\n"),
        )
        _render_provisioning_outcome(outcome)

    assert "  Monitor: downloaded (fetched and verified)" in buffer.getvalue()


class TestTheReadinessRow:
    def test_a_monitor_that_resolves_reads_ready(self) -> None:
        row = _monitor_readiness()

        assert row.name == "monitor"
        assert row.status is ReadinessStatus.READY
        assert row.info["monitor_source"] == "env"

    def test_no_monitor_reads_not_ready_with_one_cause(self) -> None:
        """One blocking answer, and nothing for anyone to do about it.

        Obtaining the monitor is automatic, so the row says whether one is
        there and never names a command.
        """
        with managed_env(**_NO_OPERATOR_MONITOR):
            row = _monitor_readiness()

        assert row.status is ReadinessStatus.NOT_READY
        assert row.detail
        assert "run " not in row.detail
        assert EnvVar.MONITOR_BINARY.value not in row.detail

    def test_a_client_installation_needs_none(self, tmp_path: Path) -> None:
        """The qdrant row's client branch, mechanically.

        Mutation: judged the client after resolving. Observed this test fail
        on the detail assertion, the row reporting a resolved monitor instead
        of saying a client needs none. Restored; passes.
        """
        del tmp_path
        row = _monitor_readiness(ComputeCapability.NOT_APPLICABLE)

        assert row.status is ReadinessStatus.READY
        assert "this installation is a client" in row.detail
        assert row.info["monitor_source"] == "not_needed"
