"""Progress must not lend transient streams to dependency exit callbacks."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS

pytestmark = [pytest.mark.unit]


def test_first_download_progress_leaves_no_closed_stream_exit_callback() -> None:
    """Exercise first tqdm import inside an actual interactive reporter."""
    program = textwrap.dedent(
        """
        import contextlib
        import io
        import sys
        from vaultspec_rag.cli._core import _build_console
        from vaultspec_rag.cli._progress import StartupStatusReporter
        from vaultspec_rag.commands._snapshot_progress import SnapshotBars

        assert 'tqdm' not in sys.modules, 'premise: first download import'
        capture = io.StringIO()
        console = _build_console(interactive=True, file=capture)
        reporter = StartupStatusReporter(
            json_mode=False, console=console, interactive=True
        )
        with contextlib.redirect_stdout(capture), reporter:
            reporter.stage('Downloading lifetime witness')
            with SnapshotBars() as tracker:
                bar_class = tracker.tqdm_class
                assert bar_class is not None
                bar = bar_class(total=1024, unit='B')
                bar.update(1024)
                bar.close()
        rendered = capture.getvalue()
        capture.close()
        sys.__stdout__.write(rendered)
        """
    )
    environment = os.environ.copy()
    environment["TERM"] = "xterm-256color"
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
        timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
        env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Downloading lifetime witness" in result.stdout
    assert "\x1b[?25l" in result.stdout, "premise: active interactive live region"
    # Red/green: default Live redirection retained a FileProxy in colorama;
    # closing its underlying capture failed here at process exit. Disabling
    # implicit redirection preserved the live output and made stderr empty.
    assert result.stderr == "", "progress dependency exit callbacks must be clean"
