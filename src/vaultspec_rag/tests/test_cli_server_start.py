"""CLI coverage for the server-first ``server start`` local-only surface.

Exercises the real Typer surface and the real daemon-env translation; no
mocks, patches, or fakes. The missing-binary loud-failure path on a default
start is covered at the integration tier in ``test_qdrant_server_mode.py``
(it needs an environment with no resolvable binary, which cannot be staged
without disturbing the live service this suite shares).
"""

from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..cli._process import _service_child_env
from ..config import EnvVar

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def test_local_only_true_translates_to_daemon_env() -> None:
    env = _service_child_env(local_only=True)
    assert env[EnvVar.LOCAL_ONLY.value] == "1"


def test_local_only_false_translates_to_daemon_env() -> None:
    env = _service_child_env(local_only=False)
    assert env[EnvVar.LOCAL_ONLY.value] == "0"


def test_local_only_unset_preserves_operator_env() -> None:
    key = EnvVar.LOCAL_ONLY.value
    previous = os.environ.get(key)
    os.environ[key] = "1"
    try:
        env = _service_child_env(local_only=None)
        # None leaves the flag unwritten, so an operator-set value survives.
        assert env[key] == "1"
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def test_default_start_does_not_force_a_backend() -> None:
    # No flags: neither the server-mode nor the local-only knob is written,
    # so the daemon resolves the server-first default through its config.
    env = _service_child_env()
    assert EnvVar.LOCAL_ONLY.value not in env
    assert EnvVar.QDRANT_SERVER.value not in env


def test_server_start_help_renders_local_only_flag() -> None:
    result = runner.invoke(app, ["server", "start", "--help"])
    assert result.exit_code == 0
    assert "--local-only" in result.output
