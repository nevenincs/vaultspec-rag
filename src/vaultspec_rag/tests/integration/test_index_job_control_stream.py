# ruff: noqa: E402
"""Real-behavior integration coverage for cooperative indexing control.

The tests use the production streaming and indexing paths with local Qdrant,
real vault and code files, and the session's real GPU embedding model. Control
is observed at production checkpoints rather than raced against a particular
encode duration, so no test implementation stands in for indexing behavior.
"""

from __future__ import annotations

import contextlib
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, cast

import pytest

from ..._publication_state import acquire_publication_snapshot
from ..._source_types import PublicSourceType
from ...embeddings import EmbeddingModel  # noqa: TC001
from ...indexer import CodebaseIndexer, DocumentIndexer, VaultIndexer
from ...indexer._streaming import _stream_encode_and_upsert_vault
from ...indexer._streaming_types import VaultStreamRequest
from ...job_control import (
    CancelRequested,
    ControlRequest,
    PauseRequested,
    RunControlSignal,
    RunControlToken,
)
from ...progress import NullProgressReporter
from ...store_runtime import VaultStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import FrameType

    from ...indexer._run_ledger_runtime import RunLedger
    from ...indexer._vault_prep import IndexResult

pytestmark = pytest.mark.integration

_CONTROL_WAIT_SECONDS = 20.0
# Generous on purpose. These waits bound a real job - process-pool chunking, a
# real encode of the whole corpus, then publication - on whatever machine the
# suite happens to run on. A bound tuned to an idle machine turns ordinary load
# into a failure, and a suite that fails under load cannot be used to judge
# whether a change regressed anything: the A/B it is asked for returns noise.
# Sixty seconds was such a bound; a passing run of the managed rebuild took
# 68.8s wall-clock on a host also running the resident daemon. The only thing
# these should catch is a job that has genuinely stopped making progress.
_MANAGED_WAIT_SECONDS = 240.0
_CONTROL_POLL_SECONDS = 0.001

from ._index_job_control_support import (
    request_after_first_upsert,
    write_vault_documents,
)


@pytest.mark.parametrize(
    ("control_request", "signal_type"),
    [
        pytest.param(ControlRequest.PAUSE, PauseRequested, id="pause"),
        pytest.param(ControlRequest.CANCEL, CancelRequested, id="cancel"),
    ],
)
def test_vault_stream_observes_control_between_published_slices(
    tmp_path: Path,
    index_control_model: EmbeddingModel,
    control_request: ControlRequest,
    signal_type: type[RunControlSignal],
) -> None:
    """Pause and cancel stop real streaming only at a safe slice boundary."""
    documents = write_vault_documents(tmp_path, 128)
    token = RunControlToken()

    with VaultStore(tmp_path, embedding_dim=index_control_model.dimension) as store:
        store.ensure_table()
        with ThreadPoolExecutor(max_workers=1) as executor:
            requester = executor.submit(
                request_after_first_upsert,
                store,
                token,
                control_request,
            )
            with pytest.raises(signal_type):
                _stream_encode_and_upsert_vault(
                    VaultStreamRequest(
                        docs=documents,
                        slice_size=1,
                        model=index_control_model,
                        store=store,
                        gpu_lock=None,
                        reporter=NullProgressReporter(),
                        run_control=token,
                    )
                )
            requester.result(timeout=_CONTROL_WAIT_SECONDS)

        published = store.count()
        assert 0 < published < len(documents)
        assert token.snapshot().delivered is control_request


