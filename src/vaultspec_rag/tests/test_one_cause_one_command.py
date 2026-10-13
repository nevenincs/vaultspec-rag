"""Every install and start message states one cause and offers one command.

A clean-machine lab found the opposite: one failing start printed a warning
about a state that was not present, a command naming a cache environment uv
owns, two mutually exclusive interpreter requests, a project repair for an
environment with no project, and the same accelerator cause three times, once
nested inside the next. These tests hold each of those lines absent and assert
what is said instead.

Nothing is substituted here. The capability labels and remediations are read
directly, the install report is rendered through its own renderer, and the
accelerator classification is driven with a stand-in torch module - the one
input a CPU-only runner and a GPU workstation cannot both produce.
"""

from __future__ import annotations

import io
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from .._gpu import ACCELERATOR_REQUIRED_MESSAGE
from ..operator_state._compute import classify_torch
from ..operator_state._installation import ComputeCapability
from ..torch_config._constants import TorchConfigAction

if TYPE_CHECKING:
    from ..commands._models import InstallReport

pytestmark = [pytest.mark.unit]


def _rendered(report: InstallReport) -> str:
    """The install report as an operator reads it."""
    from rich.console import Console

    from .. import cli as cli_mod
    from ..cli._render import _render_install_report

    buffer = io.StringIO()
    original = cli_mod.console
    cli_mod.console = Console(
        file=buffer, force_terminal=False, color_system=None, width=200
    )
    try:
        _render_install_report(report)
    finally:
        cli_mod.console = original
    return buffer.getvalue()


class TestAnInstallWithNoProjectSaysNothingAboutOne:
    """A tool or pip installation has no project declaration, by design."""

    def test_no_torch_section_and_no_missing_declaration_warning(self) -> None:
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

        out = _rendered(report)

        assert "PyTorch configuration" not in out
        assert "pyproject.toml" not in out
        assert "not found" not in out

    def test_a_real_configuration_is_still_reported(self) -> None:
        """The line is suppressed for one action, not removed."""
        from ..commands._models import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.ALREADY,
        )

        assert "PyTorch configuration" in _rendered(report)


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
        from ..commands._provision import torch_configuration_is_reportable

        (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")

        assert torch_configuration_is_reportable(tmp_path, set())


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


def _torch_without_an_accelerator() -> ModuleType:
    """A stand-in torch whose build has no device of any kind."""
    fake = ModuleType("torch")
    fake.__dict__.update(
        __version__="2.14.0+cpu",
        version=SimpleNamespace(cuda=None),
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
    )
    return fake


class TestTheAcceleratorCauseIsStatedOnce:
    """The capability's label is the cause; the detail does not repeat it."""

    def test_the_classification_carries_no_second_copy_of_its_own_sentence(
        self,
    ) -> None:
        """Guard assertion: the cause appeared nested inside itself.

        The detail is rendered in parentheses after the label, so carrying
        our own accelerator sentence there put the same cause on screen twice
        at once - and three times over, once each surface added its own copy.
        Mutation check: passing the exception's text through again gives the
        report a detail and fails the first assertion.
        """
        report = classify_torch(_torch_without_an_accelerator())

        assert report.detail is None
        assert report.capability is ComputeCapability.CPU_ONLY_BUILD

    def test_a_diagnosis_from_elsewhere_is_still_carried(self) -> None:
        """Only our own sentence is dropped, not every detail."""
        fake = _torch_without_an_accelerator()
        fake.__dict__["backends"] = SimpleNamespace(
            mps=SimpleNamespace(is_available=_raising)
        )

        report = classify_torch(fake)

        assert report.detail == "the driver fell over"

    def test_the_sentence_itself_names_no_machine_to_move_to(self) -> None:
        """Guard assertion: it told the operator to go to a capable machine.

        It is raised where torch is already loaded on this one.
        """
        assert "CUDA-capable" not in ACCELERATOR_REQUIRED_MESSAGE
        assert "machine" not in ACCELERATOR_REQUIRED_MESSAGE


def _raising() -> bool:
    """Fail the way a broken driver does, with a diagnosis of its own."""
    raise RuntimeError("the driver fell over")
