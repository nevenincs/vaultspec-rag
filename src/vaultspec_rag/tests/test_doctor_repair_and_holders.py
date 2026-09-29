"""``server doctor`` answers about the environment that would run the service.

Two defects this covers. The compute capability's own remediation tells an
operator that this command prints the exact repair, and ``status`` renders
that sentence, while the command printed only the capability label. And the
holder scan ran over the CLI's own environment while the compute verdict
beside it described the daemon interpreter's, so the two halves of one block
could be about two different environments - and neither reached the output.

The interpreter probe is doubled: it starts a child interpreter and imports
torch in it, which cannot be made to report a CPU-only build on a GPU host.
Everything else is the real verb.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from .._process_probe import EnvironmentHolder, EnvironmentHolders, HolderRelation
from ..cli import _service_doctor as doctor
from ..cli import app
from ..operator_state import _environment_probe
from ..operator_state._compute import ProbeDepth
from ..operator_state._environment_probe import InterpreterFacts
from ..operator_state._holders import HolderRole
from ..operator_state._installation import ComputeCapability, InstallRole
from ..operator_state._models import ComputeReport
from ..operator_state._provisioning import (
    CU130_INDEX_STRATEGY,
    ToolReceiptVerdict,
    classify_tool_receipt,
    cuda_remediation,
)
from ..operator_state._topology import TOOL_RECEIPT_NAME
from ..torch_config._index import CU130_INDEX_URL

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def _probe_reporting(capability: ComputeCapability):
    """A daemon-interpreter probe double reporting *capability*."""

    def probe(
        interpreter: str,
        depth: ProbeDepth = ProbeDepth.METADATA,
        *,
        timeout: float | None = None,
    ) -> InterpreterFacts:
        del depth, timeout
        return InterpreterFacts(
            interpreter=interpreter,
            role=InstallRole.HOST,
            mcp_adapter=False,
            executable=interpreter,
            prefix="",
            compute=ComputeReport(capability=capability),
        )

    return probe


def _daemon_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, receipt: str | None = None
) -> Path:
    """Point the daemon interpreter at a tool environment under *tmp_path*."""
    root = tmp_path / "service-env"
    (root / "Scripts").mkdir(parents=True)
    interpreter = root / "Scripts" / "python.exe"
    interpreter.touch()
    if receipt is not None:
        (root / TOOL_RECEIPT_NAME).write_text(receipt, encoding="utf-8")

    def _daemon() -> str:
        return str(interpreter)

    monkeypatch.setattr(doctor, "_resolve_daemon_interpreter", _daemon)
    return root


def _recording_scan(seen: list[str], holders: tuple[EnvironmentHolder, ...] = ()):
    """A holder-scan double recording the root it was asked about."""

    def scan(
        root: object,
        *,
        exclude_pids: object = (),
        exclude_launch_chain: bool = False,
        timeout: float | None = None,
    ) -> EnvironmentHolders:
        del exclude_pids, timeout
        from pathlib import Path as _Path

        seen.append(str(root))
        return EnvironmentHolders(
            root=_Path(str(root)),
            holders=holders,
            uninspectable=0,
            complete=True,
            self_held=exclude_launch_chain,
        )

    return scan


def test_a_device_problem_has_no_provisioning_repair_to_print() -> None:
    """Only a defect a new wheel fixes gets a provisioning command.

    Guard assertion: printing the tool repair for a missing device tells an
    operator to reinstall torch over a driver fault it cannot touch.
    """
    assert doctor._compute_repair_steps("python", ComputeCapability.NO_DEVICE) == []
    assert doctor._compute_repair_steps(
        "python", ComputeCapability.CPU_ONLY_BUILD
    ) == list(cuda_remediation("python").steps)


def test_doctor_prints_the_exact_repair_for_a_cpu_only_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command the capability's remediation promises is actually printed.

    Guard assertion: `ComputeCapability.CPU_ONLY_BUILD.remediation` sends the
    operator here for the exact command, and status renders that sentence, so
    a doctor that prints only the label is a dead end.
    """
    root = _daemon_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_reporting(ComputeCapability.CPU_ONLY_BUILD),
    )
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.environment_holders", _recording_scan([])
    )
    expected = cuda_remediation(str(root / "Scripts" / "python.exe"))

    result = runner.invoke(app, ["server", "doctor"])

    for command in expected.repair_commands:
        assert command in result.stdout


def test_doctor_scans_the_daemon_environment_not_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The holders reported belong to the environment the verdict is about.

    Guard assertion: the scan read this command's own prefix while the
    compute verdict beside it described the daemon interpreter, so on any
    host where the two differ the block described two environments at once.
    """
    root = _daemon_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_reporting(ComputeCapability.READY),
    )
    seen: list[str] = []
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.environment_holders", _recording_scan(seen)
    )

    runner.invoke(app, ["server", "doctor"])

    assert seen == [str(root)]


def test_doctor_reports_the_holders_in_both_output_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan nobody can read is a scan not worth paying for.

    Guard assertion: the verb ran the process-table walk and then neither
    rendered it nor put it in the envelope.
    """
    _daemon_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_reporting(ComputeCapability.READY),
    )
    holder = EnvironmentHolder(
        pid=4321,
        relation=HolderRelation.IMAGE,
        image="python.exe",
        working_directory=None,
        argv=("python.exe", "-m", "vaultspec_rag.server", "--port", "8776"),
        launcher_pid=4320,
    )
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.environment_holders",
        _recording_scan([], (holder,)),
    )

    human = runner.invoke(app, ["server", "doctor"])
    envelope = json.loads(runner.invoke(app, ["server", "doctor", "--json"]).stdout)

    assert "pid 4321" in human.stdout
    assert "vaultspec-rag service on port 8776" in human.stdout
    assert "vaultspec-rag server stop --port 8776" in human.stdout
    assert "with its launcher, pid 4320" in human.stdout
    reported = envelope["data"]["environment_holders"]
    assert reported["holders"][0]["pid"] == 4321
    assert reported["holders"][0]["role"] == "service"
    assert reported["holders"][0]["port"] == 8776
    # An argument vector reaches an HTTP route through this snapshot.
    assert "cmdline" not in reported["holders"][0]


