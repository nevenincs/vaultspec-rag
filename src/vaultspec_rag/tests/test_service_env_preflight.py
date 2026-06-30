"""Service<->python-env hardening: the daemon-interpreter pre-flight, the
start-failure log tail, and the status env label.

All real-behavior, no mocks: the pre-flight is exercised against actual
interpreters (the current one, and a path that does not exist), the log tail
against a real temp file, and the env label against plain dicts.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ..cli._process import _probe_daemon_cuda
from ..cli._service_lifecycle import _status_env_label, _tail_daemon_log

pytestmark = [pytest.mark.unit]

# Independent torch/cuda truth for an interpreter, evaluated in its OWN
# subprocess so this (torch-free) test process never imports torch - the same
# discipline the probe itself follows. Exit 0 == working CUDA torch.
_TRUTH = (
    "import importlib.util, sys\n"
    "if importlib.util.find_spec('torch') is None:\n"
    "    sys.exit(3)\n"
    "import torch\n"
    "sys.exit(0 if torch.cuda.is_available() else 1)\n"
)


def test_probe_agrees_with_independent_truth_for_the_current_interpreter() -> None:
    """The probe verdict matches an independent subprocess truth.

    Both the probe and the truth-check run in subprocesses, so this test process
    never imports torch (importing torch in-process is exactly what the probe
    avoids). A working CUDA torch must yield ``None``; anything else must yield a
    blocking verdict.
    """
    truth = subprocess.run(
        [sys.executable, "-c", _TRUTH],
        capture_output=True,
        timeout=120,
        check=False,
    ).returncode
    result = _probe_daemon_cuda(sys.executable)
    if truth == 0:
        assert result is None
    else:
        assert result is not None
        blocking, reason = result
        assert blocking is True
        assert reason


def test_probe_missing_interpreter_blocks_with_a_clear_reason() -> None:
    result = _probe_daemon_cuda("this-interpreter-does-not-exist-xyz")
    assert result is not None
    blocking, reason = result
    assert blocking is True
    assert "does not exist" in reason


def test_tail_daemon_log_returns_last_nonempty_lines(tmp_path: Path) -> None:
    log = tmp_path / "service.log"
    log.write_text(
        "line one\n\n  \nline two\nRuntimeError: CUDA GPU required\n",
        encoding="utf-8",
    )
    tail = _tail_daemon_log(log, max_lines=2)
    assert tail == ["line two", "RuntimeError: CUDA GPU required"]


def test_tail_daemon_log_missing_file_is_empty(tmp_path: Path) -> None:
    assert _tail_daemon_log(tmp_path / "absent.log") == []


def test_status_env_label_reads_the_executable() -> None:
    assert _status_env_label({"executable": "/venv/bin/python"}) == "/venv/bin/python"


def test_status_env_label_missing_is_explicit() -> None:
    assert _status_env_label(None) == "not reported by service"
    assert _status_env_label({}) == "not reported by service"
