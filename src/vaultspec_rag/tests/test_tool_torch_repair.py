"""Safety contracts for durable CUDA repair in persistent tool environments."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest
from pytest import MonkeyPatch

from ..commands import _tool_torch
from ..operator_state import _environment_probe, _provisioning
from ..operator_state._compute import ProbeDepth
from ..operator_state._environment_probe import InterpreterFacts
from ..operator_state._installation import ComputeCapability, InstallRole
from ..operator_state._models import ComputeReport
from ..operator_state._provisioning import ToolReceiptVerdict
from ..operator_state._topology import RuntimeEnvKind

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path


def _persistent_tool_env(_root: object) -> RuntimeEnvKind:
    return RuntimeEnvKind.UV_TOOL


def _durable_receipt(_interpreter: str) -> ToolReceiptVerdict:
    return ToolReceiptVerdict.DURABLE


def _no_cuda_receipt(_interpreter: str) -> ToolReceiptVerdict:
    return ToolReceiptVerdict.NO_CUDA_SOURCE


def _remediation_for(interpreter: str) -> _provisioning.CudaRemediation:
    """The remediation a tool environment is handed, built where all are."""
    return _provisioning.cuda_remediation(interpreter, env_kind=RuntimeEnvKind.UV_TOOL)


def _need(capability: ComputeCapability) -> _tool_torch._RepairNeed:
    """The assessed need a defective tool environment produces."""
    return _tool_torch._RepairNeed(
        capability=capability,
        receipt=ToolReceiptVerdict.NO_CUDA_SOURCE,
        reason=capability.label,
    )


def _probe_answering(capability: ComputeCapability):
    """A probe double that reports *capability* for any interpreter."""

    def probe(
        interpreter: str,
        depth: ProbeDepth = ProbeDepth.METADATA,
        *,
        timeout: float | None = None,
    ) -> InterpreterFacts:
        del depth, timeout
        return InterpreterFacts(
            interpreter=interpreter,
            role=(
                InstallRole.CLIENT
                if capability is ComputeCapability.NOT_APPLICABLE
                else InstallRole.HOST
            ),
            mcp_adapter=True,
            executable=interpreter,
            prefix="",
            compute=ComputeReport(capability=capability),
        )

    return probe


@pytest.mark.parametrize(
    ("capability", "is_installation_defect"),
    [
        (ComputeCapability.TORCH_MISSING, True),
        (ComputeCapability.TORCH_IMPORT_FAILED, True),
        (ComputeCapability.CPU_ONLY_BUILD, True),
        (ComputeCapability.NO_DEVICE, False),
        (ComputeCapability.MPS_POLICY_REFUSED, False),
        (ComputeCapability.NOT_APPLICABLE, False),
    ],
)
def test_only_a_broken_torch_merits_a_reinstall(
    capability: ComputeCapability, *, is_installation_defect: bool
) -> None:
    """Only missing, unloadable or CPU-only torch is fixed by a new wheel."""
    assert capability.fixed_by_torch_reinstall is is_installation_defect


def test_a_non_interactive_run_reports_the_handoff_instead_of_stopping(
    tmp_path: Path,
) -> None:
    """No terminal is needed to be told what to run.

    The transaction used to demand confirmation for a replacement it performed;
    without a terminal it refused, which made a defective tool environment
    impossible to diagnose from a script. Nothing is replaced now, so nothing
    is asked, and the same report comes back either way.
    """
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()

    outcome = _tool_torch._repair_defective_tool(
        str(interpreter),
        _need(ComputeCapability.CPU_ONLY_BUILD),
        _tool_torch.ToolRepairRequest(),
    )

    assert outcome.action in {
        _tool_torch.ToolTorchRepairAction.HANDOFF_REQUIRED,
        _tool_torch.ToolTorchRepairAction.HOLDER_DETECTED,
    }
    assert "uv tool install" in outcome.command


def test_a_defective_tool_is_handed_off_rather_than_replaced(
    tmp_path: Path,
) -> None:
    """The transaction refuses and hands over the command; it never replaces.

    The environment being repaired is the one this process runs from, so any
    replacement issued here would have to remove the interpreter issuing it.
    The outcome therefore blocks the install and carries the command for a
    shell that holds nothing.
    """
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()

    outcome = _tool_torch._repair_defective_tool(
        str(interpreter),
        _need(ComputeCapability.CPU_ONLY_BUILD),
        _tool_torch.ToolRepairRequest(),
    )

    assert outcome.action in {
        _tool_torch.ToolTorchRepairAction.HANDOFF_REQUIRED,
        _tool_torch.ToolTorchRepairAction.HOLDER_DETECTED,
    }
    assert outcome.blocks_install
    assert "uv tool install" in outcome.command
    assert "tool CUDA repair for" in outcome.detail


def test_no_path_here_replaces_an_environment_wholesale() -> None:
    """Guard assertion: a wholesale replacement is what destroys a held env.

    The repair changes torch in place, which is why the product may run it at
    all. ``uv tool install --force`` rebuilds the environment instead,
    removing its contents first and leaving nothing runnable behind when a
    file cannot be removed - the field failure this cycle exists to end. The
    absence of that flag is asserted structurally, because a refusal that
    merely avoids it today is one refactor away from passing it again.
    """
    source = inspect.getsource(_tool_torch)

    assert "--force" not in source
    assert "--force" not in " ".join(
        _provisioning.tool_repair_arguments("/opt/env/bin/python")
    )
    assert "--force" not in " ".join(
        _provisioning.tool_repair_arguments("/opt/env/bin/python", upgrade=True)
    )


def test_nothing_is_installed_without_consent(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Guard assertion: the repair mutates the operator's environment.

    It is the one mutation this product performs on an environment it did not
    create, so a run that was never authorised must launch nothing at all -
    not uv, and not the command it would have been given.
    """

    def _refuse(*_args: object, **_kwargs: object) -> tuple[bool, str]:
        raise AssertionError("an unconsented repair must launch nothing")

    monkeypatch.setattr(_tool_torch, "_run_repair", _refuse)
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()

    outcome = _tool_torch._repair_defective_tool(
        str(interpreter),
        _need(ComputeCapability.CPU_ONLY_BUILD),
        _tool_torch.ToolRepairRequest(confirm=lambda _prompt: False),
    )

    assert outcome.blocks_install
    assert "declined at the prompt" in outcome.detail


