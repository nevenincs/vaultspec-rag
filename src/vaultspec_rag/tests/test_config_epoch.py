"""Unit tests for the config-epoch drift sentinels (no GPU).

Covers two layers: the pure hashing functions in
``vaultspec_rag.indexer._config_epoch`` (the mechanism), and the
``CodebaseIndexer`` drift-classification wiring over real tmp roots (the
escalation matrix). None of these paths embed, so no GPU or vector store is
constructed - the classification methods operate on the resolved config alone.
"""

import json
import os
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
    reset_config,
)

from ..config import EnvVar
from ..config import reset_config as reset_rag_config
from ..indexer import CodebaseIndexer
from ..indexer import _config_epoch as ce
from ..indexer._content_policy import ContentKind
from ..indexer._preprocess_config import OnError, PreprocessRule
from ..progress import NullProgressReporter

if TYPE_CHECKING:
    from ..embeddings import EmbeddingModel
    from ..store import VaultStore

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _reset_cfg() -> Generator[None]:  # pyright: ignore[reportUnusedFunction]
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()
    yield
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()


def _rule(
    pattern: str,
    *,
    command: str | None = "extract {path}",
    entry_point: str | None = None,
    on_error: OnError = "skip",
    priority: int = 100,
    timeout_s: float | None = 120.0,
    options: dict[str, object] | None = None,
    order: int = 0,
) -> PreprocessRule:
    return PreprocessRule(
        pattern=pattern,
        command=command,
        entry_point=entry_point,
        priority=priority,
        target=ContentKind.DOCUMENT,
        extractor_version="1.0",
        on_error=on_error,
        timeout_s=timeout_s,
        options=options or {},
        order=order,
    )


def _make_indexer(root: Path) -> CodebaseIndexer:
    """Build an indexer with no model/store - enough for config-epoch paths."""
    return CodebaseIndexer(
        root,
        cast("EmbeddingModel", None),
        cast("VaultStore", None),
    )


def _stamp(indexer: CodebaseIndexer) -> tuple[str, str]:
    """Resolve current epochs and persist a sidecar stamped with them."""
    policy = indexer._resolve_operation_policy()
    membership, content = indexer._compute_code_epochs(policy)
    indexer._membership_epoch = membership
    indexer._content_epoch = content
    indexer._write_meta(
        {"anchor.py": "0" * 128},
        policy=policy,
    )
    return membership, content


def _classify_current(indexer: CodebaseIndexer) -> str:
    policy = indexer._resolve_operation_policy()
    membership, content = indexer._compute_code_epochs(policy)
    return indexer._classify_config_drift(membership, content)


def _write_preprocess_rule(
    root: Path,
    *,
    pattern: str,
    command: str,
    target: ContentKind = ContentKind.DOCUMENT,
) -> None:
    """Write one real versioned preprocessing rule for drift coverage."""
    (root / ".vaultragpreprocess.toml").write_text(
        "\n".join(
            (
                "version = 2",
                "[[rule]]",
                f"pattern = {json.dumps(pattern)}",
                f"command = {json.dumps(command)}",
                f"target = {json.dumps(target.value)}",
                'extractor_version = "1.0"',
                "",
            )
        ),
        encoding="utf-8",
    )


class TestMembershipEpochFunction:
    def test_changes_across_gitignore_reorder(self) -> None:
        a = ce.code_membership_epoch(
            gitignore_patterns=["a/", "b/", "c/"],
            vaultragignore_patterns=[],
            preprocess_rules=[],
        )
        b = ce.code_membership_epoch(
            gitignore_patterns=["c/", "a/", "b/"],
            vaultragignore_patterns=[],
            preprocess_rules=[],
        )
        assert a != b

    def test_changes_on_gitignore_pattern_add(self) -> None:
        a = ce.code_membership_epoch(
            gitignore_patterns=["a/"],
            vaultragignore_patterns=[],
            preprocess_rules=[],
        )
        b = ce.code_membership_epoch(
            gitignore_patterns=["a/", "b/"],
            vaultragignore_patterns=[],
            preprocess_rules=[],
        )
        assert a != b

    def test_changes_on_vaultragignore_pattern(self) -> None:
        a = ce.code_membership_epoch(
            gitignore_patterns=[],
            vaultragignore_patterns=["secret.py"],
            preprocess_rules=[],
        )
        b = ce.code_membership_epoch(
            gitignore_patterns=[],
            vaultragignore_patterns=[],
            preprocess_rules=[],
        )
        assert a != b

    def test_changes_on_preprocess_pattern(self) -> None:
        a = ce.code_membership_epoch(
            gitignore_patterns=[],
            vaultragignore_patterns=[],
            preprocess_rules=[_rule("*.pdf")],
        )
        b = ce.code_membership_epoch(
            gitignore_patterns=[],
            vaultragignore_patterns=[],
            preprocess_rules=[_rule("*.docx")],
        )
        assert a != b

    def test_ignores_command_change(self) -> None:
        # The command is a content input, not a membership one.
        a = ce.code_membership_epoch(
            gitignore_patterns=[],
            vaultragignore_patterns=[],
            preprocess_rules=[_rule("*.pdf", command="a {path}")],
        )
        b = ce.code_membership_epoch(
            gitignore_patterns=[],
            vaultragignore_patterns=[],
            preprocess_rules=[_rule("*.pdf", command="b {path}")],
        )
        assert a == b


