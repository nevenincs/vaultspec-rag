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

pytestmark = [pytest.mark.unit]


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

    def test_install_force_implies_assume_yes_for_torch_config(
        self, consumer_workspace: Path
    ) -> None:
        """Issue #83 finding 2: ``--force`` should bypass the torch-config
        confirmation. A user who typed --force expects the whole install
        to land; silently skipping the patch with a warning is the bug.
        """
        report = install_run(
            path=consumer_workspace,
            force=True,
            assume_yes=False,
            confirm=None,  # non-interactive — would otherwise be skipped-non-tty
        )
        assert report.torch_config_action == "applied"
        assert tc.detect_state(consumer_workspace / "pyproject.toml") == (
            tc.TorchConfigState.CANONICAL
        )

    def test_install_eof_distinguished_from_decline(
        self, consumer_workspace: Path
    ) -> None:
        """Issue #83 finding 3: an EOF on the prompt must not be reported
        as 'declined by user'. CI / IDE-managed shells where ``isatty()``
        lies hit EOF instead of an answer; the user was never asked.
        """

        def eof_confirm(_prompt: str) -> bool:
            raise EOFError

        report = install_run(
            path=consumer_workspace,
            assume_yes=False,
            confirm=eof_confirm,
        )
        assert report.torch_config_action == "skipped-eof"
        # Warning names the bypass flags so the user knows the next move.
        assert any("--yes" in w or "--force" in w for w in report.warnings)
        assert tc.detect_state(consumer_workspace / "pyproject.toml") == (
            tc.TorchConfigState.MISSING
        )

    def test_install_keyboard_interrupt_still_reports_declined(
        self, consumer_workspace: Path
    ) -> None:
        """KeyboardInterrupt is a genuine user signal and must remain
        labelled as 'declined' — distinct from the new EOF branch.
        """

        def interrupt_confirm(_prompt: str) -> bool:
            raise KeyboardInterrupt

        report = install_run(
            path=consumer_workspace,
            assume_yes=False,
            confirm=interrupt_confirm,
        )
        assert report.torch_config_action == "declined"

    def test_install_warns_when_torch_not_a_direct_dep(
        self, consumer_workspace: Path
    ) -> None:
        """Issue #83 finding 4: uv ignores [tool.uv.sources] for purely-
        transitive deps. The patch lands but is a no-op for resolution
        unless torch is also a direct dep. Surface a warning naming
        the canonical fix.
        """
        # consumer_workspace has only ``vaultspec-rag`` in deps, so torch
        # is purely transitive.
        report = install_run(path=consumer_workspace, assume_yes=True)
        assert report.torch_config_action == "applied"
        assert any(
            "direct dependency" in w.lower() and "torch" in w.lower()
            for w in report.warnings
        ), report.warnings

    def test_install_no_warning_when_torch_is_direct_dep(self, tmp_path: Path) -> None:
        """The transitive-dep warning must not fire when torch is already
        a direct dep — false positives would train users to ignore it.
        """
        ws = tmp_path / "with-direct-torch"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            "[project]\n"
            'name = "demo"\n'
            'version = "0.1.0"\n'
            'dependencies = ["vaultspec-rag", "torch>=2.4"]\n',
            encoding="utf-8",
            newline="",
        )
        report = install_run(path=ws, assume_yes=True)
        assert report.torch_config_action == "applied"
        assert not any("direct dependency" in w.lower() for w in report.warnings), (
            report.warnings
        )

    def test_install_force_with_customised_still_reports_conflict(
        self, tmp_path: Path
    ) -> None:
        """``--force`` bypasses the *prompt*, not the safety classifier.
        A CUSTOMISED block must still surface as a conflict — silently
        overwriting user-customised tool config is the worst outcome.
        """
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
        report = install_run(path=ws, force=True, assume_yes=False, confirm=None)
        assert report.torch_config_action == "conflict"
        assert _sha(ws / "pyproject.toml") == sha_before

    def test_install_on_scattered_pyproject_lands_canonical(
        self, tmp_path: Path
    ) -> None:
        """Issue #83 finding 1, end-to-end: the dominant scattered
        ``[tool.*]`` shape must produce a CANONICAL pyproject after a
        single ``install --yes`` run, with no warnings about the patch.
        """
        ws = tmp_path / "scattered"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            "[project]\n"
            'name = "demo"\n'
            'version = "0.1.0"\n'
            'dependencies = ["vaultspec-rag", "torch>=2.4"]\n'
            "\n"
            "[tool.uv]\n"
            "override-dependencies = []\n"
            "\n"
            "[tool.ruff]\n"
            "line-length = 120\n"
            "\n"
            "[tool.pytest.ini_options]\n"
            'testpaths = ["tests"]\n'
            "\n"
            "[tool.coverage.run]\n"
            'source = ["src"]\n',
            encoding="utf-8",
            newline="",
        )
        report = install_run(path=ws, assume_yes=True)
        assert report.torch_config_action == "applied", (
            report.torch_config_action,
            report.warnings,
        )
        assert tc.detect_state(ws / "pyproject.toml") == tc.TorchConfigState.CANONICAL
        # No torch-config write-failure warning surfaced.
        assert not any("torch-config write failed" in w for w in report.warnings)
        # No "[tool] is not a table" / OutOfOrderTableProxy regression.
        assert not any("not a table" in w for w in report.warnings)


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
        assert report.torch_config_conflicts  # populated symmetrically
        assert _sha(ws / "pyproject.toml") == sha_before

    def test_uninstall_dry_run_on_customised_populates_conflicts(
        self, tmp_path: Path
    ) -> None:
        """Dry-run on a CUSTOMISED workspace must still report conflicts
        so the user sees why the removal would refuse. Mirrors the
        install side, which surfaces conflicts in every mode.
        """
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
        report = uninstall_run(path=ws, force=False)  # dry-run path
        assert report.torch_config_action == "skipped"
        assert report.torch_config_conflicts
        assert _sha(ws / "pyproject.toml") == sha_before

    def test_uninstall_dry_run_does_not_mutate(self, consumer_workspace: Path) -> None:
        install_run(path=consumer_workspace, assume_yes=True)
        sha_before = _sha(consumer_workspace / "pyproject.toml")
        # dry_run path without --force stays in dry-run mode.
        report = uninstall_run(path=consumer_workspace, force=False)
        assert report.torch_config_action == "dry_run"
        assert _sha(consumer_workspace / "pyproject.toml") == sha_before

    def test_uninstall_without_vaultspec_dir_does_not_mutate_pyproject(
        self, tmp_path: Path
    ) -> None:
        """INSTALL-01 regression: a directory with no ``.vaultspec/`` is
        NOT an install target rag owns. Even when the user passes
        ``--force`` and the pyproject happens to contain a canonical
        cu130 block (e.g. they pasted the README snippet, or it's a
        sibling project), uninstall must not rewrite the file.

        The data-loss bug: pre-fix, ``uninstall --force`` on such a
        directory silently stripped the cu130 block while the warning
        said "nothing to uninstall".
        """
        ws = tmp_path / "not-a-rag-project"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            "[project]\n"
            'name = "demo"\n'
            'version = "0.1.0"\n'
            'dependencies = ["vaultspec-rag", "torch>=2.4"]\n'
            "\n"
            "[[tool.uv.index]]\n"
            'name = "pytorch-cu130"\n'
            'url = "https://download.pytorch.org/whl/cu130"\n'
            "explicit = true\n"
            "\n"
            "[tool.uv.sources]\n"
            "torch = [\n"
            '    {index = "pytorch-cu130", '
            "marker = \"sys_platform == 'linux' or sys_platform == 'win32'\"},\n"
            "]\n",
            encoding="utf-8",
            newline="",
        )
        sha_before = _sha(ws / "pyproject.toml")
        report = uninstall_run(path=ws, force=True)
        # The pyproject must NOT be mutated.
        assert _sha(ws / "pyproject.toml") == sha_before
        # The torch-config sweep should report a non-destructive outcome.
        assert report.torch_config_action in ("dry_run", "absent", "skipped")
        # And the warning text should still tell the user nothing was done.
        assert any("nothing to uninstall" in w for w in report.warnings)


