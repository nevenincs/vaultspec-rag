"""The daemon and the stdio MCP server refuse a bad setting before serving.

Both server entry points (``vaultspec_rag.server:main``) used to build their
config or call ``configure_logging`` with nothing checking the environment
first: a bad ``VAULTSPEC_RAG_PREPROCESS`` surfaced only on the first document
a running daemon tried to preprocess, and a bad ``VAULTSPEC_RAG_LOG_LEVEL``
raised a bare ``ConfigurationError`` traceback out of ``resolve_log_level``
mid-setup. Each entry point now runs the same collective refusal the CLI
runs, before anything else - critical for the stdio transport, whose stdout
is the MCP protocol channel itself, so nothing may reach it before a
refusal.

Real subprocesses (no mocks): each test launches a fresh interpreter with one
bad environment variable and asserts one named error on stderr, exit code 1,
and nothing on stdout.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.unit]

_STDIO_SCRIPT = "from vaultspec_rag.server import main; main()"
# An arbitrary port: the refusal fires before anything binds it, so it is
# never actually claimed.
_DAEMON_SCRIPT = "from vaultspec_rag.server import main; main(port=58311)"


def _run(
    script: str, env_overrides: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **env_overrides}
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=30,
    )


@pytest.mark.parametrize(
    "script",
    [
        pytest.param(_STDIO_SCRIPT, id="stdio"),
        pytest.param(_DAEMON_SCRIPT, id="daemon"),
    ],
)
def test_bad_preprocess_switch_refuses_before_serving(script: str) -> None:
    proc = _run(script, {"VAULTSPEC_RAG_PREPROCESS": "bogus"})

    assert proc.returncode == 1, proc.stderr
    assert proc.stdout == ""
    assert proc.stderr.count("Error:") == 1, proc.stderr
    assert "VAULTSPEC_RAG_PREPROCESS" in proc.stderr


@pytest.mark.parametrize(
    "script",
    [
        pytest.param(_STDIO_SCRIPT, id="stdio"),
        pytest.param(_DAEMON_SCRIPT, id="daemon"),
    ],
)
def test_bad_log_level_refuses_before_serving(script: str) -> None:
    proc = _run(script, {"VAULTSPEC_RAG_LOG_LEVEL": "bogus"})

    assert proc.returncode == 1, proc.stderr
    assert proc.stdout == ""
    assert proc.stderr.count("Error:") == 1, proc.stderr
    assert "VAULTSPEC_RAG_LOG_LEVEL" in proc.stderr