class TestContentEpochFunction:
    def test_changes_on_command(self) -> None:
        a = ce.code_content_epoch(
            preprocess_rules=[_rule("*.pdf", command="a {path}")],
            html_strip=True,
            max_emitted_bytes=10,
        )
        b = ce.code_content_epoch(
            preprocess_rules=[_rule("*.pdf", command="b {path}")],
            html_strip=True,
            max_emitted_bytes=10,
        )
        assert a != b

    def test_ignores_pattern_change(self) -> None:
        # The pattern is a membership input; the content epoch must not move.
        a = ce.code_content_epoch(
            preprocess_rules=[_rule("*.pdf", command="x {path}")],
            html_strip=True,
            max_emitted_bytes=10,
        )
        b = ce.code_content_epoch(
            preprocess_rules=[_rule("*.docx", command="x {path}")],
            html_strip=True,
            max_emitted_bytes=10,
        )
        assert a == b

    def test_changes_on_html_strip(self) -> None:
        a = ce.code_content_epoch(
            preprocess_rules=[], html_strip=True, max_emitted_bytes=10
        )
        b = ce.code_content_epoch(
            preprocess_rules=[], html_strip=False, max_emitted_bytes=10
        )
        assert a != b

    def test_changes_on_options(self) -> None:
        a = ce.code_content_epoch(
            preprocess_rules=[_rule("*.pdf", options={"mode": "fast"})],
            html_strip=True,
            max_emitted_bytes=10,
        )
        b = ce.code_content_epoch(
            preprocess_rules=[_rule("*.pdf", options={"mode": "slow"})],
            html_strip=True,
            max_emitted_bytes=10,
        )
        assert a != b

    def test_changes_on_on_error_and_timeout_and_order(self) -> None:
        base = ce.code_content_epoch(
            preprocess_rules=[_rule("*.pdf")],
            html_strip=True,
            max_emitted_bytes=10,
        )
        on_error = ce.code_content_epoch(
            preprocess_rules=[_rule("*.pdf", on_error="fail")],
            html_strip=True,
            max_emitted_bytes=10,
        )
        timeout = ce.code_content_epoch(
            preprocess_rules=[_rule("*.pdf", timeout_s=30.0)],
            html_strip=True,
            max_emitted_bytes=10,
        )
        order = ce.code_content_epoch(
            preprocess_rules=[_rule("*.pdf", order=3)],
            html_strip=True,
            max_emitted_bytes=10,
        )
        assert len({base, on_error, timeout, order}) == 4

    def test_changes_on_max_emitted_bytes(self) -> None:
        # The emitted-text cap re-truncates oversized extractions, so a cap
        # change is content-shaping for unchanged bytes.
        a = ce.code_content_epoch(
            preprocess_rules=[], html_strip=True, max_emitted_bytes=10
        )
        b = ce.code_content_epoch(
            preprocess_rules=[], html_strip=True, max_emitted_bytes=20
        )
        assert a != b


class TestVaultContentEpochFunction:
    def test_changes_on_chunk_chars(self) -> None:
        assert ce.vault_content_epoch(vault_chunk_chars=3000) != ce.vault_content_epoch(
            vault_chunk_chars=2000
        )

    def test_stable_for_same_chunk_chars(self) -> None:
        assert ce.vault_content_epoch(vault_chunk_chars=3000) == ce.vault_content_epoch(
            vault_chunk_chars=3000
        )


