"""``uv sync`` subprocess invocation and result classification."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from ._models import InstallReport


def _run_uv_sync_torch(*, target: Path, report: InstallReport) -> None:
    """Shell out to ``uv sync --reinstall-package torch``.

    Non-fatal: failures are recorded as warnings, never raised. Runs
    with ``check=False`` so we can surface uv's own stderr in the
    report without a Python traceback. Result-classification logic
    lives in :func:`_classify_uv_sync_result` so it can be exercised
    by tests without going through ``subprocess`` PATH resolution
    (Windows ``CreateProcess`` only auto-tries ``.exe``, which makes
    ``.cmd`` / ``.bat`` stubs unreliable cross-platform).
    """
    try:
        proc = subprocess.run(
            ["uv", "sync", "--reinstall-package", "torch"],
            cwd=str(target),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        report.torch_sync_action = "uv-not-found"
        report.warnings.append(
            "--sync requested but `uv` is not on PATH; "
            "run `uv sync --reinstall-package torch` manually"
        )
        return
    except OSError as exc:
        report.torch_sync_action = "error"
        report.warnings.append(f"uv sync failed to launch: {exc}")
        return

    action, warning = _classify_uv_sync_result(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )
    report.torch_sync_action = action
    if warning is not None:
        report.warnings.append(warning)


def _classify_uv_sync_result(
    *, returncode: int, stdout: str, stderr: str
) -> tuple[str, str | None]:
    """Classify the outcome of ``uv sync`` by exit code and streams.

    Pure function: takes the captured streams from ``subprocess.run``
    and returns ``(action, warning_or_none)`` for the install report.
    Centralising the stream-priority logic here lets tests pin every
    branch (success, stderr-failed, stdout-only-failed, both-empty
    failed) without forging subprocesses.

    uv writes resolution failures to stderr most of the time, but
    certain ``--locked`` mismatches and lockfile-conflict renderings
    land on stdout - surface whichever stream carries a payload so
    the user has something actionable to read.
    """
    if returncode == 0:
        return "succeeded", None
    stderr_s = stderr.strip()
    stdout_s = stdout.strip()
    if stderr_s:
        tail = "\n".join(stderr_s.splitlines()[-5:])
        return (
            "failed",
            f"uv sync --reinstall-package torch exited with code "
            f"{returncode}; last stderr lines:\n{tail}",
        )
    if stdout_s:
        tail = "\n".join(stdout_s.splitlines()[-5:])
        return (
            "failed",
            f"uv sync --reinstall-package torch exited with code "
            f"{returncode}; last stdout lines:\n{tail}",
        )
    return (
        "failed",
        f"uv sync --reinstall-package torch exited with code {returncode}",
    )
