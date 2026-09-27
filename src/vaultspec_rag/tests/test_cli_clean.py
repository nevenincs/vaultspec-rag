"""CLI clean prompts, locking and required-target coverage."""

from __future__ import annotations

import typing

import pytest

from ._cli_helpers import (
    _hold_local_index_lock,
    app,
    runner,
)
from ._scaffold import make_workspace

if typing.TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestCleanCommand:
    """Tests for the wipe-only ``clean`` command."""

    def test_clean_help_renders(self):
        result = runner.invoke(app, ["clean", "--help"])
        assert result.exit_code == 0
        assert "wipe" in result.output.lower()

    def test_clean_confirm_prompt_uses_search_index_language(self, tmp_path: Path):
        root = make_workspace(tmp_path)
        result = runner.invoke(
            app,
            ["--target", str(root), "clean", "combined"],
            input="n\n",
        )

        assert result.exit_code == 1
        assert "Delete combined search index data for" in result.output
        assert "Clean cancelled." in result.output
        assert "RAG index data" not in result.output

    def test_clean_noninteractive_abort_uses_operator_language(self, tmp_path: Path):
        root = make_workspace(tmp_path)
        result = runner.invoke(
            app,
            ["--target", str(root), "clean", "vault"],
        )

        assert result.exit_code == 1
        assert "Clean cancelled." in result.output
        assert "Aborted!" not in result.output

    def test_clean_lock_error_uses_operator_language(self, tmp_path: Path) -> None:
        root = make_workspace(tmp_path)
        lock = _hold_local_index_lock(root)
        try:
            result = runner.invoke(
                app,
                ["--target", str(root), "clean", "combined", "--yes"],
            )
        finally:
            lock.release()

        assert result.exit_code == 1, result.output
        assert "Cannot clean the index because the local index is busy" in result.output
        assert "vaultspec-rag server status" in result.output
        for leaked in (
            "Qdrant",
            "Local-file-backed",
            "parallel-safe",
            "exclusive.lock",
            "another process holds the lock",
        ):
            assert leaked not in result.output


class TestCleanRequiredTarget:
    """Clean target is required (no default)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_clean_no_target_errors(self, tmp_path: Path):
        """`vaultspec-rag clean` without a target exits non-zero."""
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "clean"],
        )
        # Typer surfaces missing required argument with exit code 2
        # and "Missing argument" in stderr.
        assert result.exit_code != 0
