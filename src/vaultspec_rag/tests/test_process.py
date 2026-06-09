"""Unit tests for cli._process helpers (no GPU, no subprocess)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ..cli._process import (
    _WIN_CREATE_BREAKAWAY_FROM_JOB,
    _WIN_CREATE_NEW_PROCESS_GROUP,
    _WIN_CREATE_NO_WINDOW,
    _resolve_daemon_interpreter,
)

pytestmark = [pytest.mark.unit]


class TestWindowsCreationFlags:
    """Assert the Windows process-creation flag constants are correct.

    These tests exercise pure constant values — no subprocess is spawned.
    The numeric values are fixed by the Windows API and must never change;
    asserting them here guards against accidental refactoring.
    """

    def test_create_new_process_group_value(self) -> None:
        assert _WIN_CREATE_NEW_PROCESS_GROUP == 0x00000200

    def test_create_no_window_value(self) -> None:
        assert _WIN_CREATE_NO_WINDOW == 0x08000000

    def test_create_breakaway_from_job_value(self) -> None:
        assert _WIN_CREATE_BREAKAWAY_FROM_JOB == 0x01000000

    def test_breakaway_flag_included_in_full_creationflags(self) -> None:
        """The combined flags for a normal spawn include the breakaway bit."""
        full_flags = (
            _WIN_CREATE_NEW_PROCESS_GROUP
            | _WIN_CREATE_NO_WINDOW
            | _WIN_CREATE_BREAKAWAY_FROM_JOB
        )
        assert full_flags & _WIN_CREATE_BREAKAWAY_FROM_JOB, (
            "CREATE_BREAKAWAY_FROM_JOB must be set in the full creationflags"
        )

    def test_fallback_flags_exclude_breakaway(self) -> None:
        """The fallback flags (used when breakaway is denied) omit the bit."""
        fallback_flags = _WIN_CREATE_NEW_PROCESS_GROUP | _WIN_CREATE_NO_WINDOW
        assert not (fallback_flags & _WIN_CREATE_BREAKAWAY_FROM_JOB), (
            "CREATE_BREAKAWAY_FROM_JOB must NOT be set in the fallback creationflags"
        )


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
