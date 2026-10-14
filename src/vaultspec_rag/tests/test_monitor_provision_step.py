"""The monitor as one step of provisioning, and one row of readiness.

The monitor is obtained where the models and the server binary are obtained,
by the command that is already running, and reported in the same vocabulary
that reports them. These tests hold that it is there: in what a host install
and a host start consider, in the order the daemon needs, with the same
answer for a client installation that the other fetch-and-go dependencies
give, and as one row on the readiness dependency axis.

The environment is staged as every provisioning test stages it: the
installation role and the accelerator capability are pinned. The monitor is the
one this checkout compiled and pinned, and a case about an installation that
has none runs in an installation of its own that carries no digests. What the
machine can serve on is read from the machine, and each case asserts the branch
that reading puts it in.
"""

from __future__ import annotations

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
from ..monitor_runtime._resolve import MonitorSource
from ..operator_state._hardware import read_hardware
from ..operator_state._installation import ComputeCapability
from ..operator_state._service_environment import ServiceEnvironment
from ._provision_fixtures import result_for
from ._separate_installation import INSTALLED_FROM_A_WHEEL, build_installation
from .conftest import SERVING_HARDWARE, managed_env

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: The judgement a host start has made by the time it reaches the step.
_HOST_READY = ServiceEnvironment("", ComputeCapability.READY)
#: A client installation, which runs no service and needs no monitor.
_CLIENT = ServiceEnvironment("", ComputeCapability.NOT_APPLICABLE)
#: A host whose own accelerator stack is not usable yet, so a start serves
#: the daemon from the managed runtime instead of this environment.
_NOT_YET = ServiceEnvironment("", ComputeCapability.TORCH_MISSING)


#: Run in a separate installation: the start's own sequence of fetches, then the
#: monitor step's outcome and the outcome's own verdict.
_RUN_THE_START_SEQUENCE = """
import json

from vaultspec_rag.commands._provision import (
    ProvisionStep,
    ensure_runtime_dependencies,
)
from vaultspec_rag.operator_state._installation import ComputeCapability
from vaultspec_rag.operator_state._service_environment import ServiceEnvironment

outcome = ensure_runtime_dependencies(
    environment=ServiceEnvironment("", ComputeCapability.READY),
    server_unneeded="the on-disk store is selected",
    qdrant_auto_provision=True,
)
monitor = next(row for row in outcome.steps if row.step == ProvisionStep.MONITOR)
print(json.dumps({
    "action": str(monitor.action),
    "code": monitor.code,
    "ok": outcome.ok,
    "status": outcome.status,
}))
"""

#: Run in a separate installation: the readiness row for the monitor.
_READ_THE_MONITOR_ROW = """
import json

from vaultspec_rag._readiness import _monitor_readiness

row = _monitor_readiness()
print(json.dumps({"status": str(row.status), "detail": row.detail}))
"""


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
    def test_a_host_whose_own_torch_cannot_serve_follows_what_the_machine_can(
        self,
    ) -> None:
        """The daemon runs from the managed runtime, where anything here can serve.

        What this environment's own torch can do does not decide the step:
        whether the machine has a supported accelerator does, because a start
        serves from the managed runtime, and the monitor that runtime launches
        is the machine-wide managed install this step provisions. With one the
        step is entered and reports on a monitor. Without one it is skipped in
        the same words the model and server steps use, and says that a start
        fetches it where there is something to fetch it for.

        The machine is the one the suite runs on, read as the product reads it,
        and each branch asserts exactly what that reading implies: a
        workstation proves the first and an accelerator-free runner the second.

        Mutation: answered every machine as one nothing can serve on. Observed
        this test fail on the unchanged-action assertion, the step skipped on
        a machine that can serve. Restored; passes. The other branch's
        expectation, mutated to claim this machine cannot serve, failed on the
        skipped-action assertion with the step reporting on a monitor.
        """
        presence = read_hardware().presence

        outcome = ensure_runtime_dependencies(
            environment=_NOT_YET,
            server_unneeded=None,
            qdrant_auto_provision=True,
        )

        monitor = result_for(outcome, ProvisionStep.MONITOR)
        assert monitor is not None
        if presence in SERVING_HARDWARE:
            assert monitor.action is ProvisionAction.UNCHANGED, monitor.detail
        else:
            assert monitor.action is ProvisionAction.SKIPPED, monitor.detail
            assert "no service can run on this machine" in monitor.detail
            assert presence.label in monitor.detail
            qdrant = result_for(outcome, ProvisionStep.QDRANT)
            assert qdrant is not None
            assert monitor.detail == qdrant.detail

    def test_an_installation_with_no_monitor_fails_the_step_under_its_own_code(
        self, tmp_path: Path
    ) -> None:
        """A start that cannot get a monitor is a failed start, with a code.

        The monitor is mandatory for a managed start, so this is a failure
        and not a warning. The code is the step's own, so a caller reports it
        under its own name rather than guessing from the text.

        A checkout that compiled a monitor carries digests for it, so the
        sequence runs in an installation of its own that carries none, in a
        fresh interpreter, and any monitor the operator settings name is
        cleared or it would answer first.

        Mutation: left the step's own code empty. Observed this test fail on
        the answer it compares, with every other field unchanged. Restored;
        passes.
        """
        installed = build_installation(
            tmp_path, version="9.9.9", direct_url=INSTALLED_FROM_A_WHEEL
        )

        with managed_env(
            **{
                EnvVar.MONITOR_BINARY.value: None,
                EnvVar.MONITOR_BINARY_SHA256.value: None,
            }
        ):
            answer = installed.run(_RUN_THE_START_SEQUENCE)

        assert answer == {
            "action": ProvisionAction.FAILED,
            "code": MONITOR_PROVISION_FAILED,
            "ok": False,
            "status": str(ProvisionAction.FAILED),
        }

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


