"""Vault preparation reports each unit of progress inside its own phase."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest

from .. import _publication_state
from ..indexer import _vault_fingerprint, _vault_incremental
from ..indexer._run_ledger_models import RunAuthority
from ..indexer._run_policy import RunPolicy
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..indexer._vault_indexer import VaultIndexer
from ..job_models import JobProgress
from ..jobs import JobProgressReporter
from ..progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..store_runtime import VaultStore

pytestmark = pytest.mark.unit


class _StoreReachedError(Exception):
    """Raised when the run first needs the store, after hashing."""


class _StoreStandIn:
    """Answers the activity stamp, then stops the run at its first real use."""

    def touch_manifest_last_indexed(self) -> None:
        return None

    @property
    def backend_identity(self) -> str:
        raise _StoreReachedError


class _RecordingReporter(NullProgressReporter):
    def __init__(self) -> None:
        self.phases: list[tuple[str, int | None, int]] = []
        self.stray_advances = 0
        self._open = False

    def phase_start(self, name: str, total: int | None) -> None:
        self.phases.append((name, total, 0))
        self._open = True

    def advance(self, n: int = 1) -> None:
        if not self._open:
            self.stray_advances += n
            return
        name, total, done = self.phases[-1]
        self.phases[-1] = (name, total, done + n)

    def phase_end(self) -> None:
        self._open = False


def test_hashing_reports_its_progress_in_its_own_phase(tmp_path: Path) -> None:
    # The job reporter keeps publishing into the last phase until the next one
    # starts. Hashing ran after the parse phase closed, so its advances landed
    # on "parse documents", overran that phase's total, and every vault rebuild
    # logged a rejected progress update at ERROR. Mutation: removing the hash
    # phase fails the stray-advance assertion below.
    root = tmp_path.resolve()
    for index in range(3):
        doc = root / ".vault" / "adr" / f"2026-01-0{index + 1}-topic{index}-adr.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(
            "---\ntags:\n  - '#adr'\n"
            f"  - '#topic{index}'\ndate: '2026-01-0{index + 1}'\n---\n"
            f"# topic{index} adr\n\nBody {index}.\n",
            encoding="utf-8",
        )
    reporter = _RecordingReporter()
    indexer = VaultIndexer(
        root,
        cast("EmbeddingModel", object()),
        cast("VaultStore", _StoreStandIn()),
    )

    with pytest.raises(_StoreReachedError):
        indexer.full_index(reporter=reporter, authority=RunAuthority.REBUILD)

    assert reporter.stray_advances == 0
    assert ("hash documents", 3, 3) in reporter.phases
    for name, total, done in reporter.phases:
        assert total is None or done <= total, name


class _ValidatingJobReporter(JobProgressReporter):
    """Keep actual reporter counting and validate its publications without I/O."""

    def __init__(self) -> None:
        super().__init__("scoped-vault-progress")
        self.publications: list[JobProgress] = []
        self.rejections: list[tuple[str, int, int | None, str]] = []

    def _publish(self, step: str, *, completed: int, total: int | None) -> None:
        try:
            progress = JobProgress(step, completed, total, last_updated=0.0)
        except ValueError as exc:
            self.rejections.append((step, completed, total, str(exc)))
        else:
            self.publications.append(progress)


def _document_text(index: int, *, tags: str = "#sample", body: str = "Body") -> str:
    return (
        "---\ntags:\n  - '#adr'\n"
        f"  - '{tags}'\ndate: '2026-01-0{index + 1}'\n---\n"
        f"# topic{index} adr\n\n{body} {index}.\n"
    )


def _scoped_backend_seams(
    monkeypatch: pytest.MonkeyPatch,
    previous: dict[str, str],
) -> tuple[Mock, Mock, Mock]:
    store = Mock()
    store.backend_identity = "cpu-progress-backend"
    store.get_chunk_counts.return_value = dict.fromkeys(previous, 1)
    store.get_stored_chunk_ordinals.return_value = {doc_id: {0} for doc_id in previous}
    snapshot = Mock()
    snapshot.ledger.publication_evidence_for_paths.return_value = {
        doc_id: Mock(content_identity=digest) for doc_id, digest in previous.items()
    }
    monkeypatch.setattr(
        _publication_state, "acquire_publication_snapshot", Mock(return_value=snapshot)
    )
    checkpoint = Mock(spec=VaultRunCheckpoint)
    checkpoint.run_policy = RunPolicy(no_progress_timeout_seconds=60)
    checkpoint.receipt = Mock()
    checkpoint.ledger = Mock()
    checkpoint.ledger.publication_proof.return_value.aggregate.indexed_identities = len(
        previous
    )
    checkpoint.chunk_lifecycle.return_value = None
    monkeypatch.setattr(VaultRunCheckpoint, "open", Mock(return_value=checkpoint))
    monkeypatch.setattr(
        VaultRunCheckpoint, "recover_pending_publication", Mock(return_value=None)
    )
    return store, snapshot, checkpoint


@pytest.mark.parametrize("change", ["metadata-only", "unchanged", "mixed"])
def test_scoped_payload_preparation_owns_its_progress_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clean_config: None,
    change: str,
) -> None:
    del clean_config
    root = tmp_path.resolve()
    paths: list[Path] = []
    previous: dict[str, str] = {}
    for index in range(2):
        path = root / ".vault" / "adr" / f"2026-01-0{index + 1}-topic{index}-adr.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_document_text(index), encoding="utf-8")
        doc_id = path.relative_to(root / ".vault").with_suffix("").as_posix()
        previous[doc_id] = _vault_fingerprint.fingerprint_path(path, root)
        paths.append(path)
    if change == "metadata-only":
        for index, path in enumerate(paths):
            path.write_text(_document_text(index, tags="#changed"), encoding="utf-8")
    elif change == "mixed":
        paths[0].write_text(_document_text(0, tags="#changed"), encoding="utf-8")
        paths[1].write_text(_document_text(1, body="Changed body"), encoding="utf-8")

    store, snapshot, checkpoint = _scoped_backend_seams(monkeypatch, previous)
    indexer = VaultIndexer(
        root,
        cast("EmbeddingModel", Mock(device="cpu")),
        cast("VaultStore", store),
    )
    # Only donor/model/store work is replaced. The public scoped entry, hashes,
    # classification, threaded preparation and phase machinery are production.
    monkeypatch.setattr(indexer, "_resolve_reuse", Mock(return_value=(None, None)))
    model_store_stream = Mock(return_value={list(previous)[1]: 1})
    monkeypatch.setattr(
        _vault_incremental, "_stream_encode_and_upsert_vault", model_store_stream
    )
    reporter = _ValidatingJobReporter()
    result = indexer.incremental_index(reporter=reporter, changed_paths=paths)

    # Mutation: unwrapping the real metadata preparation phase publishes 3/2
    # and 4/2 into the completed hash phase for two metadata-only documents.
    assert not reporter.rejections, (
        "metadata preparation must not overflow the completed hash phase"
    )
    latest = {progress.step: progress for progress in reporter.publications}
    assert (latest["hash documents"].completed, latest["hash documents"].total) == (
        2,
        2,
    )
    metadata_count = {"metadata-only": 2, "unchanged": 0, "mixed": 1}[change]
    body_count = 1 if change == "mixed" else 0
    if metadata_count:
        preparation = latest["prepare payloads"]
        assert (preparation.completed, preparation.total) == (
            metadata_count,
            metadata_count,
        )
    else:
        assert "prepare payloads" not in latest
    assert (latest["parse documents"].completed, latest["parse documents"].total) == (
        body_count,
        body_count,
    )
    assert result.payload_updated == metadata_count
    assert result.updated == body_count
    assert result.added == result.removed == 0
    assert store.overwrite_vault_chunk_payloads.call_count == metadata_count
    assert checkpoint.record_confirmed_chunks.call_count == metadata_count
    assert model_store_stream.call_count == body_count
    if body_count:
        request = model_store_stream.call_args.args[0]
        assert [doc.id for doc in request.docs] == [list(previous)[1]]
    snapshot.validate.assert_called_once()
    checkpoint.publish_proof_transition.assert_called_once()
    checkpoint.publish_generation.assert_called_once()