class TestInstallTorchConfigFollowups:
    """Coverage for the audit findings addressed in the same commit
    series — INSTALL-02 (confirm exception types), INSTALL-03 (uv sync
    stdout fallback), INSTALL-05/06 (transitive-dep on already +
    dry-run), TEST-01 (uv sync action branches), TEST-02 (manual_snippet
    bytes), TEST-03 (force vs no-torch-config precedence), and the
    Gemini-flagged ``InlineTable`` / ``(`` PEP 508 edge cases.
    """

    def test_install_force_with_no_torch_config_disables_patch(
        self, consumer_workspace: Path
    ) -> None:
        """TEST-03 / INSTALL precedence: ``--no-torch-config`` must win
        over ``--force``. A future refactor that hoisted the
        force-implies-yes coercion above the configure_torch
        short-circuit would silently apply the patch despite the user's
        explicit opt-out.
        """
        sha_before = _sha(consumer_workspace / "pyproject.toml")
        report = install_run(
            path=consumer_workspace,
            force=True,
            configure_torch=False,
            assume_yes=False,
        )
        assert report.torch_config_action == "disabled"
        assert _sha(consumer_workspace / "pyproject.toml") == sha_before

    def test_install_confirm_click_abort_does_not_kill_install(
        self, consumer_workspace: Path
    ) -> None:
        """INSTALL-02 regression: a custom ``confirm`` raising any
        exception type other than KeyboardInterrupt/EOFError must fold
        into the warning taxonomy, not propagate up and tear down the
        rest of the install.
        """
        import click

        def click_abort_confirm(_prompt: str) -> bool:
            raise click.exceptions.Abort

        # Must NOT raise; install_run must return a populated report.
        report = install_run(
            path=consumer_workspace,
            assume_yes=False,
            confirm=click_abort_confirm,
        )
        assert report.torch_config_action == "declined"
        assert any(
            "Abort" in w and ("--yes" in w or "--force" in w) for w in report.warnings
        ), report.warnings
        # Pyproject untouched.
        assert tc.detect_state(consumer_workspace / "pyproject.toml") == (
            tc.TorchConfigState.MISSING
        )

    def test_install_confirm_runtime_error_does_not_kill_install(
        self, consumer_workspace: Path
    ) -> None:
        """Sibling of the click.Abort case — any unexpected exception
        from a programmatic confirm hook should land in the same
        graceful-degradation branch, not crash the install.
        """

        def boom(_prompt: str) -> bool:
            raise RuntimeError("hook misconfigured")

        report = install_run(
            path=consumer_workspace,
            assume_yes=False,
            confirm=boom,
        )
        assert report.torch_config_action == "declined"
        # Warning names the exception type so the user knows where to look.
        assert any("RuntimeError" in w for w in report.warnings)

    def test_install_confirm_click_abort_caused_by_eof_reports_skipped_eof(
        self, consumer_workspace: Path
    ) -> None:
        """BEHAV-02 regression: Rich's ``Confirm.ask`` on Windows
        re-raises a stdin EOF as ``click.Abort`` rather than the bare
        ``EOFError`` other platforms see. The install handler must walk
        the exception chain and route those to ``SKIPPED_EOF`` so the
        user sees the bypass-flag hint, not a generic decline label.
        """
        import click

        def windows_eof_confirm(_prompt: str) -> bool:
            try:
                raise EOFError("EOF when reading a line")
            except EOFError as eof_exc:
                raise click.exceptions.Abort from eof_exc

        report = install_run(
            path=consumer_workspace,
            assume_yes=False,
            confirm=windows_eof_confirm,
        )
        assert report.torch_config_action == "skipped-eof", (
            report.torch_config_action,
            report.warnings,
        )
        # Warning is the EOF-shaped one, not the generic "Abort raised".
        assert any("non-interactive stdin" in w for w in report.warnings)
        assert any("--yes" in w or "--force" in w for w in report.warnings)

    def test_install_transitive_warning_fires_on_idempotent_rerun(
        self, consumer_workspace: Path
    ) -> None:
        """INSTALL-05 regression: the transitive-dep warning is the
        most actionable diagnostic rag emits. Without it, a user who
        ran install once, never fixed their direct deps, and re-runs
        gets ``torch_config_action="already"`` with no warnings —
        even though the fix is needed every run.
        """
        # First install lays down the canonical block.
        first = install_run(path=consumer_workspace, assume_yes=True)
        assert first.torch_config_action == "applied"
        assert any("direct dependency" in w for w in first.warnings)
        # Second install hits the CANONICAL short-circuit; warning
        # must still fire because torch is still purely transitive.
        second = install_run(path=consumer_workspace, assume_yes=True)
        assert second.torch_config_action == "already"
        assert any("direct dependency" in w for w in second.warnings), second.warnings

    def test_install_transitive_warning_fires_on_dry_run(
        self, consumer_workspace: Path
    ) -> None:
        """INSTALL-06 regression: dry-run is supposed to show what the
        wet run would do. Hiding the transitive-dep warning behind the
        dry-run gate makes the preview misleading — clean preview, then
        surprise on the real run.
        """
        report = install_run(path=consumer_workspace, dry_run=True)
        assert report.torch_config_action == "dry_run"
        # Warning fires AND is labelled as a preview.
        assert any(
            "(dry-run preview)" in w and "direct dependency" in w
            for w in report.warnings
        ), report.warnings

    def test_install_transitive_warning_silent_when_torch_is_direct(
        self, tmp_path: Path
    ) -> None:
        """Negative pair to the rerun/dry-run tests above — false
        positives would train users to ignore the warning. With torch
        as a direct dep, no transitive warning fires regardless of
        which path produced the canonical state.
        """
        ws = tmp_path / "with-direct-torch"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            "[project]\n"
            'name = "demo"\n'
            'version = "0.1.0"\n'
            'dependencies = ["vaultspec-rag", "torch>=2.4"]\n',
            encoding="utf-8",
            newline="",
        )
        first = install_run(path=ws, assume_yes=True)
        assert first.torch_config_action == "applied"
        assert not any("direct dependency" in w for w in first.warnings)
        # Idempotent re-run: still no warning.
        second = install_run(path=ws, assume_yes=True)
        assert second.torch_config_action == "already"
        assert not any("direct dependency" in w for w in second.warnings)
        # Dry-run on a missing-direct-dep path was tested elsewhere;
        # here the path is CANONICAL on dry-run, so no warning either.
        third = install_run(path=ws, dry_run=True)
        assert third.torch_config_action == "already"
        assert not any("direct dependency" in w for w in third.warnings)


