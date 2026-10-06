"""Real-policy coverage for model-free document dry runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._public_index import scan_documents
from ..config._types import EnvVar
from ..indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME
from ._preprocess_approval import approve_preprocess_policy
from .conftest import managed_env

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


def test_document_scan_says_whether_the_routed_rules_will_run(
    tmp_path: Path,
    isolated_status_dir: Path,
) -> None:
    """The mode alone cannot answer it: an unapproved root is in default mode.

    Mutation check: reporting the hook state from the mode and rule count
    alone calls this unapproved root active and fails here; reading it off
    the resolved policy passes.
    """
    del isolated_status_dir
    root = tmp_path / "root"
    root.mkdir()
    (root / PREPROCESS_CONFIG_FILENAME).write_text(
        'version = 2\n\n[[rule]]\npattern = "*.bin"\ncommand = "extract {path}"\n'
        'target = "document"\nextractor_version = "1"\n',
        encoding="utf-8",
    )
    (root / "first.bin").write_bytes(b"one")

    with managed_env(**{EnvVar.PREPROCESS.value: None}):
        withheld = scan_documents(root)
        approve_preprocess_policy(root)
        approved = scan_documents(root)

    assert (withheld.execution_mode, withheld.preprocess_rule_count) == ("default", 1)
    assert withheld.preprocess_hooks == "unapproved"
    assert approved.preprocess_hooks == "active"