class TestCodeDriftClassification:
    def test_no_drift_is_ok(self, tmp_path: Path) -> None:
        indexer = _make_indexer(tmp_path)
        _stamp(indexer)
        assert _classify_current(indexer) == "ok"

    def test_fresh_index_without_sidecar_is_ok(self, tmp_path: Path) -> None:
        indexer = _make_indexer(tmp_path)
        assert _classify_current(indexer) == "ok"

    def test_newly_ignored_file_forces_unscoped(self, tmp_path: Path) -> None:
        (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "drop.py").write_text("y = 2\n", encoding="utf-8")
        indexer = _make_indexer(tmp_path)
        _stamp(indexer)
        # A newly-ignored file changes the membership epoch only.
        (tmp_path / ".vaultragignore").write_text("drop.py\n", encoding="utf-8")
        assert _classify_current(indexer) == "unscoped"

    def test_newly_admitted_file_forces_unscoped(self, tmp_path: Path) -> None:
        ignore = tmp_path / ".vaultragignore"
        ignore.write_text("drop.py\n", encoding="utf-8")
        indexer = _make_indexer(tmp_path)
        _stamp(indexer)
        # Removing the ignore pattern re-admits the file: membership drift.
        ignore.write_text("\n", encoding="utf-8")
        assert _classify_current(indexer) == "unscoped"

    def test_html_strip_flip_forces_clean(self, tmp_path: Path) -> None:
        indexer = _make_indexer(tmp_path)
        _stamp(indexer)
        name = EnvVar.HTML_STRIP.value
        previous = os.environ.get(name)
        try:
            os.environ[name] = "0"
            reset_rag_config()
            assert _classify_current(indexer) == "clean"
        finally:
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
            reset_rag_config()

    def test_legacy_sidecar_forces_unscoped_once(self, tmp_path: Path) -> None:
        indexer = _make_indexer(tmp_path)
        indexer._meta_path.parent.mkdir(parents=True, exist_ok=True)
        # A sidecar from before this feature: file hashes and the embed marker,
        # but neither epoch key.
        indexer._meta_path.write_text(
            json.dumps({"a.py": "0" * 128, "__code_embed_schema__": "2"}),
            encoding="utf-8",
        )
        assert _classify_current(indexer) == "unscoped"

    def test_preprocess_pattern_change_forces_unscoped(self, tmp_path: Path) -> None:
        indexer = _make_indexer(tmp_path)
        _write_preprocess_rule(tmp_path, pattern="*.pdf", command="x {path}")
        _stamp(indexer)
        _write_preprocess_rule(tmp_path, pattern="*.docx", command="x {path}")
        assert _classify_current(indexer) == "unscoped"

    def test_preprocess_command_change_forces_clean(self, tmp_path: Path) -> None:
        indexer = _make_indexer(tmp_path)
        _write_preprocess_rule(
            tmp_path,
            pattern="*.pdf",
            command="old {path}",
            target=ContentKind.CODE,
        )
        _stamp(indexer)
        _write_preprocess_rule(
            tmp_path,
            pattern="*.pdf",
            command="new {path}",
            target=ContentKind.CODE,
        )
        assert _classify_current(indexer) == "clean"


class TestScopedSnapshot:
    def test_scoped_scan_uses_resolved_ignore_snapshot(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        indexer = _make_indexer(tmp_path)
        policy = indexer._resolve_operation_policy()
        (tmp_path / ".vaultragignore").write_text("a.py\n", encoding="utf-8")
        indexer._begin_preprocess_run(policy)
        to_hash, _delete = indexer._scan_changed_paths(
            [tmp_path / "a.py"], NullProgressReporter(), policy
        )
        assert "a.py" in to_hash

    def test_fresh_snapshot_observes_new_ignore(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / ".vaultragignore").write_text("a.py\n", encoding="utf-8")
        indexer = _make_indexer(tmp_path)
        policy = indexer._resolve_operation_policy()
        indexer._begin_preprocess_run(policy)
        to_hash, deleted = indexer._scan_changed_paths(
            [tmp_path / "a.py"], NullProgressReporter(), policy
        )
        assert not to_hash
        assert deleted == {"a.py"}
