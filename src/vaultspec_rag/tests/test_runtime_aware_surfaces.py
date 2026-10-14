"""Every report about the service describes the environment that would serve.

The daemon no longer always runs from the environment that launched the
command: a launcher that cannot serve is answered with the managed runtime,
which the first start creates. The surfaces that report on the service used to
judge the launcher and then describe it as the service's own, so a uvx or
CPU-only launcher was told it could not run the service and offered a torch
repair, while a start from it would have succeeded.

Three plans are driven through each surface: the launcher serves, a published
runtime serves, and a runtime has still to be created. The plan is never
stated directly - it is produced by the real resolver from a real environment
and a real runtime directory, so what is under test is the surface's reading
of it.

The environments are real. A launcher that serves is an installation whose
environment reaches this host's inference stack; one that cannot is the same
with the CPU build of torch installed in it, which is what a workstation holds
when torch resolved from the public index. Each is a uv tool environment, so
the receipt that would lose its GPU build on upgrade is there to be read. The
commands run in a fresh interpreter of that installation, and what a published
runtime can do is what its own interpreter says when it is asked.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, cast

import pytest

from .._operator_commands import server_start_command
from ..cli import _service_doctor as doctor
from ..commands._backend_choice import save_backend_choice
from ..commands._models import InstallReport
from ..commands._provision import ProvisionOutcome
from ..operator_state._hardware import read_hardware
from ..operator_state._installation import ComputeCapability
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
    installed_release,
    planned_service_environment,
    runtime_interpreter,
)
from ._real_environments import (
    NO_CUDA_RECEIPT,
    as_a_tool_environment,
    invoke_the_cli,
    publish_runtime,
    with_a_cpu_build_of_torch,
)
from ._separate_installation import SeparateInstallation, build_installation
from .test_service_preflight_cli import _production_service
from .test_service_runtime import _interpreter_in

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _launching(interpreter: str, capability: ComputeCapability) -> ServiceEnvironment:
    """The judgement a command has made of the environment it runs in."""
    return ServiceEnvironment(interpreter, capability)


def _tool_environment(root: Path, *, receipt: str | None = None) -> str:
    """An interpreter in a uv tool installation on disk, with its receipt."""
    interpreter = _interpreter_in(root)
    if receipt is not None:
        (root / TOOL_RECEIPT_NAME).write_text(receipt, encoding="utf-8")
    return interpreter


def _workspace(directory: Path) -> Path:
    """A directory the command line and a service accept as a project."""
    (directory / ".vaultspec").mkdir()
    (directory / ".vault").mkdir()
    return directory


def _tool_installation(directory: Path, *, cpu: bool) -> SeparateInstallation:
    """A separate installation in a uv tool environment of its own.

    With *cpu* the environment holds the CPU build of torch, so the daemon
    would not run from it; without, it reaches this host's own inference stack.
    """
    installation = build_installation(
        directory, version=installed_release(), direct_url=None, own_environment=True
    )
    as_a_tool_environment(installation.interpreter)
    if cpu:
        with_a_cpu_build_of_torch(installation.interpreter)
    return installation


def _receipt_lines_of(installation: SeparateInstallation) -> list[str]:
    """The lines ``status`` prints about the receipt of *installation*."""
    program = (
        "import json\n"
        "from vaultspec_rag.cli import _status\n"
        "print(json.dumps({'lines': _status._receipt_lines()}))\n"
    )
    lines = installation.run(program)["lines"]
    assert isinstance(lines, list)
    return [str(line) for line in cast("list[object]", lines)]


@pytest.fixture(scope="module")
def serving_tool(tmp_path_factory: pytest.TempPathFactory) -> SeparateInstallation:
    """A tool installation whose own environment can run the service."""
    return _tool_installation(tmp_path_factory.mktemp("serving-tool"), cpu=False)


@pytest.fixture(scope="module")
def cpu_tool(tmp_path_factory: pytest.TempPathFactory) -> SeparateInstallation:
    """A tool installation whose environment holds only a CPU build of torch."""
    return _tool_installation(tmp_path_factory.mktemp("cpu-tool"), cpu=True)


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

    @pytest.mark.torch
    def test_a_published_runtime_is_asked_what_it_can_do_itself(
        self, tmp_path: Path
    ) -> None:
        """The runtime's own child answers, not this installation's reading.

        Guard assertion: whether the launcher is a client or carries a
        CPU-only torch says nothing about what the runtime holds, and judging
        the launcher a second time would report the runtime as unable to
        serve. The runtime here is a real environment that reaches this
        host's GPU stack, judged by a child of its own interpreter, against a
        launcher whose judgement says it cannot serve. Mutation check: judging
        ``launching`` instead of the runtime's interpreter fails the assertion
        on the interpreter the environment was judged for, and the capability
        assertion after it.
        """
        directory = publish_runtime()
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        planned = planned_service_environment(
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD)
        )

        assert planned.source is ServiceInterpreterSource.RUNTIME
        assert planned.interpreter == str(runtime_interpreter(directory))
        assert planned.environment.interpreter == str(runtime_interpreter(directory))
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

    @pytest.mark.torch
    def test_a_published_runtime_is_reported_as_ready(self, tmp_path: Path) -> None:
        publish_runtime()
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")

        planned = planned_service_environment(
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD)
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
        tool = _tool_environment(tmp_path / "tool-env", receipt=NO_CUDA_RECEIPT)
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
        tool = _tool_environment(tmp_path / "tool-env", receipt=NO_CUDA_RECEIPT)

        serving = upgrade_commands_for_mode("tool", tool, serves=True)
        not_serving = upgrade_commands_for_mode("tool", tool, serves=False)

        assert len(serving) == len(not_serving) + 1
        assert any(CU130_INDEX_STRATEGY in command for command in serving)
        assert not_serving == durable_upgrade_commands()
        assert not any(CU130_INDEX_STRATEGY in command for command in not_serving)


@pytest.mark.usefixtures("isolated_status_dir")
class TestTheDoctorVerbFromALauncherThatCannotServe:
    """The whole verb, from the launcher the reports were wrong about."""

    @pytest.mark.torch
    def test_it_offers_the_start_rather_than_a_torch_repair(
        self, cpu_tool: SeparateInstallation, tmp_path: Path
    ) -> None:
        """Guard assertion: a repair command for an environment nothing runs in.

        A CPU-only launcher with no runtime is not a broken inference host:
        the service gets its own environment on the first start. Printing the
        wheel repair sends the operator to replace a torch the daemon will
        never load, and naming the launcher's capability reports a defect
        where there is none. The launcher is a tool environment, which is the
        one kind that has a repair to print.

        Mutation check: reporting the launching environment's own compute
        verdict prints its label and fails the second assertion. The repair
        assertion holds the other half: it catches a repair printer added
        back for an environment the daemon does not run in.
        """
        plain, structured = invoke_the_cli(
            cpu_tool,
            ["server", "doctor"],
            ["server", "doctor", "--json"],
            cwd=tmp_path,
        )
        envelope = json.loads(structured["stdout"])
        repair = cuda_remediation(envelope["data"]["interpreter"]).repair_commands

        assert envelope["data"]["interpreter"] == str(cpu_tool.interpreter)
        assert server_start_command() in plain["stdout"]
        assert ComputeCapability.CPU_ONLY_BUILD.label not in plain["stdout"]
        # The premise: this environment has a repair that could have been printed.
        assert repair
        for step in repair:
            assert step not in plain["stdout"]
        assert envelope["data"]["service_runtime"]["ready"] is False
        assert envelope["data"]["receipt"] is None
        # Nothing is running, which is not ready whatever the rows say.
        assert plain["exit_code"] != 0
        assert envelope["data"]["status"] == "not_running"
        assert envelope["data"]["next_action"] == server_start_command()

    @pytest.mark.torch
    def test_a_live_service_reads_ready_though_no_runtime_exists_yet(
        self,
        cpu_tool: SeparateInstallation,
        isolated_status_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Guard assertion: an environment nobody uses blocked the verdict.

        A project client beside a live, healthy host service was told
        "dependencies not ready" and exited 1, because the plan's own torch
        row - the runtime that does not exist yet, reported as unchecked -
        was folded into the top line. Nothing about the service answering
        requests was untrue; a start from here would have attached to it.

        The service is the real route table, served from this process and
        published through the real discovery writer.

        Mutation check: folding the dependency rows in under a runtime plan
        reads this as ``dependencies_not_ready`` and fails the status and
        exit-code assertions; the service runtime axis still reports the
        absent runtime, which the last assertion holds.
        """
        with _production_service(isolated_status_dir):
            (result,) = invoke_the_cli(
                cpu_tool,
                ["--target", str(tmp_path), "server", "doctor", "--json"],
                cwd=tmp_path,
            )

        envelope = json.loads(result["stdout"])
        assert envelope["data"]["status"] == "ready"
        assert envelope["data"]["ready"] is True
        assert result["exit_code"] == 0
        assert envelope["data"]["service_runtime"]["ready"] is False