def test_doctor_reports_what_the_next_upgrade_would_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GPU host whose receipt records no CUDA source is told so now.

    Guard assertion: such an installation runs perfectly until an upgrade
    nobody supervises resolves a CPU build over it, and every surface
    reported only the build in front of it.
    """
    root = _daemon_environment(
        tmp_path,
        monkeypatch,
        receipt='[tool]\nrequirements = [{ name = "vaultspec-rag" }]\n',
    )
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_reporting(ComputeCapability.READY),
    )
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.environment_holders", _recording_scan([])
    )
    expected = classify_tool_receipt(str(root / "Scripts" / "python.exe"))

    human = runner.invoke(app, ["server", "doctor"])
    envelope = json.loads(runner.invoke(app, ["server", "doctor", "--json"]).stdout)

    assert expected is ToolReceiptVerdict.NO_CUDA_SOURCE
    # The label is prose and wraps at the console width; the command is
    # soft-wrapped, because a folded command cannot be pasted.
    assert "Installation receipt:" in human.stdout
    assert expected.label.split(",")[0] in human.stdout
    assert "--index-strategy unsafe-first-match" in human.stdout
    reported = envelope["data"]["receipt"]
    assert reported["verdict"] == "no_cuda_source"
    assert reported["durable"] is False
    # A list, in order, beside the other command fields: running only the
    # visible step leaves a receipt the next upgrade resolves back to CPU.
    assert reported["fix"] == list(
        classify_tool_receipt(str(root / "Scripts" / "python.exe")).fix(
            str(root / "Scripts" / "python.exe")
        )
    )
    assert len(reported["fix"]) == 2
    assert "in order" in human.stdout


def test_doctor_says_nothing_about_a_receipt_a_durable_one_has(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An installation that will keep its GPU build needs no line at all."""
    _daemon_environment(
        tmp_path,
        monkeypatch,
        receipt=(
            '[tool]\nrequirements = [{ name = "vaultspec-rag" }]\n\n'
            "[tool.options]\n"
            f'index = [{{ url = "{CU130_INDEX_URL}" }}]\n'
            f'index-strategy = "{CU130_INDEX_STRATEGY}"\n'
        ),
    )
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_reporting(ComputeCapability.READY),
    )
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.environment_holders", _recording_scan([])
    )

    human = runner.invoke(app, ["server", "doctor"])
    envelope = json.loads(runner.invoke(app, ["server", "doctor", "--json"]).stdout)

    assert envelope["data"]["receipt"]["durable"] is True
    assert envelope["data"]["receipt"]["fix"] == []
    assert "make upgrades keep the GPU build" not in human.stdout


def test_a_capped_holder_list_says_how_many_it_did_not_show(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ten of twelve holders with no total reads as the whole story.

    Guard assertion: an operator clearing the list would think they had
    finished, and the repair would still be blocked by the two they never
    saw.
    """
    _daemon_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_reporting(ComputeCapability.READY),
    )
    holders = tuple(
        EnvironmentHolder(
            pid=5000 + index,
            relation=HolderRelation.IMAGE,
            image="python.exe",
            working_directory=None,
            argv=("python.exe", "-c", "pass"),
        )
        for index in range(12)
    )
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.environment_holders",
        _recording_scan([], holders),
    )

    human = runner.invoke(app, ["server", "doctor"])
    envelope = json.loads(runner.invoke(app, ["server", "doctor", "--json"]).stdout)

    assert "... and 2 more" in human.stdout
    assert envelope["data"]["environment_holders"]["total"] == 12
    assert len(envelope["data"]["environment_holders"]["holders"]) == 10


def test_a_role_this_build_does_not_know_still_renders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A snapshot from another release must not break the whole block.

    Guard assertion: constructing the enum from a reported string raises on
    a member this build has never heard of, and the holder is still a
    process someone has to deal with.
    """
    _daemon_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_reporting(ComputeCapability.READY),
    )
    monkeypatch.setattr(
        "vaultspec_rag._process_probe.environment_holders",
        _recording_scan(
            [],
            (
                EnvironmentHolder(
                    pid=6001,
                    relation=HolderRelation.IMAGE,
                    image="python.exe",
                    working_directory=None,
                    argv=("python.exe",),
                ),
            ),
        ),
    )

    def _future_role(_holder: object) -> str:
        return "a-role-from-the-future"

    monkeypatch.setattr(
        "vaultspec_rag.operator_state._holders.holder_role", _future_role
    )

    human = runner.invoke(app, ["server", "doctor"])

    assert "pid 6001" in human.stdout
    assert HolderRole.UNRECOGNISED.label in human.stdout
