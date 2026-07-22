"""Real CLI coverage for the closed source-domain adapter surface."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ...indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME
from .._cli_helpers import app, runner

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def _workspace(root: Path) -> Path:
    (root / ".vault").mkdir()
    (root / ".vaultspec").mkdir()
    return root


def _route_documents(root: Path) -> None:
    (root / PREPROCESS_CONFIG_FILENAME).write_text(
        """
version = 2

[[rule]]
pattern = "*.bin"
command = "extract {path}"
target = "document"
extractor_version = "1"
""",
        encoding="utf-8",
    )


def test_document_and_combined_dry_runs_are_bounded_and_disjoint(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _route_documents(root)
    (root / "alpha.py").write_text("print('code')\n", encoding="utf-8")
    (root / "first.bin").write_bytes(b"first")
    (root / "second.bin").write_bytes(b"second")

    document = runner.invoke(
        app,
        [
            "--target",
            str(root),
            "index",
            "--type",
            "document",
            "--dry-run",
            "--dry-run-limit",
            "1",
            "--json",
        ],
    )
    assert document.exit_code == 0, document.output
    document_data = json.loads(document.output)["data"]
    assert document_data["count"] == 2
    assert document_data["files"] == ["first.bin"]
    assert document_data["truncated"] is True
    assert document_data["sources"]["code"] == {"count": 0, "files": []}
    assert document_data["sources"]["document"]["count"] == 2
    assert document_data["sources"]["document"]["files"] == ["first.bin"]

    combined = runner.invoke(
        app,
        [
            "--target",
            str(root),
            "index",
            "--type",
            "combined",
            "--dry-run",
            "--dry-run-limit",
            "1",
            "--json",
        ],
    )
    assert combined.exit_code == 0, combined.output
    combined_data = json.loads(combined.output)["data"]
    assert combined_data["count"] == 3
    assert combined_data["sources"]["code"] == {
        "count": 1,
        "files": ["alpha.py"],
    }
    assert combined_data["sources"]["document"]["count"] == 2
    assert "alpha.py" not in combined_data["sources"]["document"]["files"]


@pytest.mark.parametrize("command", ["index", "search", "clean"])
def test_unknown_source_type_is_a_structured_usage_error(
    tmp_path: Path,
    command: str,
) -> None:
    root = _workspace(tmp_path)
    if command == "index":
        args = ["index", "--type", "mystery", "--dry-run", "--json"]
    elif command == "search":
        args = ["search", "query", "--type", "mystery", "--json"]
    else:
        args = ["clean", "mystery", "--yes", "--json"]
    result = runner.invoke(app, ["--target", str(root), *args])
    assert result.exit_code == 2, result.output
    envelope = json.loads(result.output)
    assert envelope["ok"] is False
    assert envelope["error"] == "unknown_source_type"
    assert envelope["received"] == "mystery"
    assert envelope["allowed"] == ["vault", "code", "document", "combined"]


def test_legacy_docs_alias_remains_vault_not_document(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = runner.invoke(
        app,
        ["--target", str(root), "index", "--type", "docs", "--dry-run", "--json"],
    )
    assert result.exit_code == 2, result.output
    envelope = json.loads(result.output)
    assert envelope["error"] == "dry_run_requires_supported_type"


def test_empty_document_and_combined_search_are_real_model_free_cli_calls(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    for source in ("document", "combined"):
        result = runner.invoke(
            app,
            [
                "--target",
                str(root),
                "search",
                "query",
                "--type",
                source,
                "--allow-fallback",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["data"]["search_type"] == source
        assert envelope["data"]["results"] == []
        if source == "combined":
            assert envelope["data"]["partial"] is False
            assert set(envelope["data"]["domains"]) == {
                "vault",
                "code",
                "document",
            }


def test_clean_and_status_expose_document_domain_and_support_profile(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    cleaned = runner.invoke(
        app,
        ["--target", str(root), "clean", "document", "--yes", "--json"],
    )
    assert cleaned.exit_code == 0, cleaned.output
    clean_data = json.loads(cleaned.output)["data"]
    assert clean_data["clean_type"] == "document"
    assert clean_data["source"] == "document"

    status = runner.invoke(app, ["--target", str(root), "status", "--json"])
    assert status.exit_code == 0, status.output
    status_data = json.loads(status.output)["data"]
    assert status_data["document_chunks"] == 0
    profile = status_data["support_profile"]
    assert set(profile["domains"]) == {"code", "document"}
    for source in ("code", "document"):
        assert set(profile["domains"][source]) == {
            "source_files",
            "source_bytes",
            "generated_chunks",
            "weighted_bytes",
            "extracted_bytes",
            "queue_bytes",
            "rss_bytes",
            "cuda_bytes",
        }