def test_a_consented_repair_runs_and_is_verified_rather_than_assumed(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Guard assertion: uv exiting zero is not proof of a repaired host.

    uv rewrites the receipt and keeps an installed CPU torch that still
    satisfies the requirement, so a run that trusts the exit code reports a
    GPU host that cannot serve one request.
    """
    launched: list[str] = []

    def _ran(interpreter: str, *, stream: bool) -> tuple[bool, str]:
        del stream
        launched.append(interpreter)
        return True, "uv applied the repair"

    monkeypatch.setattr(_tool_torch, "_run_repair", _ran)
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_answering(ComputeCapability.CPU_ONLY_BUILD),
    )
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()

    outcome = _tool_torch._repair_defective_tool(
        str(interpreter),
        _need(ComputeCapability.CPU_ONLY_BUILD),
        _tool_torch.ToolRepairRequest(assume_yes=True),
    )

    assert launched == [str(interpreter)]
    assert outcome.action is _tool_torch.ToolTorchRepairAction.REPAIR_FAILED
    assert outcome.blocks_install
    assert ComputeCapability.CPU_ONLY_BUILD.label in outcome.detail


def test_a_repair_that_worked_is_reported_as_done(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A verified repair lets the install continue and says what it did."""

    def _ran(_interpreter: str, *, stream: bool) -> tuple[bool, str]:
        del stream
        return True, "uv applied the repair"

    monkeypatch.setattr(_tool_torch, "_run_repair", _ran)
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_answering(ComputeCapability.READY),
    )
    monkeypatch.setattr(_tool_torch, "classify_tool_receipt", _durable_receipt)
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()

    outcome = _tool_torch._repair_defective_tool(
        str(interpreter),
        _need(ComputeCapability.CPU_ONLY_BUILD),
        _tool_torch.ToolRepairRequest(assume_yes=True),
    )

    assert outcome.action is _tool_torch.ToolTorchRepairAction.REPAIRED
    assert not outcome.blocks_install
    assert outcome.receipt is ToolReceiptVerdict.DURABLE


