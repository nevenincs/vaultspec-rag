"""CLI integration tests for vaultspec-rag against a synthetic vault.

Each test gets a fresh vault root via session fixture so the CLI
subprocess can open its own Qdrant client without lock contention.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from .._production_service import production_service
from ..corpus import build_synthetic_vault

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import TempPathFactory


@pytest.fixture(scope="session")
def cli_vault(tmp_path_factory: TempPathFactory) -> Path:
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
) -> subprocess.CompletedProcess[str]:
    """Run a vaultspec-rag CLI command via the installed entry point."""
    import os

    env = dict(os.environ)
    if cwd is not None:
        env["VAULTSPEC_RAG_STATUS_DIR"] = str(cwd)
    cmd = [
        sys.executable,
        "-m",
        "vaultspec_rag",
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

    @pytest.mark.integration
    @pytest.mark.timeout(60)
    def test_status_shows_gpu_info(self, cli_vault: Path) -> None:
        """``vaultspec-rag status`` should display CUDA GPU information."""
        root = str(cli_vault)
        result = _run_cli("--target", root, "status", cwd=root)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "cuda" in result.stdout.lower() or "GPU" in result.stdout

    @pytest.mark.integration
    @pytest.mark.timeout(60)
    def test_status_shows_document_counts(self, cli_vault: Path) -> None:
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

    Local GPU indexing is reached the way an operator reaches it: ``index``
    delegates to a running service, and running the work locally instead
    requires ``--borrow-gpu`` plus a live compatible service to quiesce. Each
    test therefore stands up the real authenticated route host in this process
    and publishes it through the production discovery writer at the status dir
    the subprocess reads, so the subprocess's own coordinator discovers it,
    pauses it, and only then runs the indexing these tests assert on. Nothing
    is rehearsed: a refusal from the borrower gate reaches no summary at all
    and fails every assertion below.
    """

    @pytest.mark.timeout(300)
    def test_index_vault_produces_summary(self, cli_vault: Path) -> None:
        """``vaultspec-rag index --type vault`` should print a summary."""
        root = str(cli_vault)
        with production_service(cli_vault):
            result = _run_cli(
                "--target",
                root,
                "index",
                "--type",
                "vault",
                "--borrow-gpu",
                cwd=root,
            )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Indexing summary" in result.stdout

    @pytest.mark.timeout(300)
    def test_index_rebuild_flag_works(self, cli_vault: Path) -> None:
        """``vaultspec-rag index --type vault --rebuild`` exits zero."""
        root = str(cli_vault)
        with production_service(cli_vault):
            result = _run_cli(
                "--target",
                root,
                "index",
                "--type",
                "vault",
                "--rebuild",
                "--borrow-gpu",
                cwd=root,
            )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Vault" in result.stdout

    @pytest.mark.timeout(300)
    def test_index_code_produces_summary(self, cli_vault: Path) -> None:
        """``vaultspec-rag index --type code`` prints summary."""
        root = str(cli_vault)
        with production_service(cli_vault):
            result = _run_cli(
                "--target",
                root,
                "index",
                "--type",
                "code",
                "--borrow-gpu",
                cwd=root,
            )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Indexing summary" in result.stdout
        assert "Source code" in result.stdout

    @pytest.mark.timeout(300)
    def test_index_all_produces_both_rows(self, cli_vault: Path) -> None:
        """``vaultspec-rag index --type all`` shows Vault and Codebase."""
        root = str(cli_vault)
        with production_service(cli_vault):
            result = _run_cli(
                "--target",
                root,
                "index",
                "--type",
                "all",
                "--borrow-gpu",
                cwd=root,
            )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Vault" in result.stdout
        assert "Source code" in result.stdout


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
    def test_search_vault_returns_results(self, cli_vault: Path) -> None:
        """``vaultspec-rag search`` should return ranked results."""
        root = str(cli_vault)
        # Ensure indexed first. Local indexing needs the borrower lease, which
        # needs a live compatible service to quiesce, so the real route host
        # stands up for the index and is gone before the search: search is
        # service-first, and a discoverable host with no project loaded would
        # answer the query itself and return nothing, which is a different
        # subject from the local ranked search asserted below.
        with production_service(cli_vault):
            _run_cli(
                "--target",
                root,
                "index",
                "--type",
                "vault",
                "--borrow-gpu",
                cwd=root,
            )
        result = _run_cli(
            "--target",
            root,
            "search",
            "architecture decision",
            "--allow-fallback",
            cwd=root,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Score" in result.stdout or "0." in result.stdout

    @pytest.mark.timeout(300)
    def test_search_no_results_for_gibberish(self, cli_vault: Path) -> None:
        """Searching for nonsense should not crash."""
        root = str(cli_vault)
        result = _run_cli(
            "--target",
            root,
            "search",
            "xyzzy99plugh42foobarbaz",
            "--allow-fallback",
            cwd=root,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

    @pytest.mark.timeout(300)
    def test_search_code_type_exits_zero(self, cli_vault: Path) -> None:
        """``vaultspec-rag search --type code`` should exit cleanly."""
        root = str(cli_vault)
        result = _run_cli(
            "--target",
            root,
            "search",
            "function",
            "--type",
            "code",
            "--allow-fallback",
            cwd=root,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