def test_the_monitor_step_is_named_in_the_provisioning_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
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

    _render_provisioning_outcome(outcome)

    assert "  Monitor: downloaded (fetched and verified)" in capsys.readouterr().out


class TestTheReadinessRow:
    def test_a_monitor_that_resolves_reads_ready(self) -> None:
        """The monitor this checkout compiled and pinned is the one that resolves.

        It is installed beside this environment's own programs, which is where
        a development setup puts it, so the row names that place as its source.
        """
        row = _monitor_readiness()

        assert row.name == "monitor"
        assert row.status is ReadinessStatus.READY
        assert row.info["monitor_source"] == str(MonitorSource.INSTALLATION_SIBLING)

    def test_no_monitor_reads_not_ready_with_one_cause(self, tmp_path: Path) -> None:
        """One blocking answer, and nothing for anyone to do about it.

        Obtaining the monitor is automatic, so the row says whether one is
        there and never names a command. The installation is one that carries
        no digests, run in a fresh interpreter, because the checkout this
        suite runs in carries digests for the monitor it compiled; any monitor
        the operator settings name is cleared or it would answer first.

        Mutation: read the refusal as ready. Observed this test fail on the
        status assertion. Mutation: appended an instruction to the detail.
        Observed this test fail on the no-command assertion, with the status
        assertion passing. Each restored; passes.
        """
        installed = build_installation(
            tmp_path, version="9.9.9", direct_url=INSTALLED_FROM_A_WHEEL
        )

        with managed_env(
            **{
                EnvVar.MONITOR_BINARY.value: None,
                EnvVar.MONITOR_BINARY_SHA256.value: None,
            }
        ):
            row = installed.run(_READ_THE_MONITOR_ROW)

        assert row["status"] == ReadinessStatus.NOT_READY
        assert row["detail"]
        assert "run " not in str(row["detail"])
        assert EnvVar.MONITOR_BINARY.value not in str(row["detail"])

    def test_a_check_that_does_not_finish_is_not_ready(self) -> None:
        """Running out of time is neither a pass nor an absent monitor.

        Deciding what is installed hashes the largest file this installation
        provisions, and this report also answers a route a broker polls. A
        budget of nothing stands in for a file that cannot be read in time.

        Mutation: reported an unfinished judgement as no monitor installed.
        Observed this test fail on the source assertion, the row saying
        ``absent`` where nothing at all is known. Restored; passes.
        """
        row = _monitor_readiness(verify_budget=0.0)

        assert row.status is ReadinessStatus.NOT_READY
        assert row.info["monitor_source"] == "unchecked"
        assert row.info["monitor_error"] == "monitor_unchecked"
        assert "could not be verified" in row.detail

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
