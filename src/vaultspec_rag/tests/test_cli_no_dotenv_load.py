"""The CLI must never read a workspace ``.env`` outside the credential gate.

Loading every variable from whichever ``.env`` a package finds above its own
installed files lets a cloned repository reconfigure a globally installed
tool. This guard runs in a fresh interpreter subprocess, started from a
working directory that holds a ``.env`` setting a variable no production code
reads, and shows the setting never reaches the process.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_SENTINEL_NAME = "VAULTSPEC_RAG_TEST_DOTENV_SENTINEL"
_SENTINEL_VALUE = "set-by-dotenv"

# The checked name travels through its own environment variable rather than
# being interpolated into the script text, so the script stays a fixed,
# reviewable string.
_CHECK = (
    "import os, vaultspec_rag.cli; "
    "print(os.environ.get(os.environ['CHECK_SENTINEL_NAME'], ''))"
)


def test_importing_the_cli_reads_no_workspace_env(tmp_path: Path) -> None:
    """Importing the CLI from a directory with a ``.env`` must not load it."""
    (tmp_path / ".env").write_text(
        f"{_SENTINEL_NAME}={_SENTINEL_VALUE}\n", encoding="utf-8"
    )
    env = {key: value for key, value in os.environ.items() if key != _SENTINEL_NAME}
    env["CHECK_SENTINEL_NAME"] = _SENTINEL_NAME
    proc = subprocess.run(
        [sys.executable, "-c", _CHECK],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", proc.stderr
