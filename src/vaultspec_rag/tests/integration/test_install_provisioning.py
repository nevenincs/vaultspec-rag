"""Real installation integration behavior: provisioning."""

from __future__ import annotations

import io
import json
from pathlib import Path  # noqa: TC003
from typing import Any

import pytest

from ...commands._install import install_run
from ._install_helpers import (
    _CONSUMER_PYPROJECT,
)

pytestmark = [pytest.mark.integration]


class TestProvisioningReport:
    @pytest.fixture()
    def provisioned_report(
        self, fresh_workspace: Path, isolated_status_dir: Path
    ) -> Any:
        _ = isolated_status_dir
        (fresh_workspace / "pyproject.toml").write_text(
            _CONSUMER_PYPROJECT, encoding="utf-8", newline=""
        )
        return install_run(
            path=fresh_workspace,
            provision=True,
            local_only=True,
            provision_skip={"models"},
            assume_yes=True,
        )

    def test_report_carries_a_provisioning_outcome(
        self, provisioned_report: Any
    ) -> None:
        assert provisioned_report.provision_outcome is not None
        steps = {r.step for r in provisioned_report.provision_outcome.steps}
        # The enrollment torch step runs separately; the front door is told
        # to skip torch so it does not double-report. So the front-door
        # outcome carries the two fetch-and-go dependencies.
        assert "models" in {str(s) for s in steps}
        assert "qdrant" in {str(s) for s in steps}

    def test_json_provisioning_key_is_heterogeneous_and_serialisable(
        self, provisioned_report: Any
    ) -> None:
        data = provisioned_report.to_dict()
        json.dumps(data)  # must not raise
        provisioning = data["provisioning"]
        assert provisioning is not None
        actions = {step["action"] for step in provisioning["steps"]}
        # models and qdrant are both opted out here, so both are skipped,
        # each carrying its own distinct reason (heterogeneous detail).
        details = {step["step"]: step["detail"] for step in provisioning["steps"]}
        assert "local-only" in details["qdrant"]
        assert details["models"] != details["qdrant"]
        assert "skipped" in actions

    def test_torch_enrollment_step_reports_configured_sync_pending(
        self, provisioned_report: Any
    ) -> None:
        from ...torch_config._constants import TorchConfigAction

        # The enrollment torch step actually patched the consumer
        # pyproject; its honest two-phase state is the headline the
        # renderer must surface as "configured, sync pending".
        assert provisioned_report.torch_config_action == TorchConfigAction.APPLIED
        assert provisioned_report.torch_sync_action == "skipped"

    def test_rendered_report_surfaces_heterogeneous_provisioning_wording(
        self, provisioned_report: Any
    ) -> None:
        from rich.console import Console

        from ...cli import _render
        from ...cli._render import _render_install_report

        buffer = io.StringIO()
        captured = Console(
            file=buffer, force_terminal=False, legacy_windows=False, width=200
        )
        original = _render._cli.console
        _render._cli.console = captured  # not a mock: swap restored in finally
        try:
            _render_install_report(provisioned_report)
        finally:
            _render._cli.console = original

        output = buffer.getvalue()
        # The qdrant binary skip and the models skip both render honestly...
        assert "Qdrant binary: skipped" in output
        assert "local-only" in output
        # ...and the provisioning summary line is present and bounded.
        assert "Provisioning:" in output

    def test_dry_run_provisioning_previews_without_writing(
        self, fresh_workspace: Path, isolated_status_dir: Path
    ) -> None:
        from ...commands._provision import ProvisionAction, ProvisionStep

        (fresh_workspace / "pyproject.toml").write_text(
            _CONSUMER_PYPROJECT, encoding="utf-8", newline=""
        )
        report = install_run(
            path=fresh_workspace,
            provision=True,
            dry_run=True,
            provision_skip={"models"},
            assume_yes=True,
        )
        assert report.provision_outcome is not None
        assert report.provision_outcome.dry_run is True
        # A dry-run preview must not have provisioned a qdrant binary into
        # the isolated managed dir nor disturbed the live service.
        qdrant = report.provision_outcome.result_for(ProvisionStep.QDRANT)
        assert qdrant is not None
        assert qdrant.action in {ProvisionAction.DRY_RUN, ProvisionAction.SKIPPED}
        assert not (isolated_status_dir / "bin").exists()
