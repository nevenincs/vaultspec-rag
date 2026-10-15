"""Every install and start message states one cause and offers one command.

A clean-machine lab found the opposite: one failing start printed a warning
about a state that was not present, a command naming a cache environment uv
owns, two mutually exclusive interpreter requests, a project repair for an
environment with no project, and the same accelerator cause three times, once
nested inside the next. These tests hold each of those lines absent and assert
what is said instead.

Nothing is substituted here. The capability labels and remediations are read
directly and the install report is rendered through its own renderer. What
depends on the environment an installation runs from is run in a fresh
interpreter of a separate installation of this package, inside an environment
of its own that is, or is not, a uv tool environment. The accelerator
classification runs against this host's real torch, which is made to report no
device, or a diagnosis of its own, by the same environment variables an
operator would set.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .._gpu import ACCELERATOR_REQUIRED_MESSAGE
from ..operator_state._installation import ComputeCapability
from ..torch_config._constants import TorchConfigAction
from ._real_environments import as_a_tool_environment
from ._separate_installation import SeparateInstallation, build_installation
from .conftest import managed_env

if TYPE_CHECKING:
    from ..commands._models import InstallReport

pytestmark = [pytest.mark.unit]


def _rendered(report: InstallReport, capsys: pytest.CaptureFixture[str]) -> str:
    """The install report as an operator reads it, from the CLI's own console."""
    from ..cli._render import _render_install_report

    capsys.readouterr()
    _render_install_report(report)
    return capsys.readouterr().out


class TestAnInstallWithNoProjectSaysNothingAboutOne:
    """A tool or pip installation has no project declaration, by design."""

    def test_no_torch_section_and_no_missing_declaration_warning(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Guard assertion: both lines described a state that is normal.

        The report said "PyTorch configuration: not found" and warned that
        there was no pyproject.toml at the target, for an installation that
        never has one. Mutation check: printing the line for an ``absent``
        action again fails the first assertion.
        """
        from ..commands._models import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.ABSENT,
        )

        out = _rendered(report, capsys)

        assert "PyTorch configuration" not in out
        assert "pyproject.toml" not in out
        assert "not found" not in out

    def test_a_real_configuration_is_still_reported(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The line is suppressed for one action, not removed."""
        from ..commands._models import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.ALREADY,
        )

        assert "PyTorch configuration" in _rendered(report, capsys)


#: Reports which kind of environment the interpreter runs from, and whether a
#: project's torch configuration applies to it.
_TORCH_CONFIGURATION_APPLIES = """
import json
import pathlib
import sys

from vaultspec_rag.commands._provision import torch_configuration_is_reportable
from vaultspec_rag.operator_state._topology import (
    classify_environment,
    environment_root,
)

target = pathlib.Path(json.loads(sys.argv[1])[0])
print(json.dumps({
    "kind": classify_environment(environment_root(sys.executable)).value,
    "reportable": torch_configuration_is_reportable(target, set()),
}))
"""

#: Runs the install's torch step in a project directory and renders the report.
_RUN_THE_TORCH_STEP = """
import contextlib
import io
import json
import pathlib
import sys

from vaultspec_rag.cli._render import _render_install_report
from vaultspec_rag.commands._models import InstallReport
from vaultspec_rag.commands._torch_flow import (
    TorchInstallOptions,
    _run_torch_config_install,
)
from vaultspec_rag.operator_state._compute import installed_role
from vaultspec_rag.operator_state._topology import (
    classify_environment,
    environment_root,
)

target = pathlib.Path(json.loads(sys.argv[1])[0])
report = InstallReport(action="install", target=target)
_run_torch_config_install(
    target=target,
    report=report,
    options=TorchInstallOptions(
        dry_run=False,
        configure_torch=True,
        assume_yes=True,
        sync_after=False,
        confirm=None,
    ),
)
rendered = io.StringIO()
with contextlib.redirect_stdout(rendered):
    _render_install_report(report)
print(json.dumps({
    "kind": classify_environment(environment_root(sys.executable)).value,
    "role": installed_role()[0].value,
    "action": report.torch_config_action.value,
    "rendered": rendered.getvalue(),
}))
"""


