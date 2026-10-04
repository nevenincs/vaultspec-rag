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
from typing import TYPE_CHECKING, cast

import pytest
from vaultspec_core.config import (
    reset_config,
)

from .._source_types import PublicSourceType
from ..indexer import CodebaseIndexer
from ..indexer import _config_epoch as ce
from ..indexer._run_ledger_models import (
    RunOperation,
    RunSignature,
    RunTerminalState,
)
from ..indexer._run_ledger_runtime import RunLedger
from ..progress import NullProgressReporter
from ._config_fixtures import reset_config as reset_rag_config

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


def _make_indexer(root: Path) -> CodebaseIndexer:
    """Build an indexer with no model/store - enough for config-epoch paths."""
    return CodebaseIndexer(
        root,
        cast("EmbeddingModel", None),
        cast("VaultStore", None),
    )


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


@pytest.mark.parametrize("ignore_location", ["root", "nested", "rag"])
def test_unreachable_gitignore_does_not_change_membership(
    tmp_path: Path, ignore_location: str
) -> None:
    parent = tmp_path / "src" if ignore_location == "nested" else tmp_path
    parent.mkdir(exist_ok=True)
    ignore_file = (
        tmp_path / ".vaultragignore"
        if ignore_location == "rag"
        else parent / ".gitignore"
    )
    ignore_file.write_text("output/\n", encoding="utf-8")
    (parent / "kept.py").write_text("kept = True\n", encoding="utf-8")
    indexer = _make_indexer(tmp_path)
    before = indexer.resolve_policy_snapshot()

    excluded = parent / "output" / "generated"
    excluded.mkdir(parents=True)
    (excluded / ".gitignore").write_text("*.poison.py\n", encoding="utf-8")
    after = indexer.resolve_policy_snapshot()

    # Removing project/RAG pruning admits this unreachable pattern and changes
    # the fingerprint; the mutation must fail this equality assertion.
    assert after.fingerprints == before.fingerprints
    assert not any("poison" in pattern for pattern in after.gitignore_patterns)


def test_reachable_nested_gitignore_changes_membership(tmp_path: Path) -> None:
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    indexer = _make_indexer(tmp_path)
    before = indexer.resolve_policy_snapshot()
    (nested / ".gitignore").write_text("*.generated.py\n", encoding="utf-8")
    after = indexer.resolve_policy_snapshot()

    assert after.fingerprints != before.fingerprints
    assert "src/pkg/*.generated.py" in after.gitignore_patterns


def test_directory_negation_keeps_nested_ignore_reachable(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("output/*\n!output/kept/\n", encoding="utf-8")
    kept = tmp_path / "output" / "kept"
    kept.mkdir(parents=True)
    (kept / ".gitignore").write_text("*.generated.py\n", encoding="utf-8")
    policy = _make_indexer(tmp_path).resolve_policy_snapshot()

    assert "output/kept/*.generated.py" in policy.gitignore_patterns
