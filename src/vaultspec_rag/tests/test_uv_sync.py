"""Tests for the uv-sync launcher behind ``install --sync``.

Real filesystem (``tmp_path``), real ``vaultspec_core`` from the dev env.
The installation role is the one pinned input: the sync flow runs only on
an inference host, so the module runs as one in every lane.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..commands._install import install_run

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("inference_host")]


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
        from ..commands._uv_sync import _classify_uv_sync_result

        action, warning = _classify_uv_sync_result(returncode=0, stdout="", stderr="")
        assert action == "succeeded"
        assert warning is None

    def test_classify_failed_with_stderr_tail(self) -> None:
        from ..commands._uv_sync import _classify_uv_sync_result

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
        from ..commands._uv_sync import _classify_uv_sync_result

        action, warning = _classify_uv_sync_result(
            returncode=2, stdout="lockfile mismatch on torch", stderr=""
        )
        assert action == "failed"
        assert warning is not None
        assert "last stdout lines" in warning
        assert "lockfile mismatch on torch" in warning

    def test_classify_failed_with_both_streams_empty(self) -> None:
        """When uv exits non-zero with no diagnostics, the warning
        carries only the exit code - but the action must still be
        ``failed`` so renderers colour it red.
        """
        from ..commands._uv_sync import _classify_uv_sync_result

        action, warning = _classify_uv_sync_result(returncode=255, stdout="", stderr="")
        assert action == "failed"
        assert warning is not None
        assert "exited with code 255" in warning
        # No tail block when there is nothing to tail.
        assert "last stderr lines" not in warning
        assert "last stdout lines" not in warning

    def test_classify_failed_tails_only_last_five_lines(self) -> None:
        """Long uv outputs must be tailed to keep warning readable."""
        from ..commands._uv_sync import _classify_uv_sync_result

        many = "\n".join(f"line {i}" for i in range(1, 21))
        action, warning = _classify_uv_sync_result(returncode=1, stdout="", stderr=many)
        assert action == "failed"
        assert warning is not None
        # The tail must contain the final five lines and exclude line 1.
        assert "line 20" in warning
        assert "line 16" in warning
        assert "line 15" not in warning  # 6th-from-last; outside the tail
        assert "line 1\n" not in warning

    def test_a_sync_that_never_returns_is_a_reported_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: an unbounded child is an install that never ends.

        This resolves a project and downloads an accelerated torch build over
        a link the product does not control. Without a bound, a uv that never
        returns leaves the install waiting with nothing to say; the timeout
        is reported like every other uv failure, as a warning on the report
        rather than as a raise.
        """
        import subprocess

        from ..commands import _uv_sync
        from ..commands._models import InstallReport

        def _never_returns(*_args: object, **kwargs: object) -> object:
            bound = kwargs.get("timeout")
            assert isinstance(bound, float), "the launch must carry a bound"
            raise subprocess.TimeoutExpired(cmd="uv sync", timeout=bound)

        monkeypatch.setattr(_uv_sync.subprocess, "run", _never_returns)
        report = InstallReport(action="install", target=tmp_path)

        _uv_sync._run_uv_sync_torch(target=tmp_path, report=report)

        assert report.torch_sync_action == "timed-out"
        assert any("did not finish within" in w for w in report.warnings)

    def test_a_sync_outside_the_pytest_root_never_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: this reinstalls packages in the project it is given.

        A test reaching a real workspace would re-resolve and reinstall
        inside it. The refusal lives in the launcher, so no caller can reach
        around it.

        Mutation check: deleting the containment call lets the run reach the
        subprocess double, which fails with "a foreign workspace must not be
        synced".
        """
        import pathlib

        from .._test_isolation import ManagedSingletonIsolationError
        from ..commands import _uv_sync
        from ..commands._models import InstallReport

        def _refuse(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("a foreign workspace must not be synced")

        monkeypatch.setattr(_uv_sync.subprocess, "run", _refuse)
        outside = pathlib.Path.home() / "not-a-real-workspace"

        with pytest.raises(ManagedSingletonIsolationError):
            _uv_sync._run_uv_sync_torch(
                target=outside, report=InstallReport(action="install", target=outside)
            )

    def test_install_sync_after_records_uv_not_found_when_uv_absent(
        self, tmp_path: Path
    ) -> None:
        """End-to-end test for the only branch the pure helper does
        not cover - the FileNotFoundError raised when ``uv`` is not
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
