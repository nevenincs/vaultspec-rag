"""Unit tests for cli._process helpers (no GPU, no subprocess)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from .._win32 import (
    WIN_CREATE_BREAKAWAY_FROM_JOB,
    WIN_CREATE_NEW_PROCESS_GROUP,
    WIN_CREATE_NO_WINDOW,
    WIN_DETACHED_PROCESS,
)
from ..cli._process import (
    WIN_DAEMON_DETACHED_FLAGS,
    WIN_DAEMON_SPAWN_FLAGS,
    _resolve_daemon_interpreter,
)

pytestmark = [pytest.mark.unit]


class TestWindowsCreationFlags:
    """Assert the daemon spawn's Windows creation-flag policy.

    The numeric values are fixed by the Windows API and read from ``_win32``,
    which is the one place they are declared. The combinations are this
    spawn's policy and are read from the module that spawns, so these assert
    what production passes to ``Popen`` rather than a copy of it: the previous
    versions built the combination inside the test and then asserted a bit
    they had just set, which held whatever production did.
    """

    def test_create_new_process_group_value(self) -> None:
        assert WIN_CREATE_NEW_PROCESS_GROUP == 0x00000200

    def test_create_no_window_value(self) -> None:
        assert WIN_CREATE_NO_WINDOW == 0x08000000

    def test_create_breakaway_from_job_value(self) -> None:
        assert WIN_CREATE_BREAKAWAY_FROM_JOB == 0x01000000

    def test_detached_process_value(self) -> None:
        assert WIN_DETACHED_PROCESS == 0x00000008

    def test_breakaway_flag_included_in_full_creationflags(self) -> None:
        """The flags the preferred spawn passes include the breakaway bit."""
        assert WIN_DAEMON_SPAWN_FLAGS & WIN_CREATE_BREAKAWAY_FROM_JOB, (
            "CREATE_BREAKAWAY_FROM_JOB must be set in the full creationflags"
        )
        assert WIN_DAEMON_SPAWN_FLAGS == (
            WIN_CREATE_NEW_PROCESS_GROUP
            | WIN_CREATE_NO_WINDOW
            | WIN_CREATE_BREAKAWAY_FROM_JOB
        )

    def test_fallback_flags_exclude_breakaway(self) -> None:
        """The console-detached fallback must not carry the breakaway bit.

        Breakaway is what the fallback exists because the Job Object refused,
        so passing it again would fail the same way.
        """
        assert not (WIN_DAEMON_DETACHED_FLAGS & WIN_CREATE_BREAKAWAY_FROM_JOB), (
            "CREATE_BREAKAWAY_FROM_JOB must NOT be set in the fallback creationflags"
        )
        assert WIN_DAEMON_DETACHED_FLAGS & WIN_DETACHED_PROCESS


class TestResolveDaemonInterpreter:
    def test_returns_existing_path(self) -> None:
        result = _resolve_daemon_interpreter()
        assert Path(result).exists(), f"interpreter path does not exist: {result!r}"

    def test_lives_under_scripts_or_bin(self) -> None:
        result = _resolve_daemon_interpreter()
        parent_name = Path(result).parent.name
        assert parent_name in {"Scripts", "bin"}, (
            f"expected interpreter under Scripts/ or bin/, got parent {parent_name!r}"
            f" (full path: {result!r})"
        )

    def test_ends_with_python_executable(self) -> None:
        result = _resolve_daemon_interpreter()
        name = Path(result).name.lower()
        expected = "python.exe" if sys.platform == "win32" else "python"
        assert name == expected, (
            f"expected interpreter filename {expected!r}, got {name!r}"
        )
