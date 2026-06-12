"""CLI tests for the managed Qdrant operator surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_config_around_each_test() -> Iterator[None]:
    reset_config()
    yield
    reset_config()


def _labels(output: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        label, value = line.split(":", 1)
        labels[label] = value.strip()
    return labels


def test_server_start_help_exposes_qdrant_options_in_operator_language() -> None:
    result = runner.invoke(app, ["server", "start", "--help"])

    assert result.exit_code == 0, result.output
    assert "--qdrant" in result.output
    assert "--qdrant-auto-provision" in result.output
    assert "managed Qdrant server" in result.output
    for old_term in ("pinned Rust", "binary", "loopback child"):
        assert old_term not in result.output


def test_qdrant_help_uses_managed_server_language() -> None:
    result = runner.invoke(app, ["server", "qdrant", "--help"])

    assert result.exit_code == 0, result.output
    assert "managed Qdrant server" in result.output
    assert "install" in result.output
    assert "status" in result.output
    assert "clean" in result.output
    for old_term in ("supervised qdrant server binary", "pinned", "bin dir"):
        assert old_term not in result.output


def test_qdrant_status_is_operator_facing_when_not_installed(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "server",
            "qdrant",
            "status",
        ],
        env={EnvVar.STATUS_DIR.value: str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    labels = _labels(result.output)
    assert labels["Version"]
    assert labels["Install"] == "not installed"
    assert labels["Address"].startswith("http://127.0.0.1:")
    assert labels["State"].startswith("Qdrant is not answering on http://127.0.0.1:")
    assert labels["Managed process"] == "none recorded"
    assert labels["Installed versions"] == "none"
    assert "vaultspec-rag server qdrant install" in result.output
    for old_term in (
        "Pinned version",
        "Active binary",
        "Server ready",
        "Service child",
    ):
        assert old_term not in result.output


def test_qdrant_install_dry_run_uses_install_language(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "server",
            "qdrant",
            "install",
            "--dry-run",
        ],
        env={EnvVar.STATUS_DIR.value: str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    labels = _labels(result.output)
    assert labels["Action"] == "dry run"
    assert labels["Version"]
    assert labels["Release package"]
    assert labels["Download"].startswith("https://github.com/qdrant/qdrant/")
    assert labels["Install"]
    assert "Binary:" not in result.output
    assert "Asset:" not in result.output
    assert "URL:" not in result.output
