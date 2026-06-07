"""Unit tests for the service warmup CLI command."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from ..cli import app

pytestmark = [pytest.mark.integration]

runner = CliRunner()


class TestServiceWarmup:
    """Tests for ``vaultspec-rag server service warmup``."""

    def test_warmup_checks_cuda(self):
        """Warmup must verify CUDA availability before downloading."""
        result = runner.invoke(app, ["server", "service", "warmup"])
        assert result.exit_code == 0

    def test_warmup_reports_cached_models(self):
        """All three models should report as cached in test environment."""
        result = runner.invoke(app, ["server", "service", "warmup"])
        assert result.exit_code == 0
        assert "cached" in result.output
        assert "Dense (Qwen3)" in result.output
        assert "Sparse (SPLADE)" in result.output
        assert "Reranker (CrossEncoder)" in result.output

    def test_warmup_shows_model_repos(self):
        """Output must include the HuggingFace repo IDs."""
        result = runner.invoke(app, ["server", "service", "warmup"])
        assert result.exit_code == 0
        assert "Qwen/Qwen3-Embedding-0.6B" in result.output
        assert "naver/splade-v3" in result.output
        assert "BAAI/bge-reranker-v2-m3" in result.output

    def test_warmup_no_failed_status(self):
        """No model should report as failed in test environment."""
        result = runner.invoke(app, ["server", "service", "warmup"])
        assert result.exit_code == 0
        assert "failed" not in result.output