def test_a_working_torch_with_a_receipt_that_will_lose_it_needs_the_repair(
    monkeypatch: MonkeyPatch,
) -> None:
    """Guard assertion: this host breaks itself at the next upgrade.

    Its torch is a GPU build today and its receipt records no CUDA source, so
    the first ``uv tool upgrade`` resolves a CPU wheel over it with nobody
    present. An install that reads only the build walks past that.
    """
    monkeypatch.setattr(_tool_torch, "classify_environment", _persistent_tool_env)
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_answering(ComputeCapability.READY),
    )
    monkeypatch.setattr(_tool_torch, "classify_tool_receipt", _no_cuda_receipt)

    assessed = _tool_torch._assess("ignored")

    assert isinstance(assessed, _tool_torch._RepairNeed)
    assert assessed.capability is ComputeCapability.READY
    assert ToolReceiptVerdict.NO_CUDA_SOURCE.label in assessed.reason


def test_cuda_build_without_a_visible_device_never_reinstalls(
    monkeypatch: MonkeyPatch,
) -> None:
    """A driver/device problem is diagnostic, not a reason to rewrite the tool."""
    monkeypatch.setattr(_tool_torch, "classify_environment", _persistent_tool_env)
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_answering(ComputeCapability.NO_DEVICE),
    )

    def _unexpected_repair(
        *_args: object, **_kwargs: object
    ) -> _tool_torch.ToolTorchRepairOutcome:
        raise AssertionError("a CUDA build without a device must not be reinstalled")

    monkeypatch.setattr(_tool_torch, "_repair_defective_tool", _unexpected_repair)

    outcome = _tool_torch.repair_tool_torch(
        _tool_torch.ToolRepairRequest(interpreter="ignored")
    )

    assert outcome.action is _tool_torch.ToolTorchRepairAction.CUDA_UNVERIFIED
    assert outcome.blocks_install


def test_the_repair_keeps_the_recorded_extras_and_pins_nothing(
    tmp_path: Path,
) -> None:
    """A repair asks for the tool it found, with no version and no new extras.

    Guard assertion: a bare package name imposes this build's extras on an
    operator who chose otherwise, and a version pin stops every later upgrade
    from resolving at all - which is what the previous repair did.
    """
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()
    (tmp_path / "uv-receipt.toml").write_text(
        """[tool]
requirements = [{ name = "vaultspec-rag", extras = ["mcp"] }]
""",
        encoding="utf-8",
    )

    requirement = _provisioning.tool_package_requirement(str(interpreter))

    assert requirement == "vaultspec-rag[mcp]"
    assert "gpu" not in requirement


def test_a_receipt_without_the_package_falls_back_to_the_host_request(
    tmp_path: Path,
) -> None:
    """An environment recording nothing gets the inference host's request.

    Guard assertion: the MCP adapter's launch spec carries only ``mcp``, so a
    repair request built from it would drop the inference stack the repaired
    torch serves. Pinned to a literal so the fallback cannot follow that spec.
    """
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()

    assert (
        _provisioning.tool_package_requirement(str(interpreter))
        == "vaultspec-rag[gpu,mcp]"
    )


