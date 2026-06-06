"""CLI integration tests for vaultspec-rag against a synthetic vault.

Each test gets a fresh vault root via session fixture so the CLI
subprocess can open its own Qdrant client without lock contention.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from ..corpus import build_synthetic_vault

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope="session")
def cli_vault(tmp_path_factory):
    """Session-scoped synthetic vault for CLI subprocess tests.

    No VaultStore is opened here - the CLI subprocess will create
    its own Qdrant client, avoiding local-mode lock contention.
    """
    root = tmp_path_factory.mktemp("cli-vault")
    build_synthetic_vault(root, n_docs=24, seed=500)
    return root


def _run_cli(
    *args: str,
    cwd: str | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    """Run a vaultspec-rag CLI command via the installed entry point."""
    import os

    env = dict(os.environ)
    if cwd is not None:
        env["VAULTSPEC_RAG_STATUS_DIR"] = str(cwd)
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
        cwd=cwd,
        env=env,
        encoding="utf-8",
        errors="replace",
    )


class TestCLIStatus:
    """Tests for ``vaultspec-rag status``."""

    @pytest.mark.timeout(60)
    def test_status_shows_gpu_info(self, cli_vault):
        """``vaultspec-rag status`` should display CUDA GPU information."""
        root = str(cli_vault)
        result = _run_cli("--target", root, "status", cwd=root)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "cuda" in result.stdout.lower() or "GPU" in result.stdout

    @pytest.mark.timeout(60)
    def test_status_shows_document_counts(self, cli_vault):
        """``vaultspec-rag status`` should show document count digits."""
        root = str(cli_vault)
        result = _run_cli("--target", root, "status", cwd=root)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert any(c.isdigit() for c in result.stdout), (
            f"Expected numeric counts in status output:\n{result.stdout}"
        )


@pytest.mark.subprocess_gpu
class TestCLIIndex:
    """Tests for ``vaultspec-rag index``.

    Marked ``subprocess_gpu`` - index subprocesses load GPU models.
    """

    @pytest.mark.timeout(300)
    def test_index_vault_produces_summary(self, cli_vault):
        """``vaultspec-rag index --type vault`` should print a summary."""
        root = str(cli_vault)
        result = _run_cli("--target", root, "index", "--type", "vault", cwd=root)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Indexing Summary" in result.stdout

    @pytest.mark.timeout(300)
    def test_index_rebuild_flag_works(self, cli_vault):
        """``vaultspec-rag index --type vault --rebuild`` exits zero."""
        root = str(cli_vault)
        result = _run_cli(
            "--target",
            root,
            "index",
            "--type",
            "vault",
            "--rebuild",
            cwd=root,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Vault" in result.stdout

    @pytest.mark.timeout(300)
    def test_index_code_produces_summary(self, cli_vault):
        """``vaultspec-rag index --type code`` prints summary."""
        root = str(cli_vault)
        result = _run_cli("--target", root, "index", "--type", "code", cwd=root)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Indexing Summary" in result.stdout
        assert "Codebase" in result.stdout

    @pytest.mark.timeout(300)
    def test_index_all_produces_both_rows(self, cli_vault):
        """``vaultspec-rag index --type all`` shows Vault and Codebase."""
        root = str(cli_vault)
        result = _run_cli("--target", root, "index", "--type", "all", cwd=root)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Vault" in result.stdout
        assert "Codebase" in result.stdout


@pytest.mark.subprocess_gpu
class TestCLISearch:
    """Tests for ``vaultspec-rag search``.

    Marked ``subprocess_gpu`` - these spawn CLI subprocesses that load
    their own GPU models (~1.9 GB VRAM). They MUST run in a separate
    pytest session from tests that use the ``embedding_model`` fixture,
    otherwise combined VRAM exceeds 16 GB and crashes on RTX 4080.

    Run with: ``pytest -m subprocess_gpu``
    """

    @pytest.mark.timeout(300)
    def test_search_vault_returns_results(self, cli_vault):
        """``vaultspec-rag search`` should return ranked results."""
        root = str(cli_vault)
        # Ensure indexed first
        _run_cli("--target", root, "index", "--type", "vault", cwd=root)
        result = _run_cli(
            "--target",
            root,
            "search",
            "architecture decision",
            cwd=root,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Score" in result.stdout or "0." in result.stdout

    @pytest.mark.timeout(300)
    def test_search_no_results_for_gibberish(self, cli_vault):
        """Searching for nonsense should not crash."""
        root = str(cli_vault)
        result = _run_cli(
            "--target",
            root,
            "search",
            "xyzzy99plugh42foobarbaz",
            cwd=root,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

    @pytest.mark.timeout(300)
    def test_search_code_type_exits_zero(self, cli_vault):
        """``vaultspec-rag search --type code`` should exit cleanly."""
        root = str(cli_vault)
        result = _run_cli(
            "--target",
            root,
            "search",
            "function",
            "--type",
            "code",
            cwd=root,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
