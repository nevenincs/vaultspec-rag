"""Every report about the service describes the environment that would serve.

The daemon no longer always runs from the environment that launched the
command: a launcher that cannot serve is answered with the managed runtime,
which the first start creates. The surfaces that report on the service used to
judge the launcher and then describe it as the service's own, so a uvx or
CPU-only launcher was told it could not run the service and offered a torch
repair, while a start from it would have succeeded.

Three plans are driven through each surface: the launcher serves, a published
runtime serves, and a runtime has still to be created. The plan is never
stated directly - it is produced by the real resolver from a pinned child
answer and a real runtime directory, so what is under test is the surface's
reading of it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from .._operator_commands import server_start_command
from ..cli import _service_doctor as doctor
from ..cli import _status
from ..commands._backend_choice import save_backend_choice
from ..commands._models import InstallReport
from ..commands._provision import ProvisionOutcome
from ..operator_state._installation import (
    ComputeCapability,
    HardwarePresence,
    InstallRole,
)
from ..operator_state._provisioning import (
    CU130_INDEX_STRATEGY,
    cuda_remediation,
    durable_upgrade_commands,
    upgrade_commands_for_mode,
)
from ..operator_state._service_environment import ServiceEnvironment
from ..operator_state._topology import TOOL_RECEIPT_NAME
from ..service_runtime import (
    ServiceInterpreterSource,
    planned_service_environment,
    runtime_interpreter,
)
from ._cli_helpers import app, runner
from .conftest import pin_daemon_capability, pin_hardware_presence, pin_install_role
from .test_service_runtime import _interpreter_in, _publish_runtime

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: A receipt that records no CUDA source, so its fix is the two-command
#: sequence that brings one onto the upgrade cycle.
_NO_CUDA_RECEIPT = '[tool]\nrequirements = [{ name = "vaultspec-rag" }]\n'


def _launching(interpreter: str, capability: ComputeCapability) -> ServiceEnvironment:
    """The judgement a command has made of the environment it runs in."""
    return ServiceEnvironment(interpreter, capability)


def _tool_environment(root: Path, *, receipt: str | None = None) -> str:
    """An interpreter in a uv tool installation on disk, with its receipt."""
    interpreter = _interpreter_in(root)
    if receipt is not None:
        (root / TOOL_RECEIPT_NAME).write_text(receipt, encoding="utf-8")
    return interpreter


@pytest.mark.usefixtures("isolated_status_dir")
class TestTheEnvironmentEachSurfaceReportsOn:
    """The shared reading: which interpreter, and what it can do."""

    def test_a_launcher_that_serves_is_the_one_reported(self, tmp_path: Path) -> None:
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")
        launching = _launching(interpreter, ComputeCapability.READY)

        planned = planned_service_environment(launching)

        assert planned.source is ServiceInterpreterSource.LAUNCHING
        assert planned.interpreter == interpreter
        assert planned.environment is launching
        assert planned.launcher_serves is True
        assert planned.runtime_required is False

    def test_a_published_runtime_is_asked_what_it_can_do_itself(
        self, tmp_path: Path
    ) -> None:
        """The runtime's own child answers, not this installation's reading.

        Guard assertion: whether the launcher is a client or carries a
        CPU-only torch says nothing about what the runtime holds, and judging
        the launcher a second time would report the runtime as unable to
        serve. Mutation check: judging ``launching`` instead of the runtime's
        interpreter fails the capability assertion.
        """
        directory = _publish_runtime()
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")
        asked: list[str] = []

        def judge(target: str) -> ServiceEnvironment:
            asked.append(target)
            return ServiceEnvironment(target, ComputeCapability.READY)

        planned = planned_service_environment(
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD), judge=judge
        )

        assert planned.source is ServiceInterpreterSource.RUNTIME
        assert asked == [str(runtime_interpreter(directory))]
        assert planned.interpreter == str(runtime_interpreter(directory))
        assert planned.environment.capability is ComputeCapability.READY
        assert planned.launcher_serves is False
        assert planned.runtime_required is False

    def test_a_runtime_that_has_still_to_be_created_is_named_as_such(
        self, tmp_path: Path
    ) -> None:
        """The plan names a runtime to create, not an environment at fault.

        Reading the absent runtime as an environment that cannot serve is the
        defect itself: every surface then reported a launcher's own torch as
        the reason the service cannot run.
        """
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        planned = planned_service_environment(
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD)
        )

        assert planned.source is ServiceInterpreterSource.RUNTIME_REQUIRED
        assert planned.interpreter == interpreter
        assert planned.launcher_serves is False
        assert planned.runtime_required is True


@pytest.mark.usefixtures("isolated_status_dir")
class TestWhatTheDoctorSaysAboutTheRuntime:
    """``server doctor`` reports the runtime as one more start dependency."""

    def test_a_launcher_that_serves_has_no_runtime_row(self, tmp_path: Path) -> None:
        """A warning for a state that is not present is not printed at all."""
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        planned = planned_service_environment(
            _launching(interpreter, ComputeCapability.READY)
        )

        assert doctor._service_runtime_axis(planned) is None

    def test_a_published_runtime_is_reported_as_ready(self, tmp_path: Path) -> None:
        _publish_runtime()
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        planned = planned_service_environment(
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD),
            judge=lambda target: ServiceEnvironment(target, ComputeCapability.READY),
        )
        axis = doctor._service_runtime_axis(planned)

        assert axis is not None
        assert axis["ready"] is True
        assert str(planned.interpreter) in str(axis["label"])

    def test_a_missing_runtime_is_not_ready_and_names_the_one_command(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: one cause, and the command that resolves it.

        Mutation check: naming any other command, or none, fails the second
        assertion - the first start is the only thing that creates a runtime.
        """
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        planned = planned_service_environment(
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD)
        )
        axis = doctor._service_runtime_axis(planned)

        assert axis is not None
        assert axis["ready"] is False
        assert server_start_command() in str(axis["label"])

    def test_a_receipt_is_judged_only_for_the_installation_that_serves(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: no torch repair for an installation nothing runs in.

        The receipt's fix reinstalls this environment's accelerator build,
        which decides nothing about a service that runs from its own
        environment. Mutation check: dropping the plan from the axis returns
        the verdict for the second case and fails on ``None``.
        """
        tool = _tool_environment(tmp_path / "tool-env", receipt=_NO_CUDA_RECEIPT)
        serving = planned_service_environment(_launching(tool, ComputeCapability.READY))
        not_serving = planned_service_environment(
            _launching(tool, ComputeCapability.CPU_ONLY_BUILD)
        )

        judged = doctor._receipt_axis(serving)

        assert judged is not None
        assert judged["durable"] is False
        assert doctor._receipt_axis(not_serving) is None

    def test_an_upgrade_of_an_installation_that_serves_nothing_keeps_no_build(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: the receipt step is a repair of nothing here.

        The newer release is still taken; what is dropped is the step that
        rewrites the receipt so this environment keeps a CUDA torch, which
        the daemon does not run from. Mutation check: dropping the gate
        returns the serving sequence for both, which fails on the count and
        on the CUDA index.
        """
        tool = _tool_environment(tmp_path / "tool-env", receipt=_NO_CUDA_RECEIPT)

        serving = upgrade_commands_for_mode("tool", tool, serves=True)
        not_serving = upgrade_commands_for_mode("tool", tool, serves=False)

        assert len(serving) == len(not_serving) + 1
        assert any(CU130_INDEX_STRATEGY in command for command in serving)
        assert not_serving == durable_upgrade_commands()
        assert not any(CU130_INDEX_STRATEGY in command for command in not_serving)


@pytest.mark.usefixtures("isolated_status_dir")
class TestTheDoctorVerbFromALauncherThatCannotServe:
    """The whole verb, from the launcher the reports were wrong about."""

    def test_it_offers_the_start_rather_than_a_torch_repair(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: a repair command for an environment nothing runs in.

        A CPU-only launcher with no runtime is not a broken inference host:
        the service gets its own environment on the first start. Printing the
        wheel repair sends the operator to replace a torch the daemon will
        never load, and naming the launcher's capability reports a defect
        where there is none.

        Mutation check: reporting the launching environment's own compute
        verdict prints its label and fails the second assertion. The repair
        assertion holds the other half: it catches a repair printer added
        back for an environment the daemon does not run in.
        """
        pin_install_role(monkeypatch, InstallRole.HOST)
        pin_daemon_capability(monkeypatch, ComputeCapability.CPU_ONLY_BUILD)

        result = runner.invoke(app, ["server", "doctor"])
        envelope = json.loads(runner.invoke(app, ["server", "doctor", "--json"]).stdout)

        assert server_start_command() in result.stdout
        assert ComputeCapability.CPU_ONLY_BUILD.label not in result.stdout
        for step in cuda_remediation(envelope["data"]["interpreter"]).repair_commands:
            assert step not in result.stdout
        assert envelope["data"]["service_runtime"]["ready"] is False
        assert envelope["data"]["receipt"] is None
        # Nothing is running, which is not ready whatever the rows say.
        assert result.exit_code != 0
        assert envelope["data"]["status"] == "not_running"
        assert envelope["data"]["next_action"] == server_start_command()

    def test_a_live_service_reads_ready_though_no_runtime_exists_yet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: an environment nobody uses blocked the verdict.

        A project client beside a live, healthy host service was told
        "dependencies not ready" and exited 1, because the plan's own torch
        row - the runtime that does not exist yet, reported as unchecked -
        was folded into the top line. Nothing about the service answering
        requests was untrue; a start from here would have attached to it.

        Mutation check: folding the dependency rows in under a runtime plan
        reads this as ``dependencies_not_ready`` and fails the status and
        exit-code assertions; the service runtime axis still reports the
        absent runtime, which the last assertion holds.
        """
        from ._cli_helpers import _running_service_record, _status_contract_server

        pin_install_role(monkeypatch, InstallRole.HOST)
        pin_daemon_capability(monkeypatch, ComputeCapability.CPU_ONLY_BUILD)
        server, thread = _status_contract_server(tmp_path)
        try:
            port = server.server_address[1]
            with _running_service_record(tmp_path / "live", port):
                result = runner.invoke(
                    app, ["--target", str(tmp_path), "server", "doctor", "--json"]
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        envelope = json.loads(result.stdout)
        assert envelope["data"]["status"] == "ready"
        assert envelope["data"]["ready"] is True
        assert result.exit_code == 0
        assert envelope["data"]["service_runtime"]["ready"] is False


@pytest.mark.usefixtures("isolated_status_dir")
class TestWhatStatusSaysAboutTheInterpreter:
    """``status`` names the next action and the interpreter a start would use."""

    @pytest.mark.parametrize(
        "capability",
        [ComputeCapability.READY, ComputeCapability.CPU_ONLY_BUILD],
    )
    def test_the_next_action_is_the_start_under_every_plan(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        capability: ComputeCapability,
    ) -> None:
        """Nothing about where the daemon would run changes the next action."""
        from .test_cli_status import _compute, _installation, _view

        pin_install_role(monkeypatch, InstallRole.HOST)
        pin_daemon_capability(monkeypatch, capability)

        _status._render_status_text(
            _view(
                {"storage_path": "data", "vault_count": 1},
                _installation(_compute(capability)),
            )
        )

        output = capsys.readouterr().out
        assert "Next action:" in output
        assert output.rstrip().endswith(server_start_command())

    def test_a_receipt_is_named_only_when_this_installation_serves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: no torch repair for a launcher nothing runs in.

        The fix keeps this installation's GPU build across an upgrade, which
        a service running from its own environment does not use. Mutation
        check: dropping the plan from the line prints the fix for the second
        case and fails the last assertion.
        """
        tool = _tool_environment(tmp_path / "tool-env", receipt=_NO_CUDA_RECEIPT)
        monkeypatch.setattr(
            "vaultspec_rag.cli._process._resolve_daemon_interpreter", lambda: tool
        )
        pin_install_role(monkeypatch, InstallRole.HOST)

        pin_daemon_capability(monkeypatch, ComputeCapability.READY)
        serving = _status._receipt_lines()
        pin_daemon_capability(monkeypatch, ComputeCapability.CPU_ONLY_BUILD)
        not_serving = _status._receipt_lines()

        assert any("Fix, in order:" in line for line in serving)
        assert not_serving == []

    def test_the_note_says_a_runtime_would_be_created(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Guard assertion: the note named an interpreter that would not serve.

        A running service from another interpreter is explained by saying
        what a start from here would use, and from a launcher that cannot
        serve that is not this interpreter at all. Mutation check: naming the
        local interpreter again fails the second assertion.
        """
        from .test_cli_status import _compute, _installation, _view

        pin_install_role(monkeypatch, InstallRole.HOST)
        pin_daemon_capability(monkeypatch, ComputeCapability.CPU_ONLY_BUILD)

        _status._render_status_text(
            _view(
                {"storage_path": "data", "vault_count": 1},
                _installation(_compute(ComputeCapability.READY)),
                service_port=8766,
            )
        )

        output = capsys.readouterr().out
        assert "the running service uses python" in output
        assert "would create its own environment to run in first" in output


@pytest.mark.usefixtures("isolated_status_dir")
class TestTheBackendChoiceAnInstallSaves:
    """An install records server mode for whatever will run the service."""

    class _Run:
        """One install run, as far as the backend choice reads it."""

        def __init__(self, target: Path) -> None:
            self.report = InstallReport(action="install", target=target)
            self.dry_run = False
            self.host = True
            self.local_only = False

    def test_a_launcher_that_cannot_serve_still_chooses_server_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: the saved choice is read by the start it precedes.

        That start runs the service from the managed runtime, so refusing to
        record a backend for a launcher whose own torch cannot serve leaves it
        with no choice to read, and told that its environment cannot run the
        service at all. Mutation check: reading the launching environment's
        verdict instead of the plan's fails the first assertion.
        """
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")
        pin_hardware_presence(monkeypatch, HardwarePresence.NVIDIA_GPU)

        saved = save_backend_choice(
            self._Run(tmp_path),
            ProvisionOutcome(),
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD),
        )

        assert saved.saved is True
        assert saved.local_only is False
        assert "cannot run the service" not in saved.detail

    def test_a_machine_that_can_serve_nothing_chooses_no_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: a runtime built here could not serve either.

        The question a missing runtime asks is about the machine, not about
        the environment in front of it, and a machine with no accelerator is
        where the refusal still belongs - nothing is written for it.

        Mutation check: answering a missing runtime as servable regardless of
        the hardware saves the choice and fails the first assertion.
        """
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")
        pin_hardware_presence(monkeypatch, HardwarePresence.NONE)

        saved = save_backend_choice(
            self._Run(tmp_path),
            ProvisionOutcome(),
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD),
        )

        assert saved.saved is False
        assert HardwarePresence.NONE.label in saved.detail
        assert "this environment cannot run the service" not in saved.detail

    def test_a_runtime_that_cannot_serve_is_named_as_the_services_own(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The remaining refusal is about the service, not the installation.

        A published runtime that cannot run the service is the one case left
        in which no backend is chosen, and the sentence says so of the
        service rather than of the environment the operator installed.
        """
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")
        _publish_runtime()
        pin_install_role(monkeypatch, InstallRole.HOST)
        pin_daemon_capability(monkeypatch, ComputeCapability.NO_DEVICE)

        saved = save_backend_choice(
            self._Run(tmp_path),
            ProvisionOutcome(),
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD),
        )

        assert saved.saved is False
        assert "the service has no environment that can run it yet" in saved.detail
        assert ComputeCapability.NO_DEVICE.label in saved.detail
        assert "this environment cannot run the service" not in saved.detail