@dataclass
class _RebuildTrace:
    """Observe actual durable commits and real encoder inputs without replacing them."""

    token: RunControlToken | None = None
    request: ControlRequest = ControlRequest.PAUSE
    ledger: RunLedger | None = None
    generation_id: str | None = None
    texts: list[str] = field(default_factory=list)

    def observe(self, frame: FrameType, event: str, _arg: object):
        if event == "call" and frame.f_code.co_name == "encode_documents_on_device":
            self.texts.extend(cast("list[str]", frame.f_locals["texts"]))
        if (
            event == "return"
            and frame.f_code.co_name == "record_storage_confirmed_units"
            and self.generation_id is None
        ):
            self.ledger = cast("RunLedger", frame.f_locals["self"])
            self.generation_id = str(frame.f_locals["generation_id"])
            if self.token is not None:
                if self.request is ControlRequest.PAUSE:
                    assert self.token.request_pause()
                else:
                    assert self.token.request_cancel()
        return self.observe

    @contextlib.contextmanager
    def installed(self) -> Generator[None]:
        previous, previous_thread = sys.gettrace(), threading.gettrace()
        try:
            sys.settrace(self.observe)
            threading.settrace(self.observe)
            yield
        finally:
            sys.settrace(previous)
            threading.settrace(previous_thread)


def _rebuild_corpus(root: Path, source: PublicSourceType) -> dict[str, str]:
    markers: dict[str, str] = {}
    if source is PublicSourceType.VAULT:
        directory = root / ".vault" / "adr"
        directory.mkdir(parents=True)
    else:
        directory = root
    for ordinal in range(32):
        marker = f"unique_resume_marker_{ordinal:03d}"
        if source is PublicSourceType.VAULT:
            path = directory / f"item-{ordinal:03d}.md"
            content = f"---\ntype: adr\ntitle: Resume\n---\n# Resume\n\n{marker}\n"
            rel = f"adr/{path.stem}"
        elif source is PublicSourceType.CODE:
            path = directory / f"item_{ordinal:03d}.py"
            content = f"def value_{ordinal}():\n    return '{marker}'\n"
            rel = path.name
        else:
            path = directory / f"item-{ordinal:03d}.txt"
            content = f"Resume document {marker}\n"
            rel = path.name
        path.write_text(content, encoding="utf-8")
        markers[rel] = marker
    return markers


def _full_rebuild(
    indexer: CodebaseIndexer | DocumentIndexer | VaultIndexer,
    token: RunControlToken,
) -> IndexResult:
    if isinstance(indexer, CodebaseIndexer):
        return indexer.full_index(
            clean=True,
            reporter=NullProgressReporter(),
            run_control=token,
            preflight=indexer.preflight_content(),
        )
    return indexer.full_index(
        clean=True,
        reporter=NullProgressReporter(),
        run_control=token,
    )


@pytest.mark.parametrize(
    "source", [PublicSourceType.VAULT, PublicSourceType.CODE, PublicSourceType.DOCUMENT]
)
@pytest.mark.parametrize(
    "control_request,signal",
    [(ControlRequest.PAUSE, PauseRequested), (ControlRequest.CANCEL, CancelRequested)],
)
def test_clean_rebuild_interrupts_and_resumes_confirmed_units(
    tmp_path: Path,
    index_control_model: EmbeddingModel,
    source: PublicSourceType,
    control_request: ControlRequest,
    signal: type[RunControlSignal],
) -> None:
    """Control stops early; retry retains points and skips confirmed encoding.

    Restoring whole-run vault protection failed the partial-unit assertion
    (32 < 32); removing that protection passed the same pause case.
    """
    from ..._store_models import generation_code_collection
    from ._helpers import _document_policy

    markers = _rebuild_corpus(tmp_path, source)
    token = RunControlToken()
    with VaultStore(tmp_path, embedding_dim=index_control_model.dimension) as store:
        if source is PublicSourceType.CODE:
            indexer = CodebaseIndexer(tmp_path, index_control_model, store)
        elif source is PublicSourceType.DOCUMENT:
            indexer = DocumentIndexer(
                tmp_path,
                index_control_model,
                store,
                content_policy=_document_policy("*.txt"),
            )
        else:
            indexer = VaultIndexer(tmp_path, index_control_model, store)
        trace = _RebuildTrace(token=token, request=control_request)
        with trace.installed(), pytest.raises(signal):
            _full_rebuild(indexer, token)
        assert token.snapshot().delivered is control_request
        assert trace.ledger is not None and trace.generation_id is not None
        units = list(trace.ledger.iter_units(trace.generation_id))
        assert 0 < len(units) < len(markers)
        collection = {
            PublicSourceType.VAULT: store.TABLE_NAME,
            PublicSourceType.CODE: generation_code_collection(
                store.DERIVED_CODE_TABLE_NAME, trace.generation_id
            ),
            PublicSourceType.DOCUMENT: store.DOCUMENT_TABLE_NAME,
        }[source]
        records, offset = store._scroll(
            collection_name=collection, limit=100, with_payload=True
        )
        assert offset is None
        confirmed = {
            str(store._stable_id(point)) for unit in units for point in unit.point_ids
        }
        assert confirmed <= {str(record.id) for record in records}
        resumed = _RebuildTrace()
        with resumed.installed():
            _full_rebuild(indexer, RunControlToken())
        proof = acquire_publication_snapshot(tmp_path, source).proof
        assert proof.generation_id == trace.generation_id
        assert proof.aggregate.retained_points == len(markers)
        assert resumed.texts
        encoded = "\n".join(resumed.texts)
        assert all(markers[unit.rel_path] not in encoded for unit in units)
        collection = (
            store._code_collection(None)
            if source is PublicSourceType.CODE
            else collection
        )
        records, offset = store._scroll(
            collection_name=collection, limit=100, with_payload=True
        )
        assert offset is None
        assert len(records) == len(markers)
        assert confirmed <= {str(record.id) for record in records}