@pytest.mark.usefixtures("isolated_status_dir")
class TestWhatStatusSaysAboutTheInterpreter:
    """``status`` names the next action and the interpreter a start would use."""

    @pytest.mark.torch
    @pytest.mark.parametrize("launcher", ["serving_tool", "cpu_tool"])
    def test_the_next_action_is_the_start_under_every_plan(
        self, request: pytest.FixtureRequest, launcher: str, tmp_path: Path
    ) -> None:
        """Nothing about where the daemon would run changes the next action."""
        installation: SeparateInstallation = request.getfixturevalue(launcher)
        project = _workspace(tmp_path)

        (result,) = invoke_the_cli(
            installation, ["--target", str(project), "status"], cwd=project
        )

        assert result["exit_code"] == 0, result["stdout"]
        assert "Next action:" in result["stdout"]
        assert result["stdout"].rstrip().endswith(server_start_command())

    @pytest.mark.torch
    def test_a_receipt_is_named_only_when_this_installation_serves(
        self, serving_tool: SeparateInstallation, cpu_tool: SeparateInstallation
    ) -> None:
        """Guard assertion: no torch repair for a launcher nothing runs in.

        The fix keeps this installation's GPU build across an upgrade, which
        a service running from its own environment does not use. Both
        installations are uv tool environments with a receipt that names no
        CUDA source; only one holds a torch the daemon could run from.
        Mutation check: dropping the plan from the line prints the fix for the
        second case and fails the last assertion.
        """
        serving = _receipt_lines_of(serving_tool)
        not_serving = _receipt_lines_of(cpu_tool)

        assert any("Fix, in order:" in line for line in serving)
        assert not_serving == []

    @pytest.mark.torch
    def test_the_note_says_a_runtime_would_be_created(
        self,
        cpu_tool: SeparateInstallation,
        isolated_status_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Guard assertion: the note named an interpreter that would not serve.

        A running service from another interpreter is explained by saying
        what a start from here would use, and from a launcher that cannot
        serve that is not this interpreter at all. The service is the real
        route table, run by this process, so it reports the interpreter this
        process runs from, which is not the launcher's. Mutation check:
        naming the local interpreter again fails the second assertion.
        """
        project = _workspace(tmp_path)

        with _production_service(isolated_status_dir):
            (result,) = invoke_the_cli(
                cpu_tool, ["--target", str(project), "status"], cwd=project
            )

        assert f"the running service uses {sys.executable}" in result["stdout"]
        assert "would create its own environment to run in first" in result["stdout"]


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

    def test_a_launcher_that_cannot_serve_follows_the_machines_accelerator(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: a runtime has still to be built, and for what?

        A launcher that cannot serve still chooses server mode when this
        machine has an accelerator a runtime built here could use, and
        records nothing, naming the machine, when it has none. The question
        is about the machine and not the environment in front of it, so each
        runner proves the branch its own hardware implies: a workstation the
        first, a runner with no accelerator the second.

        Mutation check, on a workstation: answering a missing runtime as
        unservable regardless of the hardware records nothing and fails the
        first branch. The other branch is the mirror, and fails on a runner
        with no accelerator when a missing runtime is answered as servable.
        """
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")
        presence = read_hardware().presence

        saved = save_backend_choice(
            self._Run(tmp_path),
            ProvisionOutcome(),
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD),
        )

        if presence.supports_the_service:
            assert saved.saved is True
            assert saved.local_only is False
            assert "cannot run the service" not in saved.detail
        else:
            assert saved.saved is False
            assert presence.label in saved.detail
            assert "this environment cannot run the service" not in saved.detail

    @pytest.mark.torch
    def test_a_runtime_that_cannot_serve_is_named_as_the_services_own(
        self, tmp_path: Path
    ) -> None:
        """The remaining refusal is about the service, not the installation.

        A published runtime that cannot run the service is the one case left
        in which no backend is chosen, and the sentence says so of the
        service rather than of the environment the operator installed. The
        runtime here is a real environment holding the CPU build of torch,
        which its own interpreter reports.
        """
        interpreter = _interpreter_in(tmp_path / "project" / ".venv")
        publish_runtime(cpu_torch=True)

        saved = save_backend_choice(
            self._Run(tmp_path),
            ProvisionOutcome(),
            _launching(interpreter, ComputeCapability.CPU_ONLY_BUILD),
        )

        assert saved.saved is False
        assert "the service has no environment that can run it yet" in saved.detail
        assert ComputeCapability.CPU_ONLY_BUILD.label in saved.detail
        assert "this environment cannot run the service" not in saved.detail
