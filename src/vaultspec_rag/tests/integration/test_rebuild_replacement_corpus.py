"""A corpus rebuild discards the old index before its first replacement write.

Each case builds a real root over real local storage and a real run ledger,
then drives the production full-index entry of one content kind and observes
what storage held at the instant before the first replacement write, what it
holds afterwards, what publication certified, and what the sibling sources
kept.

The forward pass is the one component a CPU runner cannot drive, because this
project never runs inference on CPU. :class:`_ProbingEncoder` stands at that
boundary and nowhere else: it returns fixed vectors, and before the first
forward of a run it records what the rebuilt source's canonical collection
holds. Every encode is immediately followed by the slice's store write, so the
first record is the collection exactly as the first replacement write finds
it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from ..._publication_state import acquire_publication_snapshot
from ..._source_types import PublicSourceType
from ...config._settings import get_config
from ...indexer._codebase_indexer import CodebaseIndexer
from ...indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ...indexer._document_indexer import DocumentIndexer
from ...indexer._rebuild_lifecycle import CONCRETE_SOURCES, capture_reset_epoch
from ...indexer._run_ledger_models import RunAuthority, index_run_ledger_path
from ...indexer._run_ledger_runtime import RunLedger
from ...indexer._vault_indexer import VaultIndexer
from ...progress import NullProgressReporter
from ...store_runtime import VaultStore

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from ...embeddings import EmbeddingModel
    from ...indexer._run_ledger_models import PublicationProof, SourceResetState

pytestmark = [pytest.mark.integration]

_POLICY = RootContentPolicy(
    SourceProfileVersion.CONVENTIONAL_V1,
    (ContentRoute("docs/*.md", ContentKind.DOCUMENT),),
)


@dataclass
class _ProbingEncoder:
    """Fixed CPU vectors, and storage as the first replacement write finds it."""

    device: str = "cpu"
    probe: Callable[[], list[str]] | None = None
    before_first_write: list[str] | None = None
    forwards: int = field(default=0)

    def encode_documents_on_device(
        self, texts: list[str], **_options: object
    ) -> list[list[float]]:
        if self.probe is not None and self.before_first_write is None:
            self.before_first_write = self.probe()
        self.forwards += 1
        return [[0.0, 1.0] for _ in texts]

    def arm(self, probe: Callable[[], list[str]]) -> None:
        """Record what *probe* reads at the next run's first forward."""
        self.probe = probe
        self.before_first_write = None

    def encode_documents_sparse(
        self, texts: list[str], **_options: object
    ) -> list[None]:
        return [None for _ in texts]


@dataclass
class _Root:
    root: Path
    store: VaultStore
    encoder: _ProbingEncoder
    vault: VaultIndexer
    code: CodebaseIndexer
    document: DocumentIndexer

    def collection(self, source: PublicSourceType) -> str:
        if source is PublicSourceType.VAULT:
            return self.store.TABLE_NAME
        if source is PublicSourceType.CODE:
            return self.store.DERIVED_CODE_TABLE_NAME
        return self.store.DOCUMENT_TABLE_NAME

    def contents(self, source: PublicSourceType) -> list[str]:
        """Every stored payload of *source*'s canonical collection, as text."""
        collection = self.collection(source)
        if not self.store.client.collection_exists(collection):
            return []
        points, _ = self.store.client.scroll(
            collection, limit=10_000, with_payload=True, with_vectors=False
        )
        return [str(point.payload) for point in points]

    def full_index(self, source: PublicSourceType) -> None:
        reporter = NullProgressReporter()
        if source is PublicSourceType.VAULT:
            self.vault.full_index(clean=True, reporter=reporter)
        elif source is PublicSourceType.CODE:
            self.code.full_index(
                clean=True,
                reporter=reporter,
                preflight=self.code.preflight_content(),
            )
        else:
            self.document.full_index(
                clean=True,
                reporter=reporter,
                preflight=self.document.preflight_content(),
            )

    def incremental_index(self, source: PublicSourceType) -> None:
        reporter = NullProgressReporter()
        if source is PublicSourceType.VAULT:
            self.vault.incremental_index(reporter=reporter)
        elif source is PublicSourceType.CODE:
            self.code.incremental_index(
                reporter=reporter, preflight=self.code.preflight_content()
            )
        else:
            self.document.incremental_index(
                reporter=reporter, preflight=self.document.preflight_content()
            )

    def proof(self, source: PublicSourceType) -> PublicationProof:
        snapshot = acquire_publication_snapshot(self.root, source)
        proof = snapshot.proof
        snapshot.validate()
        return proof

    def reset_state(self, source: PublicSourceType) -> SourceResetState | None:
        from ..._store_writes import workspace_volume_path

        ledger = RunLedger(
            index_run_ledger_path(workspace_volume_path(self.root.resolve()))
        )
        return ledger.source_reset_state(
            source, str(self.root.resolve()), self.store.backend_identity
        )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _vault_doc(root: Path, name: str, body: str) -> Path:
    path = root / ".vault" / "adr" / f"2026-01-01-{name}-adr.md"
    _write(
        path,
        f"---\ntags:\n  - '#adr'\n  - '#{name}'\ndate: '2026-01-01'\n---\n"
        f"# {name} adr\n\n{body}\n",
    )
    return path


