"""Tests for :func:`install_run`/:func:`uninstall_run` torch-config flow.

Real filesystem (``tmp_path``), real ``vaultspec_core`` from the dev
env, real ``tomlkit``. No mocks. No HF / GPU dependency — these tests
exercise only the pyproject-patching branch and deliberately do not
trigger the ``sync_after`` subprocess path.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
import tomlkit

from vaultspec_rag import torch_config as tc
from vaultspec_rag.commands import install_run, uninstall_run

if TYPE_CHECKING:
    from pathlib import Path


PROJECT_ONLY = (
    "[project]\n"
    'name = "demo-consumer"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag"]\n'
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def consumer_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "consumer"
    ws.mkdir()
    (ws / "pyproject.toml").write_text(PROJECT_ONLY, encoding="utf-8", newline="")
    return ws


class TestInstallTorchConfig:
    def test_install_with_yes_applies_canonical_block(
        self, consumer_workspace: Path
    ) -> None:
        report = install_run(path=consumer_workspace, assume_yes=True)
        assert report.torch_config_action == "applied"
        pyproject = consumer_workspace / "pyproject.toml"
        assert tc.detect_state(pyproject) == tc.TorchConfigState.CANONICAL

    def test_install_with_no_torch_config_leaves_pyproject_alone(
        self, consumer_workspace: Path
    ) -> None:
        sha_before = _sha(consumer_workspace / "pyproject.toml")
        report = install_run(
            path=consumer_workspace, configure_torch=False, assume_yes=True
        )
        assert report.torch_config_action == "disabled"
        assert _sha(consumer_workspace / "pyproject.toml") == sha_before

    def test_install_idempotent_on_second_run(self, consumer_workspace: Path) -> None:
        install_run(path=consumer_workspace, assume_yes=True)
        sha_after_first = _sha(consumer_workspace / "pyproject.toml")
        report = install_run(path=consumer_workspace, assume_yes=True)
        assert report.torch_config_action == "already"
        assert _sha(consumer_workspace / "pyproject.toml") == sha_after_first

    def test_install_on_workspace_without_pyproject(self, tmp_path: Path) -> None:
        ws = tmp_path / "no-pyproject"
        ws.mkdir()
        report = install_run(path=ws, assume_yes=True)
        assert report.torch_config_action == "absent"
        # Warning text names the missing pyproject.
        assert any("pyproject.toml" in w for w in report.warnings)

    def test_install_with_customised_block_reports_conflict(
        self, tmp_path: Path
    ) -> None:
        ws = tmp_path / "customised"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            PROJECT_ONLY + "\n[[tool.uv.index]]\n"
            'name = "pytorch-cu130"\n'
            'url = "https://download.pytorch.org/whl/cu121"\n'
            "explicit = true\n",
            encoding="utf-8",
            newline="",
        )
        sha_before = _sha(ws / "pyproject.toml")
        report = install_run(path=ws, assume_yes=True)
        assert report.torch_config_action == "conflict"
        assert report.torch_config_conflicts
        assert _sha(ws / "pyproject.toml") == sha_before

    def test_install_non_tty_without_yes_skips_with_warning(
        self, consumer_workspace: Path
    ) -> None:
        # confirm=None simulates the non-interactive case that cli.py
        # never hits (the CLI always passes a Confirm wrapper). This
        # path exercises the sys.stdin.isatty() / confirm-absent fence.
        report = install_run(path=consumer_workspace, assume_yes=False, confirm=None)
        assert report.torch_config_action == "skipped-non-tty"
        assert tc.detect_state(consumer_workspace / "pyproject.toml") == (
            tc.TorchConfigState.MISSING
        )

    def test_install_with_confirm_false_is_declined(
        self, consumer_workspace: Path
    ) -> None:
        # confirm returns False → user declined the prompt.
        report = install_run(
            path=consumer_workspace,
            assume_yes=False,
            confirm=lambda _prompt: False,
        )
        assert report.torch_config_action == "declined"
        assert tc.detect_state(consumer_workspace / "pyproject.toml") == (
            tc.TorchConfigState.MISSING
        )

    def test_install_dry_run_reports_dry_run_action(
        self, consumer_workspace: Path
    ) -> None:
        sha_before = _sha(consumer_workspace / "pyproject.toml")
        report = install_run(path=consumer_workspace, dry_run=True)
        assert report.torch_config_action == "dry_run"
        assert _sha(consumer_workspace / "pyproject.toml") == sha_before

    def test_install_json_surface_includes_torch_config(
        self, consumer_workspace: Path
    ) -> None:
        report = install_run(path=consumer_workspace, assume_yes=True)
        d = report.to_dict()
        assert d["torch_config_action"] == "applied"
        assert "torch_config_conflicts" in d
        assert d["torch_sync_action"] == "skipped"


class TestUninstallTorchConfig:
    def test_uninstall_removes_canonical_block(self, consumer_workspace: Path) -> None:
        install_run(path=consumer_workspace, assume_yes=True)
        report = uninstall_run(path=consumer_workspace, force=True)
        assert report.torch_config_action == "removed"
        assert tc.detect_state(consumer_workspace / "pyproject.toml") == (
            tc.TorchConfigState.MISSING
        )

    def test_uninstall_round_trip_preserves_project_table(
        self, consumer_workspace: Path
    ) -> None:
        """Project semantics survive the apply/remove round trip."""
        orig_parsed = tomlkit.parse(
            (consumer_workspace / "pyproject.toml").read_text(encoding="utf-8")
        )
        install_run(path=consumer_workspace, assume_yes=True)
        uninstall_run(path=consumer_workspace, force=True)
        final_parsed = tomlkit.parse(
            (consumer_workspace / "pyproject.toml").read_text(encoding="utf-8")
        )
        assert final_parsed["project"] == orig_parsed["project"]

    def test_uninstall_on_missing_pyproject_is_absent(self, tmp_path: Path) -> None:
        ws = tmp_path / "empty"
        ws.mkdir()
        # Install nothing; uninstall must be a no-op on the torch-config side.
        report = uninstall_run(path=ws, force=True)
        assert report.torch_config_action == "absent"

    def test_uninstall_on_customised_block_skips_with_conflict(
        self, tmp_path: Path
    ) -> None:
        ws = tmp_path / "customised"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            PROJECT_ONLY + "\n[[tool.uv.index]]\n"
            'name = "pytorch-cu130"\n'
            'url = "https://download.pytorch.org/whl/cu121"\n'
            "explicit = true\n",
            encoding="utf-8",
            newline="",
        )
        sha_before = _sha(ws / "pyproject.toml")
        report = uninstall_run(path=ws, force=True)
        assert report.torch_config_action == "skipped"
        assert _sha(ws / "pyproject.toml") == sha_before

    def test_uninstall_dry_run_does_not_mutate(self, consumer_workspace: Path) -> None:
        install_run(path=consumer_workspace, assume_yes=True)
        sha_before = _sha(consumer_workspace / "pyproject.toml")
        # dry_run path without --force stays in dry-run mode.
        report = uninstall_run(path=consumer_workspace, force=False)
        assert report.torch_config_action == "dry_run"
        assert _sha(consumer_workspace / "pyproject.toml") == sha_before