@pytest.mark.parametrize("source_change", ["grow", "shrink", "delete"])
def test_vault_full_resume_reconciles_changed_partial_source(
    tmp_path: Path, index_control_model: EmbeddingModel, source_change: str
) -> None:
    """A paused partial document may change or disappear before the same run resumes."""
    from ..._publication_state import read_all_publication_evidence

    markers = _rebuild_corpus(tmp_path, PublicSourceType.VAULT)
    path = tmp_path / ".vault" / "adr" / "item-000.md"
    old_content = "---\ntype: adr\ntitle: Partial\n---\n# Partial\n\n" + (
        "old partial source text " * 1500
    )
    path.write_text(old_content, encoding="utf-8")
    token = RunControlToken()
    with VaultStore(tmp_path, embedding_dim=index_control_model.dimension) as store:
        indexer = VaultIndexer(tmp_path, index_control_model, store)
        trace = _RebuildTrace(token=token)
        with trace.installed(), pytest.raises(PauseRequested):
            _full_rebuild(indexer, token)
        assert trace.ledger is not None and trace.generation_id is not None
        units = list(trace.ledger.iter_units(trace.generation_id))
        assert units and all(unit.rel_path == "adr/item-000" for unit in units)
        assert not trace.ledger.file_complete(trace.generation_id, "adr/item-000")
        if source_change == "delete":
            path.unlink()
        else:
            text = "replacement source text " * (2000 if source_change == "grow" else 1)
            path.write_text(
                "---\ntype: adr\ntitle: Changed\n---\n# Changed\n\n" + text,
                encoding="utf-8",
            )
        _full_rebuild(indexer, RunControlToken())
        snapshot = acquire_publication_snapshot(tmp_path, PublicSourceType.VAULT)
        assert snapshot.proof.generation_id == trace.generation_id
        evidence = read_all_publication_evidence(snapshot)
        assert len(evidence) == len(markers) - (source_change == "delete")
        records, offset = store._scroll(
            collection_name=store.TABLE_NAME, limit=100, with_payload=True
        )
        assert offset is None
        assert {str(record.id) for record in records} == {
            str(store._stable_id(point))
            for item in evidence.values()
            for point in item.point_ids
        }
        content = "\n".join(
            str((record.payload or {}).get("content", "")) for record in records
        )
        assert "old partial source text" not in content
        if source_change != "delete":
            assert "replacement source text" in content