def test_a_handoff_is_visible_without_json(capsys: pytest.CaptureFixture[str]) -> None:
    """The operator sees the refusal, the holders and the command in plain output.

    Guard assertion: this outcome used to reach `--json` only, so an operator
    running the install normally was told nothing at all about an environment
    that cannot run the GPU stack.
    """
    from ..cli._render import _render_tool_torch_repair

    outcome = _tool_torch.ToolTorchRepairOutcome(
        _tool_torch.ToolTorchRepairAction.HOLDER_DETECTED,
        "tool CUDA repair for C:/tools/vaultspec-rag"
        + chr(10)
        + "  running out of it now, and unchanged until restarted:"
        + chr(10)
        + "    pid 4321 (end this process): C:/tools/vaultspec-rag/Scripts/python.exe",
        "uv tool install ... --upgrade-package torch",
        steps=(
            "Install the CUDA build of torch into this environment: "
            "uv tool install ... --upgrade-package torch",
        ),
    )

    _render_tool_torch_repair(outcome)

    printed = capsys.readouterr().out
    assert "Tool environment needs a CUDA repair" in printed
    assert "pid 4321" in printed
    assert "uv tool install ... --upgrade-package torch" in printed


def test_a_healthy_tool_environment_prints_no_repair_section(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An install with no tool problem does not grow a section saying so."""
    from ..cli._render import _render_tool_torch_repair

    _render_tool_torch_repair(
        _tool_torch.ToolTorchRepairOutcome(
            _tool_torch.ToolTorchRepairAction.ALREADY_READY, "fine", ""
        )
    )
    _render_tool_torch_repair(None)

    assert capsys.readouterr().out == ""


def test_the_install_report_itself_carries_the_repair_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The section reaches plain install output, not just the helper.

    Guard assertion: the defect this closes was a renderer that never read
    `tool_torch_repair` at all, so proving the helper works in isolation
    proves nothing about what an operator sees. This renders the whole report.
    """
    from ..cli._render import _render_install_report
    from ..commands._models import InstallReport

    report = InstallReport(action="install", target=tmp_path)
    report.tool_torch_repair = _tool_torch.ToolTorchRepairOutcome(
        _tool_torch.ToolTorchRepairAction.HANDOFF_REQUIRED,
        "tool CUDA repair for " + str(tmp_path),
        "uv tool install ... --upgrade-package torch",
        steps=(
            "Install the CUDA build of torch into this environment: "
            "uv tool install ... --upgrade-package torch",
        ),
    )

    _render_install_report(report)

    printed = capsys.readouterr().out
    assert "Tool environment needs a CUDA repair" in printed
    assert "uv tool install ... --upgrade-package torch" in printed


def test_a_healthy_tool_interpreter_needs_no_repair(monkeypatch: MonkeyPatch) -> None:
    """A CUDA-ready environment with a durable receipt ends the transaction."""
    monkeypatch.setattr(_tool_torch, "classify_environment", _persistent_tool_env)
    monkeypatch.setattr(_tool_torch, "classify_tool_receipt", _durable_receipt)
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_answering(ComputeCapability.READY),
    )

    outcome = _tool_torch.repair_tool_torch(
        _tool_torch.ToolRepairRequest(interpreter="ignored")
    )

    assert outcome.action is _tool_torch.ToolTorchRepairAction.ALREADY_READY
    assert not outcome.blocks_install


def test_a_project_venv_is_not_this_transaction_s_business(
    monkeypatch: MonkeyPatch,
) -> None:
    """Only a persistent tool environment is repaired through this path."""

    def _project_venv(_root: object) -> RuntimeEnvKind:
        return RuntimeEnvKind.PROJECT_VENV

    monkeypatch.setattr(_tool_torch, "classify_environment", _project_venv)

    outcome = _tool_torch.repair_tool_torch(
        _tool_torch.ToolRepairRequest(interpreter="ignored")
    )

    assert outcome.action is _tool_torch.ToolTorchRepairAction.NOT_APPLICABLE
    assert not outcome.blocks_install


def test_a_dry_run_previews_the_command_without_inspecting_holders(
    tmp_path: Path,
) -> None:
    """A preview names what is needed and why, and stops there."""
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()

    outcome = _tool_torch._repair_defective_tool(
        str(interpreter),
        _need(ComputeCapability.CPU_ONLY_BUILD),
        _tool_torch.ToolRepairRequest(dry_run=True),
    )

    assert outcome.action is _tool_torch.ToolTorchRepairAction.DRY_RUN
    assert ComputeCapability.CPU_ONLY_BUILD.label in outcome.detail
    assert "uv tool install" in outcome.command
    assert outcome.holders == ()


