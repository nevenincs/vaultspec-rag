"""The level every process kind logs at, over the one ladder.

Three process kinds resolve this - the command line, the stdio adapter and
the resident daemon - and they used to answer differently: the command line
read one variable, the daemon read none and logged at a fixed level, and the
adapter configured nothing at all. The ladder is the same for all three now,
and what differs is only the last rung each declares.

The runs are real subprocesses. The decision is made in a process's own
bootstrap, before any command executes, so an in-process call enters below
the seam and would prove nothing about it.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from vaultspec_core.config import VAULTSPEC_LOG_LEVEL
from vaultspec_core.logging_config import reset_logging

from ..config._types import EnvVar
from ..logging_config import configure_logging
from ._scaffold import restore_env, set_env

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

_PACKAGE_PATH = str(Path(__file__).resolve().parents[2])

#: A real subcommand, because the root callback is where the refusal lives
#: and the eager options (``--version``, ``--help``) answer above it. This
#: one reaches the callback and then stops without contacting a service.
_PROBE = ("server", "status", "--json")


@pytest.fixture
def clean_levels() -> Iterator[None]:
    """Unset both level names and leave logging reconfigurable."""
    scoped = os.environ.pop(EnvVar.LOG_LEVEL.value, None)
    shared = os.environ.pop(VAULTSPEC_LOG_LEVEL.env_name, None)
    reset_logging()
    try:
        yield
    finally:
        restore_env(EnvVar.LOG_LEVEL, scoped)
        if shared is None:
            os.environ.pop(VAULTSPEC_LOG_LEVEL.env_name, None)
        else:
            os.environ[VAULTSPEC_LOG_LEVEL.env_name] = shared
        reset_logging()
        logging.getLogger().setLevel(logging.WARNING)


def _configured_level(
    *, debug: bool = False, verbose: bool = False, default: str = "WARNING"
) -> int:
    """Configure logging afresh and report the level the root logger took."""
    reset_logging()
    configure_logging(debug=debug, verbose=verbose, default=default)
    return logging.getLogger().level


@pytest.mark.usefixtures("clean_levels")
def test_the_shipped_default_applies_when_nothing_names_a_level() -> None:
    """Each process kind declares its own last rung."""
    assert _configured_level() == logging.WARNING
    assert _configured_level(default="INFO") == logging.INFO


@pytest.mark.usefixtures("clean_levels")
def test_the_scoped_variable_outranks_the_declared_default() -> None:
    """A daemon that ships INFO still honours a level named for it.

    This is what a hard-coded level denied: the one process kind whose logs
    an operator reaches for when something is wrong was the one that ignored
    the variable they set.
    """
    previous = set_env(EnvVar.LOG_LEVEL, "error")
    try:
        assert _configured_level(default="INFO") == logging.ERROR
    finally:
        restore_env(EnvVar.LOG_LEVEL, previous)


@pytest.mark.usefixtures("clean_levels")
def test_the_framework_variable_answers_behind_the_scoped_one() -> None:
    """A session that turns up the logs for every vaultspec tool turns up these."""
    os.environ[VAULTSPEC_LOG_LEVEL.env_name] = "DEBUG"

    assert _configured_level() == logging.DEBUG


@pytest.mark.usefixtures("clean_levels")
def test_the_scoped_variable_outranks_the_framework_one() -> None:
    os.environ[EnvVar.LOG_LEVEL.value] = "ERROR"
    os.environ[VAULTSPEC_LOG_LEVEL.env_name] = "DEBUG"

    assert _configured_level() == logging.ERROR


@pytest.mark.usefixtures("clean_levels")
def test_the_invocation_outranks_both_variables() -> None:
    os.environ[EnvVar.LOG_LEVEL.value] = "ERROR"

    assert _configured_level(debug=True) == logging.DEBUG
    assert _configured_level(verbose=True) == logging.INFO


def _run_cli(*args: str, env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    inherited = os.environ.get("PYTHONPATH") or ""
    env = {
        **os.environ,
        "PYTHONPATH": (
            f"{_PACKAGE_PATH}{os.pathsep}{inherited}" if inherited else _PACKAGE_PATH
        ),
        "NO_COLOR": "1",
        "COLUMNS": "4096",
        **env_extra,
    }
    env.pop(VAULTSPEC_LOG_LEVEL.env_name, None)
    env.pop(EnvVar.LOG_LEVEL.value, None)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "vaultspec_rag", *args],
        capture_output=True,
        check=False,
        env=env,
        encoding="utf-8",
        errors="replace",
    )


@pytest.mark.timeout(120)
def test_a_level_that_does_not_exist_stops_the_run() -> None:
    """Refused, not degraded, and named.

    Degrading was wrong in both directions: quieter than asked and the
    diagnostics never arrive, louder and the operator reads the new output
    as a change in behaviour. Neither says the value was rejected.
    """
    result = _run_cli(*_PROBE, env_extra={EnvVar.LOG_LEVEL.value: "verbose-please"})

    assert result.returncode == 1, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert EnvVar.LOG_LEVEL.value in combined, combined
    assert "verbose-please" in combined, combined


@pytest.mark.timeout(120)
def test_a_bad_framework_level_is_refused_naming_its_own_variable() -> None:
    """The report names the variable the operator actually set."""
    result = _run_cli(*_PROBE, env_extra={VAULTSPEC_LOG_LEVEL.env_name: "chatty"})

    assert result.returncode == 1, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert VAULTSPEC_LOG_LEVEL.env_name in combined, combined


@pytest.mark.timeout(120)
def test_every_unusable_value_is_reported_in_one_run() -> None:
    """One edit, one round of mistakes.

    A framework value and one of this package's own are wrong at once. The
    run has to name both: stopping on the first leaves the operator to fix
    it, run again, and discover the second.
    """
    result = _run_cli(
        *_PROBE,
        env_extra={
            VAULTSPEC_LOG_LEVEL.env_name: "chatty",
            EnvVar.PORT.value: "not-a-port",
        },
    )

    assert result.returncode == 1, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert VAULTSPEC_LOG_LEVEL.env_name in combined, combined
    assert EnvVar.PORT.value in combined, combined