class TestUvSyncTorchBranches:
    """TEST-01 coverage: pin every branch of the uv-sync result
    classifier. Tests target the pure helper
    :func:`vaultspec_rag.commands._classify_uv_sync_result` so the
    branch coverage does not depend on Windows ``CreateProcess`` PATH
    resolution (which only auto-tries ``.exe`` and so cannot be driven
    by a ``.cmd`` stub script). Plus one end-to-end test for the
    ``uv-not-found`` branch which the helper does not see (raised by
    ``subprocess`` before ``returncode`` exists).
    """

    def test_classify_succeeded_when_returncode_zero(self) -> None:
        from vaultspec_rag.commands import _classify_uv_sync_result

        action, warning = _classify_uv_sync_result(returncode=0, stdout="", stderr="")
        assert action == "succeeded"
        assert warning is None

    def test_classify_failed_with_stderr_tail(self) -> None:
        from vaultspec_rag.commands import _classify_uv_sync_result

        action, warning = _classify_uv_sync_result(
            returncode=1, stdout="", stderr="resolution failed\nmore detail"
        )
        assert action == "failed"
        assert warning is not None
        assert "last stderr lines" in warning
        assert "resolution failed" in warning
        assert "exited with code 1" in warning

    def test_classify_failed_with_stdout_fallback(self) -> None:
        """INSTALL-03 regression: stderr empty, stdout populated → use
        stdout's tail. Pre-fix, the user got only the bare exit code.
        """
        from vaultspec_rag.commands import _classify_uv_sync_result

        action, warning = _classify_uv_sync_result(
            returncode=2, stdout="lockfile mismatch on torch", stderr=""
        )
        assert action == "failed"
        assert warning is not None
        assert "last stdout lines" in warning
        assert "lockfile mismatch on torch" in warning

    def test_classify_failed_with_both_streams_empty(self) -> None:
        """When uv exits non-zero with no diagnostics, the warning
        carries only the exit code — but the action must still be
        ``failed`` so renderers colour it red.
        """
        from vaultspec_rag.commands import _classify_uv_sync_result

        action, warning = _classify_uv_sync_result(returncode=255, stdout="", stderr="")
        assert action == "failed"
        assert warning is not None
        assert "exited with code 255" in warning
        # No tail block when there is nothing to tail.
        assert "last stderr lines" not in warning
        assert "last stdout lines" not in warning

    def test_classify_failed_tails_only_last_five_lines(self) -> None:
        """Long uv outputs must be tailed to keep warning readable."""
        from vaultspec_rag.commands import _classify_uv_sync_result

        many = "\n".join(f"line {i}" for i in range(1, 21))
        action, warning = _classify_uv_sync_result(returncode=1, stdout="", stderr=many)
        assert action == "failed"
        assert warning is not None
        # The tail must contain the final five lines and exclude line 1.
        assert "line 20" in warning
        assert "line 16" in warning
        assert "line 15" not in warning  # 6th-from-last; outside the tail
        assert "line 1\n" not in warning

    def test_install_sync_after_records_uv_not_found_when_uv_absent(
        self, tmp_path: Path
    ) -> None:
        """End-to-end test for the only branch the pure helper does
        not cover — the FileNotFoundError raised when ``uv`` is not
        resolvable on PATH at all. Drives ``install_run`` against a
        consumer that needs a fresh apply and points PATH at an empty
        directory so subprocess can't find any ``uv``.
        """
        import os

        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            "[project]\n"
            'name = "demo"\n'
            'version = "0.1.0"\n'
            'dependencies = ["vaultspec-rag", "torch>=2.4"]\n',
            encoding="utf-8",
            newline="",
        )
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(empty_dir)
        try:
            report = install_run(path=ws, assume_yes=True, sync_after=True)
        finally:
            os.environ["PATH"] = original_path
        assert report.torch_sync_action == "uv-not-found"
        assert any("uv` is not on PATH" in w for w in report.warnings)


class TestManualSnippetBytes:
    """TEST-02 coverage: pin the bytes ``manual_snippet()`` emits so a
    future copy edit cannot silently desync README, error messages,
    and runtime output.
    """

    def test_manual_snippet_byte_for_byte(self) -> None:
        expected = (
            "\n"
            "[[tool.uv.index]]\n"
            'name = "pytorch-cu130"\n'
            'url = "https://download.pytorch.org/whl/cu130"\n'
            "explicit = true\n"
            "\n"
            "[tool.uv.sources]\n"
            'torch = [{ index = "pytorch-cu130", '
            "marker = \"sys_platform == 'linux' or sys_platform == 'win32'\" }]\n"
            "\n"
            "# uv ignores [tool.uv.sources] for purely-transitive deps.\n"
            "# Add torch as a direct dep too, e.g. in [project].dependencies\n"
            '# or [dependency-groups].dev:  "torch>=2.4"\n'
        )
        assert tc.manual_snippet() == expected