def _installation(directory: Path, *, tool: bool) -> SeparateInstallation:
    """A separate installation of this package in an environment of its own.

    The environment is a uv tool environment when *tool* is set, which is what
    uv itself makes one by: its receipt at the environment's root. Which kind
    of environment the suite runs from is a property of the runner, and both
    answers have to be reached, so neither is taken from this process.
    """
    installation = build_installation(
        directory, version="1.2.3", direct_url=None, own_environment=True
    )
    if tool:
        as_a_tool_environment(installation.interpreter)
    return installation


class TestAToolHostInARepositoryIsNotAClient:
    """An installation uv resolves torch for has no torch phase to report.

    A uv tool or uvx host needs torch and gets it from uv, so no project
    declaration configures it - not the one it happens to be standing in. It
    was recorded as the one other case that configures nothing, a client
    installation, and so told a GPU host that it was a client and counted a
    skipped row against the run.
    """

    def test_no_torch_row_for_a_tool_host_standing_in_a_repository(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: the row that made every such install "mixed".

        Both answers are read from a fresh interpreter in an environment of its
        own: a uv tool environment, and one that is not. Mutation check: asking
        only whether a ``pyproject.toml`` is present, as the reportability
        question did, returns True for the tool environment and fails the
        first ``reportable`` assertion; the last holds the other half, so a
        question that answered False for everything would fail too.
        """
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        tool = _installation(tmp_path / "tool", tool=True)
        project = _installation(tmp_path / "project", tool=False)

        in_a_tool = tool.run(_TORCH_CONFIGURATION_APPLIES, str(tmp_path))
        in_a_project = project.run(_TORCH_CONFIGURATION_APPLIES, str(tmp_path))

        assert in_a_tool["kind"] == "uv-tool"
        assert in_a_tool["reportable"] is False
        assert in_a_project["kind"] == "other"
        assert in_a_project["reportable"] is True

    @pytest.mark.torch
    def test_no_torch_line_and_no_client_wording_for_a_tool_host(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: "this installation is a client", to a GPU host.

        Runs where the inference stack is installed, so the role the install
        reads is the real one: an inference host. Mutation check: recording
        the tool host as ``not_applicable`` again - the one action a client is
        recorded as - fails the action assertion.
        """
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        tool = _installation(tmp_path / "tool", tool=True)

        ran = tool.run(_RUN_THE_TORCH_STEP, str(tmp_path))
        rendered = str(ran["rendered"])

        assert ran["kind"] == "uv-tool"
        assert ran["role"] == "host"
        assert ran["action"] == TorchConfigAction.ABSENT
        assert "PyTorch configuration" not in rendered
        assert ComputeCapability.NOT_APPLICABLE.label not in rendered


class TestTheTorchRowIsNotRepeatedInProvisioning:
    """The install reports its torch step once, under its own heading."""

    def test_no_row_where_the_dedicated_step_owns_it(self, tmp_path: Path) -> None:
        """Guard assertion: the second row explained the absence of work.

        It read "PyTorch: skipped (torch configuration handled by the
        dedicated PyTorch step ...)", and because it disagreed with the two
        fetched dependencies it also made every such run's aggregate outcome
        "mixed". Mutation check: reporting the step again adds the row and
        fails both assertions.
        """
        from ..commands._provision import torch_configuration_is_reportable

        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")

        assert not torch_configuration_is_reportable(tmp_path, {"torch"})

    def test_no_row_where_there_is_no_declaration_to_configure(
        self, tmp_path: Path
    ) -> None:
        from ..commands._provision import torch_configuration_is_reportable

        assert not torch_configuration_is_reportable(tmp_path, set())

    def test_a_project_run_that_configures_torch_still_reports_it(
        self, tmp_path: Path
    ) -> None:
        """A run from an environment a project could own keeps its torch row.

        Read from a fresh interpreter in an environment that is not a tool
        environment, because whether the interpreter running these tests
        belongs to a project is a property of the runner and not of the
        subject.
        """
        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
        project = _installation(tmp_path / "project", tool=False)

        ran = project.run(_TORCH_CONFIGURATION_APPLIES, str(tmp_path))

        assert ran["kind"] == "other"
        assert ran["reportable"] is True


class TestEveryCapabilityOffersAtMostOneCommand:
    """One cause, one command: the remedy carries a single command or none."""

    @pytest.mark.parametrize("capability", list(ComputeCapability))
    def test_at_most_one_command_per_remedy(
        self, capability: ComputeCapability
    ) -> None:
        """Guard assertion: three of these named a second thing to run first.

        Each command is written between backticks, so a remedy with two of
        them carries four. Mutation check: restoring the "`server doctor`
        prints the exact command" sentence to any of these fails here.
        """
        remediation = capability.remediation

        assert remediation is None or remediation.count("`") <= 2, remediation

    def test_a_client_is_told_how_to_serve_rather_than_how_to_rebuild(self) -> None:
        """Guard assertion: a client was told to install a host to serve.

        It never has to: a start runs the service from its own GPU runtime.
        """
        remediation = ComputeCapability.NOT_APPLICABLE.remediation

        assert remediation is not None
        assert "server start" in remediation
        assert "uv tool install" not in remediation

    def test_a_cpu_build_is_not_told_to_find_a_capable_machine(self) -> None:
        """Guard assertion: it said so ON a capable machine.

        The machine's accelerator is not the problem when the torch build is,
        and the service no longer runs in this environment anyway.
        """
        remediation = ComputeCapability.CPU_ONLY_BUILD.remediation

        assert remediation is not None
        assert "CUDA-capable" not in remediation
        assert "server start" in remediation


#: The variable CUDA reads to hide devices from a process; ``-1`` hides all.
_HIDE_EVERY_DEVICE = "CUDA_VISIBLE_DEVICES"

#: The variable that configures the CUDA allocator, which torch parses when the
#: device is first touched and refuses a key it does not know.
_REJECTED_ALLOCATOR_SETTING = "PYTORCH_CUDA_ALLOC_CONF"

#: Classifies the torch this interpreter holds, as the compute probe does.
_CLASSIFY_THIS_TORCH = """
import json

import torch

from vaultspec_rag.operator_state._compute import classify_torch

print(json.dumps(classify_torch(torch).model_dump(mode="json")))
"""


def _classified_by(tmp_path: Path, environment: dict[str, str]) -> dict[str, object]:
    """Classify this host's torch in a fresh interpreter under *environment*."""
    installation = build_installation(
        tmp_path / "installation", version="1.2.3", direct_url=None
    )
    with managed_env(**environment):
        return installation.run(_CLASSIFY_THIS_TORCH)


class TestTheAcceleratorCauseIsStatedOnce:
    """The capability's label is the cause; the detail does not repeat it.

    Each case classifies this host's real torch in a fresh interpreter, so the
    verdict is the one the classifier gives a real build. What the build is
    told about the device is what an operator would tell it: hidden from it, or
    given an allocator setting it rejects.
    """

    @pytest.mark.torch
    def test_the_classification_carries_no_second_copy_of_its_own_sentence(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: the cause appeared nested inside itself.

        The detail is rendered in parentheses after the label, so carrying
        our own accelerator sentence there put the same cause on screen twice
        at once - and three times over, once each surface added its own copy.
        Mutation check: passing the exception's text through again gives the
        report a detail and fails the detail assertion.
        """
        report = _classified_by(tmp_path, {_HIDE_EVERY_DEVICE: "-1"})

        assert report["capability"] == ComputeCapability.NO_DEVICE
        assert report["detail"] is None

    @pytest.mark.torch
    def test_a_diagnosis_from_elsewhere_is_still_carried(self, tmp_path: Path) -> None:
        """Only our own sentence is dropped, not every detail.

        The allocator setting is one torch refuses when it first touches the
        device, with a diagnosis of its own. Mutation check: dropping every
        detail fails the assertion that the diagnosis is carried.
        """
        report = _classified_by(tmp_path, {_REJECTED_ALLOCATOR_SETTING: "bogus_key:1"})

        assert report["capability"] == ComputeCapability.NO_DEVICE
        assert "bogus_key" in str(report["detail"])
        assert report["detail"] != ACCELERATOR_REQUIRED_MESSAGE

    def test_the_sentence_itself_names_no_machine_to_move_to(self) -> None:
        """Guard assertion: it told the operator to go to a capable machine.

        It is raised where torch is already loaded on this one.
        """
        assert "CUDA-capable" not in ACCELERATOR_REQUIRED_MESSAGE
        assert "machine" not in ACCELERATOR_REQUIRED_MESSAGE
