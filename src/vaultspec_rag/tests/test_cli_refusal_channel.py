"""Guards the channel a pre-command refusal is reported on.

A refusal raised in the root callback - an unusable value in the session
environment - is output like any other output, and it answers to the same
two channels the rest of the CLI does. It reached neither. The line went to
standard output as plain ``Error:`` text no matter what the run had asked
for, which corrupts the machine channel a ``--json`` consumer is parsing
(the run prints a line that is not JSON, then exits 1, so the failure is
readable only as an exit code) and pollutes the human one (a diagnostic
arriving where a pipeline is reading the result).

The runs below are real subprocesses. The channel a line lands on is a
property of the process's own streams, and an in-process runner that merges
or redirects them cannot observe it; the plain-text half of this contract is
exactly the half such a runner would report as passing either way.

Both directions were checked. Reverting the root callback to the single
plain-text-on-stdout report fails ``test_a_refused_json_run_prints_one_error
_envelope_on_stdout`` on its JSON decode and ``test_a_refused_plain_run_
prints_to_stderr_not_stdout`` on its empty-stdout assertion; restoring it
passes both.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ..config._types import EnvVar

pytestmark = [pytest.mark.unit]

#: The tree holding the package under test, handed to the child absolutely so
#: it imports this copy rather than an installed one.
_PACKAGE_PATH = str(Path(__file__).resolve().parents[2])

#: A level name no logger spells. The root callback refuses it before any
#: command runs, which is the pre-command refusal these tests are about.
_UNUSABLE_LEVEL = "WARNIGN"


def _run(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI in a child process whose environment cannot be honoured."""
    inherited = os.environ.get("PYTHONPATH") or ""
    env = {
        **os.environ,
        "PYTHONPATH": (
            f"{_PACKAGE_PATH}{os.pathsep}{inherited}" if inherited else _PACKAGE_PATH
        ),
        "NO_COLOR": "1",
        "FORCE_COLOR": "0",
        "COLUMNS": "4096",
        EnvVar.LOG_LEVEL.value: _UNUSABLE_LEVEL,
        EnvVar.STATUS_DIR.value: str(workspace / "st"),
    }
    return subprocess.run(
        [sys.executable, "-m", "vaultspec_rag", *args],
        capture_output=True,
        check=False,
        cwd=str(workspace),
        env=env,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """An enrolled project, so nothing but the bad value can refuse the run."""
    (tmp_path / ".vault").mkdir()
    (tmp_path / ".vaultspec").mkdir()
    return tmp_path


@pytest.mark.timeout(120)
def test_a_refused_json_run_prints_one_error_envelope_on_stdout(
    workspace: Path,
) -> None:
    """A ``--json`` consumer parses the refusal, rather than inferring it."""
    result = _run(workspace, "preprocess", "status", "--json")

    assert result.returncode == 1, result.stdout
    envelope = json.loads(result.stdout)
    assert envelope["schema"] == "vaultspec.error.v1"
    assert envelope["status"] == "failed"
    assert _UNUSABLE_LEVEL in str(envelope["data"]["message"])


@pytest.mark.timeout(120)
def test_a_refused_plain_run_prints_to_stderr_not_stdout(workspace: Path) -> None:
    """Without ``--json`` the diagnostic belongs on the diagnostic stream."""
    result = _run(workspace, "preprocess", "status")

    assert result.returncode == 1, result.stderr
    assert result.stdout.strip() == "", result.stdout
    assert _UNUSABLE_LEVEL in result.stderr
    assert result.stderr.lstrip().startswith("Error:"), result.stderr