@pytest.mark.parametrize(
    "action",
    [
        _tool_torch.ToolTorchRepairAction.HOLDER_DETECTED,
        _tool_torch.ToolTorchRepairAction.HANDOFF_REQUIRED,
        _tool_torch.ToolTorchRepairAction.CUDA_UNVERIFIED,
    ],
)
def test_every_unresolved_outcome_stops_the_install(
    action: _tool_torch.ToolTorchRepairAction,
) -> None:
    """An environment that cannot run the stack is never installed over.

    Guard assertion: continuing past any of these would leave the operator with
    a completed install on top of an environment that cannot serve a request.
    """
    outcome = _tool_torch.ToolTorchRepairOutcome(action, "detail", "command")

    assert outcome.blocks_install


@pytest.mark.parametrize(
    "action",
    [
        _tool_torch.ToolTorchRepairAction.NOT_APPLICABLE,
        _tool_torch.ToolTorchRepairAction.ALREADY_READY,
        _tool_torch.ToolTorchRepairAction.DRY_RUN,
    ],
)
def test_a_resolved_outcome_lets_the_install_continue(
    action: _tool_torch.ToolTorchRepairAction,
) -> None:
    """Nothing to repair, or nothing asked for, does not block the install."""
    outcome = _tool_torch.ToolTorchRepairOutcome(action, "detail", "command")

    assert not outcome.blocks_install


def test_a_real_holder_is_named_in_the_refusal(tmp_path: Path) -> None:
    """A live process in the environment is reported, with its pid and relation.

    Real environment, real holder: the refusal an operator reads has to name
    the process they must actually end, not merely state that one exists.
    """
    from ._uv_env_harness import (
        build_wheel,
        hold_environment,
        index_arguments,
        sandbox_from,
        serve_wheels,
    )

    sandbox = sandbox_from(tmp_path)
    wheels = tmp_path / "wheels"
    build_wheel(wheels, name="provtool", version="1.0.0")
    with serve_wheels(wheels) as base_url:
        installed = sandbox.run(
            "tool", "install", "provtool", *index_arguments(base_url)
        )
        assert installed.returncode == 0, installed.stderr

    root = sandbox.tool_root("provtool")
    interpreter = root / "Scripts" / "python.exe"
    if not interpreter.exists():
        interpreter = root / "bin" / "python"

    with hold_environment(root, by_image=True) as holder:
        outcome = _tool_torch._handoff_outcome(
            str(interpreter), _remediation_for(str(interpreter))
        )

    assert outcome.action is _tool_torch.ToolTorchRepairAction.HOLDER_DETECTED
    # A venv interpreter is a launcher that re-executes the real one, so the
    # pid Popen returned may be reported as the paired launcher rather than as
    # the entry itself.
    assert any(
        holder.pid in {found.pid, found.launcher_pid} for found in outcome.holders
    )
    assert f"pid {holder.pid}" in outcome.detail
    assert "end this process" in outcome.detail
    assert outcome.blocks_install


def test_an_install_without_the_gpu_extra_is_not_a_defect(
    monkeypatch: MonkeyPatch,
) -> None:
    """A deliberately torch-free install completes instead of failing.

    Guard assertion: absence of torch used to classify as an installation
    defect, whose blocking outcome short-circuited the whole install to exit 2.
    That made the torch-free install this project deliberately offers
    impossible to complete without a terminal - a defect introduced by reading
    a choice as a fault.
    """
    monkeypatch.setattr(_tool_torch, "classify_environment", _persistent_tool_env)
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_answering(ComputeCapability.NOT_APPLICABLE),
    )

    outcome = _tool_torch.repair_tool_torch(
        _tool_torch.ToolRepairRequest(interpreter="ignored")
    )

    assert outcome.action is _tool_torch.ToolTorchRepairAction.NOT_APPLICABLE
    assert not outcome.blocks_install
    assert "GPU extra" in outcome.detail


