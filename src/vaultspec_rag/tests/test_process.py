"""Unit tests for cli._process helpers (no GPU, no subprocess)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ..cli._process import _resolve_daemon_interpreter

pytestmark = [pytest.mark.unit]


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
