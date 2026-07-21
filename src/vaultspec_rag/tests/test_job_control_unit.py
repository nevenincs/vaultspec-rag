"""Real-behavior tests for cooperative job control and its service bounds."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ..config import EnvVar, get_config, reset_config
from ..job_control import (
    NO_RUN_CONTROL,
    CancelRequested,
    ControlRequest,
    NullRunControl,
    PauseRequested,
    RunControl,
    RunControlToken,
)

pytestmark = [pytest.mark.unit]

_THREAD_TIMEOUT_SECONDS = 5.0
_CONFIG_PROBE_TIMEOUT_SECONDS = 30.0
_PROJECT_ROOT = Path(__file__).parents[3]
_JOB_CONFIG_VARS = (
    EnvVar.JOB_MAX_NONTERMINAL,
    EnvVar.JOB_SHUTDOWN_TIMEOUT_SECONDS,
)
_CONFIG_PROBE = """
import sys

from vaultspec_rag.config import get_config

try:
    value = getattr(get_config(), sys.argv[1])
except Exception as exc:
    print(f"ERROR|{type(exc).__name__}|{exc}")
else:
    print(f"VALUE|{type(value).__name__}|{value!r}")
"""


def _join_thread(thread: threading.Thread) -> None:
    """Join a test worker and fail with a bounded diagnostic if it is stuck."""
    thread.join(timeout=_THREAD_TIMEOUT_SECONDS)
    assert not thread.is_alive(), f"worker {thread.name!r} did not stop"


def _run_config_probe(
    attribute: str,
    *,
    env_var: EnvVar | None = None,
    raw_value: str | None = None,
) -> str:
    """Resolve one production config attribute in an isolated interpreter."""
    env = os.environ.copy()
    for var in _JOB_CONFIG_VARS:
        env.pop(var.value, None)
    if env_var is not None and raw_value is not None:
        env[env_var.value] = raw_value

    completed = subprocess.run(
        [sys.executable, "-c", _CONFIG_PROBE, attribute],
        cwd=_PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=_CONFIG_PROBE_TIMEOUT_SECONDS,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    return completed.stdout.strip()


def test_cross_thread_pause_waits_for_outer_protected_safe_edge() -> None:
    """A cross-thread pause cannot split nested protected mutations."""
    token = RunControlToken()
    entered_inner = threading.Event()
    release_inner = threading.Event()
    outcomes: list[str] = []
    worker_errors: list[Exception] = []

    def run_protected_work() -> None:
        try:
            with token.protected():
                with token.protected():
                    entered_inner.set()
                    if not release_inner.wait(timeout=_THREAD_TIMEOUT_SECONDS):
                        raise TimeoutError("test did not release protected work")
                    token.checkpoint()
                    outcomes.append("inner-checkpoint-returned")
                token.checkpoint()
                outcomes.append("outer-checkpoint-returned")
            outcomes.append("outer-span-returned")
        except PauseRequested as exc:
            outcomes.append(f"delivered-{exc.request.value}")
        except Exception as exc:
            worker_errors.append(exc)

    worker = threading.Thread(
        target=run_protected_work,
        name="job-control-protected-worker",
    )
    worker.start()
    assert entered_inner.wait(timeout=_THREAD_TIMEOUT_SECONDS)
    assert token.snapshot().protected_depth == 2

    assert token.request_pause() is True
    requested = token.snapshot()
    assert requested.desired is ControlRequest.PAUSE
    assert requested.delivered is None
    assert requested.protected_depth == 2
    release_inner.set()
    _join_thread(worker)

    assert worker_errors == []
    assert outcomes == [
        "inner-checkpoint-returned",
        "outer-checkpoint-returned",
        "delivered-pause",
    ]
    delivered = token.snapshot()
    assert delivered.desired is ControlRequest.PAUSE
    assert delivered.delivered is ControlRequest.PAUSE
    assert delivered.protected_depth == 0


def test_pause_is_reversible_before_a_safe_checkpoint() -> None:
    token = RunControlToken()

    assert token.request_pause() is True
    assert token.request_pause() is False
    assert token.request_resume() is True
    assert token.request_resume() is False
    token.checkpoint()

    snapshot = token.snapshot()
    assert snapshot.desired is None
    assert snapshot.delivered is None
    assert snapshot.protected_depth == 0


def test_pause_cannot_be_withdrawn_after_checkpoint_delivery() -> None:
    token = RunControlToken()
    assert token.request_pause() is True
    with pytest.raises(PauseRequested):
        token.checkpoint()

    assert token.request_resume() is False
    assert token.snapshot().desired is ControlRequest.PAUSE


def test_cancellation_is_absorbing_and_reaches_every_checkpoint() -> None:
    token = RunControlToken()

    assert token.request_pause() is True
    assert token.request_cancel() is True
    assert token.request_cancel() is False
    assert token.request_resume() is False
    assert token.request_pause() is False

    with pytest.raises(CancelRequested) as first:
        token.checkpoint()
    with pytest.raises(CancelRequested) as second:
        token.checkpoint()

    assert first.value.request is ControlRequest.CANCEL
    assert second.value.request is ControlRequest.CANCEL
    snapshot = token.snapshot()
    assert snapshot.desired is ControlRequest.CANCEL
    assert snapshot.delivered is ControlRequest.CANCEL


def test_pending_pause_is_delivered_before_protected_entry() -> None:
    token = RunControlToken()
    entered = False
    token.request_pause()

    with pytest.raises(PauseRequested), token.protected():
        entered = True

    assert entered is False
    snapshot = token.snapshot()
    assert snapshot.protected_depth == 0
    assert snapshot.delivered is ControlRequest.PAUSE


def test_application_failure_is_not_masked_by_pending_control() -> None:
    token = RunControlToken()

    with (
        pytest.raises(RuntimeError, match="storage mutation failed"),
        token.protected(),
    ):
        token.request_cancel()
        raise RuntimeError("storage mutation failed")

    after_failure = token.snapshot()
    assert after_failure.desired is ControlRequest.CANCEL
    assert after_failure.delivered is None
    assert after_failure.protected_depth == 0

    with pytest.raises(CancelRequested):
        token.checkpoint()


def test_null_control_is_runtime_compatible_and_never_interrupts() -> None:
    events: list[str] = []

    assert isinstance(RunControlToken(), RunControl)
    assert isinstance(NO_RUN_CONTROL, RunControl)
    assert isinstance(NO_RUN_CONTROL, NullRunControl)
    NO_RUN_CONTROL.checkpoint()
    with NO_RUN_CONTROL.protected():
        events.append("outer")
        with NO_RUN_CONTROL.protected():
            NO_RUN_CONTROL.checkpoint()
            events.append("inner")

    assert events == ["outer", "inner"]


def test_job_control_config_defaults_are_bounded_and_typed() -> None:
    assert _run_config_probe("job_max_nonterminal") == "VALUE|int|64"
    assert _run_config_probe("job_shutdown_timeout_seconds") == ("VALUE|float|300.0")


def test_job_control_config_parses_environment_values() -> None:
    assert (
        _run_config_probe(
            "job_max_nonterminal",
            env_var=EnvVar.JOB_MAX_NONTERMINAL,
            raw_value="7",
        )
        == "VALUE|int|7"
    )
    assert (
        _run_config_probe(
            "job_shutdown_timeout_seconds",
            env_var=EnvVar.JOB_SHUTDOWN_TIMEOUT_SECONDS,
            raw_value="12.5",
        )
        == "VALUE|float|12.5"
    )


def test_job_control_config_honors_public_overrides() -> None:
    reset_config()
    try:
        config = get_config(
            {
                "job_max_nonterminal": 9,
                "job_shutdown_timeout_seconds": 17.5,
            }
        )
        assert config.job_max_nonterminal == 9
        assert config.job_shutdown_timeout_seconds == 17.5
    finally:
        reset_config()


@pytest.mark.parametrize("raw_value", ["0", "-1", "1.5"])
def test_job_max_nonterminal_rejects_invalid_values(raw_value: str) -> None:
    result = _run_config_probe(
        "job_max_nonterminal",
        env_var=EnvVar.JOB_MAX_NONTERMINAL,
        raw_value=raw_value,
    )
    assert result.startswith("ERROR|ValueError|")


@pytest.mark.parametrize("raw_value", ["0", "-1", "nan", "inf"])
def test_job_shutdown_timeout_rejects_invalid_values(raw_value: str) -> None:
    result = _run_config_probe(
        "job_shutdown_timeout_seconds",
        env_var=EnvVar.JOB_SHUTDOWN_TIMEOUT_SECONDS,
        raw_value=raw_value,
    )
    assert result.startswith("ERROR|ValueError|")
