"""Unit tests for the config-epoch drift sentinels (no GPU).

Covers two layers: the pure hashing functions in
``vaultspec_rag.indexer._config_epoch`` (the mechanism), and the
``CodebaseIndexer`` drift-classification wiring over real tmp roots (the
escalation matrix). None of these paths embed, so no GPU or vector store is
constructed - the classification methods operate on the resolved config alone.
"""

from collections.abc import Generator
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, Unpack, cast

import pytest
from vaultspec_core.config import (
    reset_config,
)

from .._source_types import PublicSourceType
from ..config._settings import reset_config as reset_rag_config
from ..indexer import CodebaseIndexer
from ..indexer import _config_epoch as ce
from ..indexer._content_policy import ContentKind
from ..indexer._preprocess_config import OnError, PreprocessRule
from ..indexer._run_ledger_models import (
    RunOperation,
    RunSignature,
    RunTerminalState,
)
from ..indexer._run_ledger_runtime import RunLedger
from ..progress import NullProgressReporter

if TYPE_CHECKING:
    from ..embeddings import EmbeddingModel
    from ..store_runtime import VaultStore

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _reset_cfg() -> Generator[None]:  # pyright: ignore[reportUnusedFunction]
    reset_config()
    reset_rag_config()
    yield
    reset_config()
    reset_rag_config()


class _RuleOverrides(TypedDict, total=False):
    command: str | None
    entry_point: str | None
    on_error: OnError
    priority: int
    timeout_s: float | None
    options: dict[str, object] | None
    order: int


def _rule(pattern: str, **overrides: Unpack[_RuleOverrides]) -> PreprocessRule:
    return PreprocessRule(
        pattern=pattern,
        command=overrides.get("command", "extract {path}"),
        entry_point=overrides.get("entry_point"),
        priority=overrides.get("priority", 100),
        target=ContentKind.DOCUMENT,
        extractor_version="1.0",
        on_error=overrides.get("on_error", "skip"),
        timeout_s=overrides.get("timeout_s", 120.0),
        options=overrides.get("options") or {},
        order=overrides.get("order", 0),
    )


def _make_indexer(root: Path) -> CodebaseIndexer:
    """Build an indexer with no model/store - enough for config-epoch paths."""
    return CodebaseIndexer(
        root,
        cast("EmbeddingModel", None),
        cast("VaultStore", None),
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


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        pytest.param("model_identity", "model-v2", id="model"),
        pytest.param("dense_dimensions", 16, id="dimensions"),
        pytest.param("embedding_schema", 3, id="embedding-schema"),
        pytest.param("payload_schema", 4, id="payload-schema"),
        pytest.param("content_epoch", "content-v2", id="content"),
        pytest.param("membership_epoch", "membership-v2", id="membership"),
        pytest.param(
            "preprocessing_identity",
            "preprocessing-v2",
            id="preprocessing",
        ),
        pytest.param(
            "configuration_fingerprint",
            "configuration-v2",
            id="configuration",
        ),
    ],
)
def test_checkpoint_signature_drift_invalidates_before_reuse(
    tmp_path: Path,
    field: str,
    replacement: str | int,
) -> None:
    """Every content- or storage-shaping signature change fails closed."""
    ledger = RunLedger(tmp_path / "code-runs.sqlite3")
    signature = RunSignature(
        root_identity=str(tmp_path.resolve()),
        collection_identity="codebase-v1",
        source_type=PublicSourceType.CODE,
        operation=RunOperation.FULL,
        clean=False,
        model_identity="model-v1",
        backend_identity="test-backend:config-epoch",
        dense_dimensions=8,
        embedding_schema=2,
        payload_schema=3,
        content_epoch="content-v1",
        membership_epoch="membership-v1",
        preprocessing_identity="preprocessing-v1",
        configuration_fingerprint="configuration-v1",
        policy_fingerprint="policy-v1",
    )
    active = ledger.start_generation(signature)

    changed = ledger.start_generation(replace(signature, **{field: replacement}))

    assert changed.generation_id != active.generation_id
    assert (
        ledger.generation(active.generation_id).terminal_state
        is RunTerminalState.INVALIDATED
    )


class TestScopedSnapshot:
    def test_scoped_scan_uses_resolved_ignore_snapshot(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        indexer = _make_indexer(tmp_path)
        policy = indexer.resolve_policy_snapshot()
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
        policy = indexer.resolve_policy_snapshot()
        indexer._begin_preprocess_run(policy)
        to_hash, deleted = indexer._scan_changed_paths(
            [tmp_path / "a.py"], NullProgressReporter(), policy
        )
        assert not to_hash
        assert deleted == {"a.py"}
