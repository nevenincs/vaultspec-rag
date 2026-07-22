"""Real-policy coverage for model-free document dry runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._public_index import scan_documents
from ..indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_document_scan_is_bounded_and_uses_explicit_policy(tmp_path: Path) -> None:
    (tmp_path / PREPROCESS_CONFIG_FILENAME).write_text(
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
    (tmp_path / "first.bin").write_bytes(b"one")
    (tmp_path / "second.bin").write_bytes(b"two")
    (tmp_path / "source.py").write_text("print('code')", encoding="utf-8")

    result = scan_documents(tmp_path, sample_limit=1)
    assert result.total_files == 2
    assert result.sampled_paths == ("first.bin",)
    assert result.truncated
    assert result.preprocess_rule_count == 1
    assert result.execution_mode in {"default", "off"}
    assert result.membership_fingerprint
    assert result.content_fingerprint
    assert result.policy_snapshot
