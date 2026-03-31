"""CLI integration tests for vaultspec-rag against real test-project."""

from __future__ import annotations

import subprocess
import sys

import pytest

from ..constants import PROJECT_ROOT, TEST_PROJECT

pytestmark = [pytest.mark.integration]


def _run_cli(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a vaultspec-rag CLI command via the installed entry point."""
    cmd = [
        sys.executable,
        "-c",
        "from vaultspec_rag.cli import app; app()",
        *args,
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
    )


class TestCLIStatus:
    """Tests for ``vaultspec-rag status``."""

    @pytest.mark.timeout(60)
    def test_status_shows_gpu_info(self):
        """``vaultspec-rag status`` should display CUDA GPU information."""
        result = _run_cli("--target", str(TEST_PROJECT), "status")
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "cuda" in result.stdout.lower() or "GPU" in result.stdout

    @pytest.mark.timeout(60)
    def test_status_shows_document_counts(self):
        """``vaultspec-rag status`` should show document count digits."""
        result = _run_cli("--target", str(TEST_PROJECT), "status")
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert any(c.isdigit() for c in result.stdout), (
            f"Expected numeric counts in status output:\n{result.stdout}"
        )


class TestCLIIndex:
    """Tests for ``vaultspec-rag index``."""

    @pytest.mark.timeout(300)
    def test_index_vault_produces_summary(self):
        """``vaultspec-rag index --type vault`` should print an indexing summary."""
        result = _run_cli(
            "--target",
            str(TEST_PROJECT),
            "index",
            "--type",
            "vault",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Indexing Summary" in result.stdout

    @pytest.mark.timeout(300)
    def test_index_clean_flag_works(self):
        """``vaultspec-rag index --type vault --clean`` exits zero."""
        result = _run_cli(
            "--target",
            str(TEST_PROJECT),
            "index",
            "--type",
            "vault",
            "--clean",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Vault" in result.stdout

    @pytest.mark.timeout(300)
    def test_index_code_produces_summary(self):
        """``vaultspec-rag index --type code`` prints summary with Codebase row."""
        result = _run_cli(
            "--target",
            str(TEST_PROJECT),
            "index",
            "--type",
            "code",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Indexing Summary" in result.stdout
        assert "Codebase" in result.stdout

    @pytest.mark.timeout(300)
    def test_index_all_produces_both_rows(self):
        """``vaultspec-rag index --type all`` should show Vault and Codebase rows."""
        result = _run_cli(
            "--target",
            str(TEST_PROJECT),
            "index",
            "--type",
            "all",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Vault" in result.stdout
        assert "Codebase" in result.stdout


class TestCLISearch:
    """Tests for ``vaultspec-rag search``."""

    @pytest.mark.timeout(300)
    def test_search_vault_returns_results(self):
        """``vaultspec-rag search`` should return ranked results."""
        _run_cli("--target", str(TEST_PROJECT), "index", "--type", "vault")
        result = _run_cli(
            "--target",
            str(TEST_PROJECT),
            "search",
            "architecture decision",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Score" in result.stdout or "0." in result.stdout

    @pytest.mark.timeout(300)
    def test_search_no_results_for_gibberish(self):
        """Searching for nonsense should not crash (may return empty)."""
        _run_cli("--target", str(TEST_PROJECT), "index", "--type", "vault")
        result = _run_cli(
            "--target",
            str(TEST_PROJECT),
            "search",
            "xyzzy99plugh42foobarbaz",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

    @pytest.mark.timeout(300)
    def test_search_code_type_exits_zero(self):
        """``vaultspec-rag search --type code`` should exit cleanly."""
        _run_cli("--target", str(TEST_PROJECT), "index", "--type", "vault")
        result = _run_cli(
            "--target",
            str(TEST_PROJECT),
            "search",
            "function",
            "--type",
            "code",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
