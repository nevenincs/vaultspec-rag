"""Document admission and reads reject filesystem aliases to ignored inputs."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
import textwrap
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ..config._settings import get_config
from ..indexer._chunk_worker import (
    DocumentChunkingOptions,
    stream_document_and_hash_file,
)
from ..indexer._content_discovery import CodeContentDiscovery
from ..indexer._content_policy import (
    AdmissionReason,
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._document_file import DocumentFileMetadata
from ..indexer._document_indexer import DocumentIndexer
from ..indexer._preprocess_config import PreprocessContext, load_preprocess_rules
from ..indexer._source_file import SourceIdentityError
from ..job_control import NO_RUN_CONTROL
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore
from ._preprocess_approval import approve_preprocess_policy
from .test_live_checkpoint_resilience import unloaded_model

if TYPE_CHECKING:
    from pathlib import Path

    from ..embeddings import EmbeddingModel

__all__ = ["unloaded_model"]
pytestmark = [pytest.mark.unit]

_SECRET = "fixture_sensitive_value = 'fixture only'\n"


def _policy(pattern: str = "docs/*.md") -> RootContentPolicy:
    return RootContentPolicy(
        SourceProfileVersion.CONVENTIONAL_V1,
        (ContentRoute(pattern, ContentKind.DOCUMENT),),
    )


def _indexer(root: Path, pattern: str = "docs/*.md") -> DocumentIndexer:
    return DocumentIndexer.for_preflight(root, content_policy=_policy(pattern))


def _docs(root: Path) -> Path:
    docs = root / "docs"
    docs.mkdir()
    return docs


def _write_blob_rule(root: Path, command: str, *, extra: str = "") -> None:
    (root / ".vaultragpreprocess.toml").write_text(
        "version = 2\n\n"
        '[[rule]]\npattern = "*.blob"\n'
        f"command = '''{command}'''\n"
        'target = "document"\nextractor_version = "1"\non_error = "skip"\n'
        f"{extra}",
        encoding="utf-8",
    )


def _unit_vectors(texts: list[str], **_options: object) -> list[list[float]]:
    return [[1.0, 0.0] for _ in texts]


@pytest.fixture
def local_model(unloaded_model: EmbeddingModel) -> EmbeddingModel:
    """Real encoder state over local storage, with no forward available."""
    get_config(
        {
            "embedding_dimension": 2,
            "qdrant_url": None,
            "sparse_enabled": False,
            "reranker_enabled": False,
            "index_reuse_enabled": False,
        }
    )
    return unloaded_model


@pytest.fixture
def forwardless_model(
    local_model: EmbeddingModel, monkeypatch: pytest.MonkeyPatch
) -> EmbeddingModel:
    """The same model with only the device forward replaced.

    The model is built without weights, so a real forward cannot run here, and
    the case that takes this fixture needs points a real index pass stored. The
    stand-in returns one fixed vector per text. Nothing asserts on a vector:
    the assertions read which paths, content and counts the pass left behind.
    """
    monkeypatch.setattr(local_model, "encode_documents_on_device", _unit_vectors)
    return local_model


@pytest.mark.parametrize("target_name", [".env", ".git/config", "private/notes.md"])
@pytest.mark.parametrize("chained", [False, True])
def test_discovery_rejects_ignored_target_alias(
    tmp_path: Path, target_name: str, chained: bool
) -> None:
    """Admitting the alias on its name alone failed membership; the gate passed."""
    target = tmp_path / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_SECRET, encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\nprivate/\n", encoding="utf-8")
    docs = _docs(tmp_path)
    alias = docs / "environment.md"
    alias.symlink_to(target)
    if chained:
        (docs / "outer.md").symlink_to(alias)
    ordinary = docs / "guide.md"
    ordinary.write_text("ordinary guide\n", encoding="utf-8")

    preflight = _indexer(tmp_path).preflight_content()

    assert preflight.files == (ordinary,), (
        "symlink aliases must not enter document membership"
    )


def test_scan_reports_document_alias_as_a_failed_probe(tmp_path: Path) -> None:
    """Classifying the alias by name alone reported it admitted; the probe passed."""
    target = tmp_path / ".env"
    target.write_text(_SECRET, encoding="utf-8")
    docs = _docs(tmp_path)
    alias = docs / "environment.md"
    alias.symlink_to(target)
    (docs / "guide.md").write_text("ordinary guide\n", encoding="utf-8")

    scan = CodeContentDiscovery(tmp_path, content_policy=_policy()).scan_admission()

    samples = {sample.path: sample for sample in scan.samples}
    rejected = samples["docs/environment.md"]
    assert rejected.kind is ContentKind.DOCUMENT
    assert not rejected.admitted, "a dry run must not report an alias as admitted"
    assert rejected.reason is AdmissionReason.SOURCE_PROBE_FAILED
    assert samples["docs/guide.md"].admitted
    assert samples["docs/guide.md"].kind is ContentKind.DOCUMENT


@pytest.mark.parametrize("target_kind", ["safe", "outside", "missing"])
def test_discovery_rejects_other_file_link_targets(
    tmp_path: Path, target_kind: str
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    docs = _docs(root)
    target = tmp_path / "outside.md" if target_kind == "outside" else docs / "target.md"
    if target_kind != "missing":
        target.write_text("ordinary guide\n", encoding="utf-8")
    (docs / "alias.md").symlink_to(target)

    preflight = _indexer(root).preflight_content()

    assert preflight.files == ((target,) if target_kind == "safe" else ())


def test_full_preflight_rejects_source_replaced_by_link(tmp_path: Path) -> None:
    """Dropping the canonical check accepted the link; restoring it refused."""
    docs = _docs(tmp_path)
    source = docs / "guide.md"
    source.write_text("ordinary guide\n", encoding="utf-8")
    target = tmp_path / ".env"
    target.write_text(_SECRET, encoding="utf-8")
    indexer = _indexer(tmp_path)
    preflight = indexer.preflight_content()
    assert preflight.files == (source,)
    source.unlink()
    source.symlink_to(target)

    with pytest.raises(ValueError, match="non-canonical source"):
        indexer._accept_preflight(
            preflight, changed_paths=None, run_control=NO_RUN_CONTROL
        )


def test_full_preflight_rejects_forged_link_membership(tmp_path: Path) -> None:
    docs = _docs(tmp_path)
    target = tmp_path / ".env"
    target.write_text(_SECRET, encoding="utf-8")
    alias = docs / "environment.md"
    alias.symlink_to(target)
    indexer = _indexer(tmp_path)
    forged = replace(indexer.preflight_content(), files=(alias,))

    with pytest.raises(ValueError, match="non-canonical source"):
        indexer._accept_preflight(
            forged, changed_paths=None, run_control=NO_RUN_CONTROL
        )


def test_full_preflight_rejects_forged_outside_link(tmp_path: Path) -> None:
    """The containment branch still names an outside target as outside."""
    root = tmp_path / "project"
    root.mkdir()
    docs = _docs(root)
    target = tmp_path / "outside.md"
    target.write_text("outside fixture content\n", encoding="utf-8")
    alias = docs / "outside.md"
    alias.symlink_to(target)
    indexer = _indexer(root)
    forged = replace(indexer.preflight_content(), files=(alias,))

    with pytest.raises(ValueError, match="outside its root"):
        indexer._accept_preflight(
            forged, changed_paths=None, run_control=NO_RUN_CONTROL
        )


@pytest.mark.parametrize("directory_alias", [False, True])
def test_worker_rejects_link_created_after_preflight(
    tmp_path: Path, directory_alias: bool
) -> None:
    """Unguarded reads yielded the protected chunk; guarded reads yielded none."""
    docs = _docs(tmp_path)
    source = docs / "guide.md"
    source.write_text("ordinary guide\n", encoding="utf-8")
    private = tmp_path / "private"
    private.mkdir()
    target = private / "guide.md"
    target.write_text(_SECRET, encoding="utf-8")
    source.unlink()
    if directory_alias:
        docs.rmdir()
        docs.symlink_to(private, target_is_directory=True)
    else:
        source.symlink_to(target)

    result = stream_document_and_hash_file(source, tmp_path)

    assert result.content_hash == "unpublished", "a link must not be hashed"
    assert result.preprocess_status == "skipped"
    assert result.preprocess_reason is not None
    assert list(result.chunks) == []


def test_swap_between_validation_and_chunk_read_yields_nothing(
    tmp_path: Path,
) -> None:
    """A document is read twice: once to fix its identity, once to chunk it.

    Opening the second read by name alone yielded the protected chunk before
    the trailing hash comparison could object; the guarded open yielded none.
    """
    docs = _docs(tmp_path)
    source = docs / "guide.md"
    raw = b"ordinary guide\n"
    source.write_bytes(raw)
    target = tmp_path / ".env"
    target.write_text(_SECRET, encoding="utf-8")

    result = stream_document_and_hash_file(source, tmp_path)
    assert result.content_hash == hashlib.blake2b(raw).hexdigest()
    source.unlink()
    source.symlink_to(target)
    leaked: list[str] = []
    refusal: BaseException | None = None
    try:
        leaked.extend(chunk.payload.content for chunk in result.chunks)
    except (OSError, RuntimeError) as exc:
        refusal = exc

    assert leaked == [], "a swapped source must yield no protected chunks"
    assert isinstance(refusal, SourceIdentityError)


def test_extractor_is_not_launched_on_a_link(tmp_path: Path) -> None:
    """Hashing by name alone launched the extractor on the target; the gate did not."""
    marker = tmp_path / "launched.txt"
    extractor = tmp_path / "extract.py"
    extractor.write_text(
        textwrap.dedent(f"""
            import json, pathlib, sys
            pathlib.Path({str(marker)!r}).write_text("launched", encoding="utf-8")
            print(json.dumps({{
                "schema_version": 1,
                "preprocessor_id": "fixture-extractor",
                "preprocessor_version": "1",
                "source_path": sys.argv[1],
                "text": pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"),
            }}))
        """),
        encoding="utf-8",
    )
    _write_blob_rule(
        tmp_path,
        f"{shlex.quote(sys.executable)} {shlex.quote(str(extractor))} {{path}}",
    )
    target = tmp_path / ".env"
    target.write_text(_SECRET, encoding="utf-8")
    alias = tmp_path / "manual.blob"
    alias.symlink_to(target)
    context = PreprocessContext(
        config=load_preprocess_rules(tmp_path, strict=True),
        cache_root=tmp_path / "cache",
        max_emitted_bytes=64 * 1024,
        project_root=tmp_path,
    )

    result = stream_document_and_hash_file(
        alias, tmp_path, DocumentChunkingOptions(prep=context)
    )

    assert not marker.exists(), "an extractor must never be handed a link"
    assert list(result.chunks) == []
    assert result.content_hash == "unpublished"
    assert result.preprocess_status == "skipped"


def test_incremental_selection_refuses_to_digest_a_link(tmp_path: Path) -> None:
    """A digest opened by name alone hashed the target; the bound digest refused."""
    docs = _docs(tmp_path)
    target = tmp_path / ".env"
    target.write_text(_SECRET, encoding="utf-8")
    alias = docs / "guide.md"
    alias.symlink_to(target)
    previous = {
        "docs/guide.md": DocumentFileMetadata("docs/guide.md", "prior", ("point",))
    }

    with pytest.raises(OSError, match="non-canonical source"):
        _indexer(tmp_path)._select_incremental_paths((alias,), previous, scoped=False)


def test_incremental_removes_points_of_document_replaced_by_link(
    tmp_path: Path, forwardless_model: EmbeddingModel
) -> None:
    """Treating a link as a present file kept its points; the gate removed them."""
    secret = tmp_path / ".env"
    secret.write_text(_SECRET, encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    docs = _docs(tmp_path)
    guide = docs / "guide.md"
    guide.write_text("Ordinary document guide.", encoding="utf-8")
    (docs / "environment.md").symlink_to(secret)
    with VaultStore(tmp_path, embedding_dim=2) as store:
        indexer = DocumentIndexer(
            tmp_path, forwardless_model, store, content_policy=_policy()
        )
        indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        rows, _ = store.scroll_document_content(limit=10)
        assert [row["payload"]["source_path"] for row in rows] == ["docs/guide.md"]
        assert rows[0]["payload"]["content"] == "Ordinary document guide."

        guide.unlink()
        guide.symlink_to(secret)
        outcome = indexer.incremental_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        rows, _ = store.scroll_document_content(limit=10)
        assert rows == [], "a document replaced by a link must leave no points"
        assert (outcome.removed, outcome.preprocess_skipped) == (1, 0)


def test_refused_source_is_reported_as_one_failed_file(
    tmp_path: Path, local_model: EmbeddingModel
) -> None:
    """A source refused before it is read carries a placeholder, not a digest.

    Handing the placeholder to the ledger raised on its digest shape and ended
    the run; recording no digest reported the one file and finished. A refused
    source has nothing to encode, so the model here has no forward at all.
    """
    _write_blob_rule(
        tmp_path,
        f"{shlex.quote(sys.executable)} -c pass {{path}}",
        extra="max_source_bytes = 4\n",
    )
    # Approved, so the source is refused for its size and not for a withheld
    # approval.
    approve_preprocess_policy(tmp_path)
    (tmp_path / "manual.blob").write_bytes(b"longer than four bytes")
    with VaultStore(tmp_path, embedding_dim=2) as store:
        indexer = DocumentIndexer(
            tmp_path, local_model, store, content_policy=_policy("*.blob")
        )

        outcome = indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )

        assert outcome.preprocess_failures == [
            "manual.blob: source exceeds max_source_bytes=4"
        ]
        assert store.count_document() == 0


def test_regular_document_keeps_hash_chunks_and_preflight(tmp_path: Path) -> None:
    docs = _docs(tmp_path)
    source = docs / "guide.md"
    raw = b"ordinary guide\r\nsecond line\r\n"
    source.write_bytes(raw)
    indexer = _indexer(tmp_path)
    preflight = indexer.preflight_content()
    _policy_snapshot, paths = indexer._accept_preflight(
        preflight, changed_paths=None, run_control=NO_RUN_CONTROL
    )

    result = stream_document_and_hash_file(source, tmp_path)

    assert paths == (source,)
    assert result.content_hash == hashlib.blake2b(raw).hexdigest()
    assert "".join(chunk.payload.content for chunk in result.chunks) == (
        raw.decode("utf-8").replace("\r\n", "\n")
    )
    assert result.preprocess_status is None


def test_symlinked_project_root_keeps_regular_document(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = _docs(project) / "guide.md"
    source.write_text("ordinary guide\n", encoding="utf-8")
    alias = tmp_path / "project-alias"
    alias.symlink_to(project, target_is_directory=True)
    indexer = _indexer(alias)
    _policy_snapshot, paths = indexer._accept_preflight(
        indexer.preflight_content(), changed_paths=None, run_control=NO_RUN_CONTROL
    )

    assert paths == (source,)
    assert list(stream_document_and_hash_file(source, project).chunks)


@pytest.mark.parametrize("directory_alias", [False, True])
def test_open_time_replacement_cannot_supply_worker_bytes(
    tmp_path: Path, directory_alias: bool
) -> None:
    """Disabling opened-object checks leaked the chunk; restoring them did not.

    An audit hook schedules real filesystem replacement at the open syscall of
    the chunk read, after that read's own inspection passed; the child contains
    its process-wide hook. The earlier identity read is left alone, because a
    swap there is caught by the chunk read's inspection whatever the open does.
    """
    script = textwrap.dedent(
        """
        import json, os, sys
        from pathlib import Path
        from vaultspec_rag.indexer._chunk_worker import stream_document_and_hash_file

        root = Path(sys.argv[1])
        directory_alias = sys.argv[2] == 'True'
        docs = root / 'docs'
        docs.mkdir()
        source = docs / 'guide.md'
        source.write_text('ordinary guide\\n', encoding='utf-8')
        private = root / 'private'
        private.mkdir()
        target = private / source.name
        target.write_text('fixture_sensitive_value = 1\\n', encoding='utf-8')
        replaced = False
        opens = 0

        def intercept(event, args):
            global replaced, opens
            if event != 'open' or replaced:
                return
            name = args[0]
            trigger = str(source) if os.name == 'nt' else (
                'docs' if directory_alias else source.name
            )
            if name != trigger:
                return
            opens += 1
            if opens < 2:
                return
            replaced = True
            if directory_alias:
                docs.rename(root / 'original')
                docs.symlink_to(private, target_is_directory=True)
            else:
                source.unlink()
                source.symlink_to(target)

        sys.addaudithook(intercept)
        chunks = []
        try:
            result = stream_document_and_hash_file(source, root)
            for chunk in result.chunks:
                chunks.append(chunk.payload.content)
        except (OSError, RuntimeError):
            pass
        print(json.dumps({'replaced': replaced, 'chunks': chunks}))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), str(directory_alias)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(completed.stdout)
    assert result["replaced"], "the source replacement must reach the open syscall"
    assert result["chunks"] == [], "opened aliases must not yield protected chunks"