def _old_corpus(root: Path) -> dict[PublicSourceType, Path]:
    """Write a shared survivor and one old-only file for every content kind."""
    _vault_doc(root, "survivor", "Vault survivor body.")
    _write(root / "src" / "survivor.py", "def survivor():\n    return 1\n")
    _write(root / "docs" / "survivor.md", "# Survivor\n\nDocument survivor body.\n")
    return {
        PublicSourceType.VAULT: _vault_doc(root, "oldonly", "OLDVAULTMARKER body."),
        PublicSourceType.CODE: root / "src" / "old_only.py",
        PublicSourceType.DOCUMENT: root / "docs" / "old_only.md",
    }


def _write_old_only(paths: dict[PublicSourceType, Path]) -> None:
    _write(
        paths[PublicSourceType.CODE],
        'def old_only():\n    return "OLDCODEMARKER"\n',
    )
    _write(paths[PublicSourceType.DOCUMENT], "# Old\n\nOLDDOCUMENTMARKER body.\n")


def _replace_with_fresh(root: Path, source: PublicSourceType, old: Path) -> None:
    old.unlink()
    if source is PublicSourceType.VAULT:
        _vault_doc(root, "fresh", "FRESHVAULTMARKER body.")
    elif source is PublicSourceType.CODE:
        _write(
            root / "src" / "fresh.py", 'def fresh():\n    return "FRESHCODEMARKER"\n'
        )
    else:
        _write(root / "docs" / "fresh.md", "# Fresh\n\nFRESHDOCUMENTMARKER body.\n")


def _marker(source: PublicSourceType, age: str) -> str:
    return f"{age}{source.value.upper()}MARKER"


@pytest.fixture
def built_root(
    tmp_path: Path, isolated_singleton_dirs: Path
) -> Generator[tuple[_Root, dict[PublicSourceType, Path]]]:
    """A root whose three sources were each built once from the old corpus."""
    del isolated_singleton_dirs
    get_config(
        {
            "embedding_model": "fixed/dense",
            "embedding_dimension": 2,
            "sparse_enabled": False,
            "qdrant_url": None,
            "reranker_enabled": False,
            "index_reuse_enabled": False,
            "index_chunk_workers": 1,
        }
    )
    root = (tmp_path / "root").resolve()
    old_only = _old_corpus(root)
    _write_old_only(old_only)
    encoder = _ProbingEncoder()
    model = cast("EmbeddingModel", encoder)
    with VaultStore(root, embedding_dim=2) as store:
        built = _Root(
            root=root,
            store=store,
            encoder=encoder,
            vault=VaultIndexer(root, model, store),
            code=CodebaseIndexer(
                root,
                model,
                store,
                CodebaseIndexer.Options(content_policy=_POLICY),
            ),
            document=DocumentIndexer(root, model, store, content_policy=_POLICY),
        )
        for source in CONCRETE_SOURCES:
            built.full_index(source)
            assert any(
                _marker(source, "OLD") in text for text in built.contents(source)
            )
        yield built, old_only


