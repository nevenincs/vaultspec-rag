"""CLI integration tests for vaultspec-rag against a synthetic vault.

Each test gets a fresh vault root via session fixture so the CLI
subprocess can open its own Qdrant client without lock contention.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, NamedTuple

import pytest

from .._production_service import production_service
from ..conftest import release_owner_anchor
from ..corpus import build_synthetic_vault

if TYPE_CHECKING:
    from collections.abc import Generator
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


class _IndexRuns(NamedTuple):
    """The two local index runs every test below reads."""

    rebuild: subprocess.CompletedProcess[str]
    incremental: subprocess.CompletedProcess[str]


@pytest.fixture(scope="module")
def index_runs(
    cli_vault: Path, tmp_path_factory: TempPathFactory
) -> Generator[_IndexRuns]:
    """Index the vault locally twice: a rebuild, then an incremental pass.

    Each local index run is a process that loads the model set for itself, the
    costliest thing in this module by far, so the two runs happen once and
    every test reads what they printed and what they left indexed.

    Local GPU indexing is reached the way an operator reaches it: ``index``
    delegates to a running service, and running the work locally instead
    requires ``--borrow-gpu`` plus a live compatible service to quiesce. So the
    real authenticated route host stands up in this process and is published
    through the production discovery writer at the status dir the subprocess
    reads; the subprocess's own coordinator discovers it, pauses it, and only
    then indexes. Nothing is rehearsed: a refusal from the borrower gate
    reaches no summary at all and fails every assertion below. The host is
    gone before any search runs: search is service-first, and a discoverable
    host with no project loaded would answer the query itself and return
    nothing, which is a different subject from the local ranked search.
    """
    root = str(cli_vault)
    anchor = tmp_path_factory.mktemp("cli-owner") / "gpu-owner.lock"
    try:
        with production_service(cli_vault, gpu_owner_anchor=anchor):
            rebuild = _run_cli(
                "--target",
                root,
                "index",
                "--type",
                "all",
                "--rebuild",
                "--borrow-gpu",
                cwd=root,
            )
            incremental = _run_cli(
                "--target", root, "index", "--type", "all", "--borrow-gpu", cwd=root
            )
        yield _IndexRuns(rebuild, incremental)
    finally:
        release_owner_anchor(anchor)


class TestCLIStatus:
    """Tests for ``vaultspec-rag status``."""

    @pytest.mark.unit
    @pytest.mark.timeout(60)
    def test_status_shows_gpu_info(self, cli_vault: Path) -> None:
        """``vaultspec-rag status`` names the compute this machine offers."""
        root = str(cli_vault)
        result = _run_cli("--target", root, "status", cwd=root)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Compute: " in result.stdout
        assert "Unavailable" not in result.stdout

    @pytest.mark.unit
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
    """Tests for ``vaultspec-rag index`` run locally under a GPU borrow."""

    def test_a_rebuild_indexes_both_sources(self, index_runs: _IndexRuns) -> None:
        """``index --type all --rebuild`` exits zero and reports each source."""
        result = index_runs.rebuild
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Vault" in result.stdout
        assert "Source code" in result.stdout

    def test_an_incremental_pass_prints_a_summary_of_both_sources(
        self, index_runs: _IndexRuns
    ) -> None:
        """``index --type all`` over a published index prints its summary."""
        result = index_runs.incremental
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Indexing summary" in result.stdout
        assert "Vault" in result.stdout
        assert "Source code" in result.stdout


@pytest.mark.subprocess_gpu
class TestCLISearch:
    """Tests for ``vaultspec-rag search`` answered locally.

    Each search is a process that loads its own models, so these must not share
    a session with tests that hold a model set resident.
    """

    @pytest.mark.timeout(300)
    def test_search_vault_returns_results(
        self, cli_vault: Path, index_runs: _IndexRuns
    ) -> None:
        """``vaultspec-rag search`` should return ranked results."""
        assert index_runs.rebuild.returncode == 0, index_runs.rebuild.stderr
        root = str(cli_vault)
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