def test_torch_missing_from_a_gpu_install_is_still_a_defect() -> None:
    """The half-destroyed environment keeps its defect classification.

    Torch missing beside the GPU stack means an install that asked for torch
    lost it, which is what an interrupted replacement leaves behind - the field
    failure. It must not be softened by the by-design branch beside it.
    """
    missing = ComputeCapability.TORCH_MISSING

    assert missing.fixed_by_torch_reinstall
    assert missing.is_defect


def test_the_environment_root_is_the_environment_not_the_link_target(
    tmp_path: Path,
) -> None:
    """A symlinked interpreter names its OWN environment, not the base one.

    Guard assertion: a tool environment's interpreter is a symlink to the base
    interpreter on POSIX. Resolving it yields the shared Python installation,
    and everything derived from the root then describes that installation
    instead - the directory the operator is told to leave, the environment
    scanned for holders, and the receipt looked up. This is the same symlink
    trap that made the holder query blind to every POSIX virtual environment.
    """
    env = tmp_path / "tool-env"
    (env / "bin").mkdir(parents=True)
    base = tmp_path / "base" / "bin"
    base.mkdir(parents=True)
    base_python = base / "python3.14"
    base_python.write_text("", encoding="utf-8")
    interpreter = env / "bin" / "python"
    try:
        interpreter.symlink_to(base_python)
    except (OSError, NotImplementedError):  # pragma: no cover - needs privilege
        pytest.skip("this platform does not allow creating a symlink here")

    assert _provisioning.environment_root(str(interpreter)) == env
    assert _provisioning.environment_root(str(interpreter)) != base.parent


def _process_table(*rows: dict[str, object]):
    """An ``iter_process_info`` stand-in yielding *rows*."""

    def scan(attrs: list[str]) -> Iterator[Mapping[str, object]]:
        del attrs
        yield from rows

    return scan


def _holder_row(
    pid: int, image: str | None, argv: list[str] | None = None
) -> dict[str, object]:
    return {"pid": pid, "ppid": None, "exe": image, "cwd": None, "cmdline": argv}


def _refusal_detail(tmp_path: Path) -> str:
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir(exist_ok=True)
    return _tool_torch._handoff_outcome(
        str(interpreter), _remediation_for(str(interpreter))
    ).detail


def test_the_refusal_names_what_each_holder_is_and_how_to_clear_it(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A pid and an image path do not tell an operator what to do.

    Guard assertion: the list showed the image path alone, which is the same
    interpreter for every process in one environment - so the service, an
    assistant's stdio adapter and a stranger's script were three identical
    lines, and the remediation for all three was "end this process".
    """
    image = str(tmp_path / "Scripts" / "python.exe")
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.iter_process_info",
        _process_table(
            _holder_row(
                701,
                image,
                [image, "-m", "vaultspec_rag.server", "--port", "8776"],
            ),
            _holder_row(702, image, [image, "-m", "vaultspec_rag.server"]),
            _holder_row(703, image, [image, "-c", "import time; time.sleep(9)"]),
        ),
    )

    detail = _refusal_detail(tmp_path)

    assert "vaultspec-rag service on port 8776" in detail
    assert "vaultspec-rag server stop --port 8776" in detail
    assert "MCP stdio adapter" in detail
    assert "close the editor or agent session that started it" in detail
    assert "end this process" in detail
    # The command line is what tells the three apart; the image cannot.
    assert "-m vaultspec_rag.server" in detail


def test_the_refusal_counts_the_processes_it_could_not_inspect(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A count is actionable; "some processes" is not.

    Guard assertion: one protected system process and a table belonging to
    another user produced the same sentence, and they are different answers
    to "is this list the whole story".
    """
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.iter_process_info",
        _process_table(_holder_row(801, None)),
    )

    detail = _refusal_detail(tmp_path)

    assert "1 process could not be inspected" in detail
    assert "some processes could not be inspected" not in detail