@pytest.mark.parametrize("source", CONCRETE_SOURCES, ids=lambda s: s.value)
def test_explicit_rebuild_discards_first_and_certifies_its_own_collection(
    built_root: tuple[_Root, dict[PublicSourceType, Path]],
    source: PublicSourceType,
) -> None:
    """Old content is gone before the first write; completion certifies the same target.

    Mutation: removing the reset call from the indexer's full entry left the
    old corpus in place when the first replacement batch was encoded and
    failed the ``before_first_write`` assertion; restoring it passed.
    """
    built, old_only = built_root
    siblings = [kind for kind in CONCRETE_SOURCES if kind is not source]
    sibling_proofs = {kind: built.proof(kind) for kind in siblings}
    sibling_contents = {kind: sorted(built.contents(kind)) for kind in siblings}
    legacy = None
    if source is PublicSourceType.CODE:
        from ..._store_models import generation_code_collection

        # An interrupted build under the earlier layout left this behind.
        legacy = generation_code_collection(built.store.DERIVED_CODE_TABLE_NAME, "old")
        built.store.ensure_code_table(legacy)
    epoch_before = capture_reset_epoch(
        built.root, source, built.store.backend_identity
    ).epoch
    _replace_with_fresh(built.root, source, old_only[source])
    built.encoder.arm(lambda: built.contents(source))

    built.full_index(source)

    assert built.encoder.before_first_write == [], (
        "the first replacement write found content from before the rebuild"
    )
    after = built.contents(source)
    assert any(_marker(source, "FRESH") in text for text in after)
    assert not any(_marker(source, "OLD") in text for text in after)
    if source is PublicSourceType.CODE:
        assert built.store.owned_code_collections() == (
            built.store.DERIVED_CODE_TABLE_NAME,
        )
        assert built.store.CODE_TABLE_NAME == built.store.DERIVED_CODE_TABLE_NAME
        assert legacy is not None
        assert not built.store.client.collection_exists(legacy)
    reset = built.reset_state(source)
    assert reset is not None and reset.complete
    assert reset.epoch == epoch_before + 1
    proof = built.proof(source)
    assert proof.generation_id == reset.generation_id, (
        "completion certified a generation other than the one that reset"
    )
    assert proof.aggregate.retained_points == len(after)
    for kind in siblings:
        assert built.proof(kind) == sibling_proofs[kind], kind
        assert sorted(built.contents(kind)) == sibling_contents[kind], kind


@pytest.mark.parametrize("source", CONCRETE_SOURCES, ids=lambda s: s.value)
def test_incremental_run_never_resets(
    built_root: tuple[_Root, dict[PublicSourceType, Path]],
    source: PublicSourceType,
) -> None:
    """An incremental run updates in place and leaves the reset epoch alone.

    Mutation: adding a reset of the source to the incremental entry advanced
    the recorded epoch and failed the reset-state equality; restoring passed.
    """
    built, old_only = built_root
    before = built.reset_state(source)
    _replace_with_fresh(built.root, source, old_only[source])
    built.encoder.arm(lambda: built.contents(source))

    built.incremental_index(source)

    assert built.reset_state(source) == before
    assert built.encoder.before_first_write, (
        "the incremental run found its source emptied before it wrote"
    )
    assert any("survivor" in text for text in built.encoder.before_first_write)
    after = built.contents(source)
    assert any(_marker(source, "FRESH") in text for text in after)
    assert not any(_marker(source, "OLD") in text for text in after)


@pytest.mark.parametrize("source", CONCRETE_SOURCES, ids=lambda s: s.value)
def test_full_index_refuses_without_rebuild_authority(
    built_root: tuple[_Root, dict[PublicSourceType, Path]],
    source: PublicSourceType,
) -> None:
    """A full run is a rebuild; publication authority cannot reach it.

    Mutation: deleting the authority check let the full entry run and failed
    the ``pytest.raises``; restoring it passed.
    """
    built, _ = built_root
    reporter = NullProgressReporter()
    authority = RunAuthority.PUBLICATION
    contents = sorted(built.contents(source))
    with pytest.raises(PermissionError, match="requires rebuild authority"):
        if source is PublicSourceType.VAULT:
            built.vault.full_index(reporter=reporter, authority=authority)
        elif source is PublicSourceType.CODE:
            built.code.full_index(
                reporter=reporter,
                preflight=built.code.preflight_content(),
                authority=authority,
            )
        else:
            built.document.full_index(
                reporter=reporter,
                preflight=built.document.preflight_content(),
                authority=authority,
            )
    assert sorted(built.contents(source)) == contents
