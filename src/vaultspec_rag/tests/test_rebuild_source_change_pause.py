"""A source that changes while its rebuild is paused never mixes epochs.

A real job manager runs a real code rebuild over real local storage. The only
substituted boundary is the encoder, which holds one encode so the pause and
the edit land after the rebuild has confirmed two files and while it is part-way
through the third. Nothing loads a model.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from .._publication_state import (
    acquire_publication_snapshot,
    read_all_publication_evidence,
)
from .._source_types import PublicSourceType
from ..indexer import CodebaseIndexer
from ..indexer._content_discovery import CodeContentDiscovery
from ..indexer._publication_proof import ProofProvenance
from ..indexer._rebuild_lifecycle import capture_reset_epoch
from ..indexer._run_ledger_models import RunAuthority
from ..job_dispatch import _AttemptDispatch, _bind_index_attempt
from ..job_manager.manager import JobManager
from ..job_manager.models import JobAttemptContext, JobExecutionResult
from ..job_models import (
    DesiredJobState,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ..progress import NullProgressReporter
from ..service import ServiceRegistry
from ..service_quiesce import ServiceQuiesceController
from ..store_runtime import VaultStore
from .test_code_pipeline_retained_ids import _CPUEncoder, _pipeline
from .test_code_rebuild_stale_evidence import _configure
from .test_job_rebuild_resume_dispatch import _until
from .test_live_checkpoint_resilience import unloaded_model

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..job_models import JobSnapshot

__all__ = ["unloaded_model"]
pytestmark = [pytest.mark.unit]

_WAIT_SECONDS = 20.0
_CHANGED = "changed-source-marker"


class _HoldingEncoder(_CPUEncoder):
    """The deterministic encoder boundary, able to hold one encode.

    It records every text it is asked to encode, so a test can tell which work
    a resumed attempt repeated.
    """

    def __init__(self, hold_call: int) -> None:
        self.hold_call = hold_call
        self.calls = 0
        self.encoded: list[str] = []
        self.holding = threading.Event()
        self.release = threading.Event()

    def encode_documents_on_device(
        self, texts: list[str], **options: object
    ) -> list[list[float]]:
        self.calls += 1
        if self.calls == self.hold_call:
            self.holding.set()
            assert self.release.wait(_WAIT_SECONDS), "the held encode was never freed"
        self.encoded.extend(texts)
        return super().encode_documents_on_device(texts, **options)


@dataclass
class _CodeRebuild:
    """A real job manager running real code rebuild attempts."""

    root: Path
    store: VaultStore
    indexer: CodebaseIndexer
    manager: JobManager
    encoder: _HoldingEncoder
    registry: ServiceRegistry
    job_id: str = ""

    def runner(self, context: JobAttemptContext) -> JobExecutionResult:
        """Bind the attempt exactly as dispatch does, against current source."""
        dispatch = _AttemptDispatch(
            JobSource.CODE,
            self.job_id,
            self.root,
            JobMode.REBUILD,
            RunAuthority.REBUILD,
            self.registry,
        )
        operation = _bind_index_attempt(
            context,
            dispatch,
            indexer=self.indexer,
            reporter=NullProgressReporter(),
            preflight=CodeContentDiscovery(self.root).preflight_content(),
        )
        operation()
        return JobExecutionResult(summary="rebuilt")

    def start(self) -> None:
        assert self.manager.bind_dispatch(self.job_id, self.runner).code == (
            "dispatch_bound"
        )
        assert self.manager.dispatch(self.job_id).code == "attempt_started"

    async def until(self, expected: JobState) -> JobSnapshot:
        def reached() -> bool:
            snapshot = self.manager.get(self.job_id)
            return snapshot is not None and snapshot.state is expected

        await _until(reached, expected.value)
        snapshot = self.manager.get(self.job_id)
        assert snapshot is not None
        return snapshot

    def stored_contents(self) -> list[str]:
        records, _next = self.store.client.scroll(
            self.store.CODE_TABLE_NAME, limit=100, with_payload=True
        )
        return sorted(str((record.payload or {})["content"]) for record in records)


@pytest.fixture
async def rebuild(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> AsyncGenerator[_CodeRebuild]:
    root = tmp_path / "corpus"
    root.mkdir()
    for name in ("a", "b", "c"):
        (root / f"{name}.py").write_text(
            f'def {name}():\n    return "{name}-original"\n', encoding="utf-8"
        )
    # One chunk per segment, slice and encode, so each file is its own durable
    # unit and the encoder sees them one at a time.
    _configure(
        "dense/model",
        None,
        index_segment_max_chunks=1,
        index_queue_max_chunks=1,
        embedding_code_encode_batch_size=1,
    )
    # Two files are confirmed before the third file's encode is held.
    encoder = _HoldingEncoder(hold_call=3)
    registry = ServiceRegistry()
    with VaultStore(root, embedding_dim=2) as store:
        indexer = CodebaseIndexer(root, unloaded_model, store)
        indexer._consumer_pipeline = _pipeline(root, store, indexer._lifecycle, encoder)
        manager = JobManager(
            quiesce_controller=ServiceQuiesceController(),
            max_nonterminal=2,
            state_path=tmp_path / "jobs.json",
        )
        built = _CodeRebuild(root, store, indexer, manager, encoder, registry)
        try:
            yield built
        finally:
            encoder.release.set()
            requested = manager.begin_shutdown()
            shutdown = await manager.wait_for_shutdown(
                requested, timeout_seconds=_WAIT_SECONDS
            )
            assert shutdown.clean


async def test_a_source_changed_during_a_pause_never_mixes_epochs(
    rebuild: _CodeRebuild,
) -> None:
    """The resume re-encodes only the changed source, in the same generation.

    The rebuild confirms two files and is held inside the third file's encode
    when the operator pauses it and the second confirmed file is edited. The
    resume continues the same generation over the same reset epoch: it does
    not encode the first confirmed file again, and no point of the second
    file as it was before the edit survives beside the new one.

    Mutation: making the drift owner's supersede neither delete the old
    points nor reopen the path left the old point beside the new one and
    failed the survival assertion; restoring it passed.
    """
    created = rebuild.manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            str(rebuild.root),
            JobMode.REBUILD,
            RunAuthority.REBUILD,
        ),
        JobInitiator("test", "source-change", str(rebuild.root)),
    )
    assert created.job is not None
    rebuild.job_id = created.job.id
    rebuild.start()
    await _until(rebuild.encoder.holding.is_set, "the third file's encode")
    assert len(rebuild.store.get_all_code_ids()) == 2, "two files are confirmed"
    kept, changed = (text.split(".py", 1)[0] for text in rebuild.encoder.encoded)

    assert rebuild.manager.set_desired_state(
        rebuild.job_id, DesiredJobState.PAUSED
    ).code in {"job_paused", "pause_requested"}
    (rebuild.root / f"{changed}.py").write_text(
        f'def {changed}():\n    return "{_CHANGED}"\n', encoding="utf-8"
    )
    rebuild.encoder.release.set()
    paused = await rebuild.until(JobState.PAUSED)
    generation_id = paused.rebuild_generation_id
    assert generation_id is not None
    began = capture_reset_epoch(
        rebuild.root, PublicSourceType.CODE, rebuild.store.backend_identity
    )
    assert (began.epoch, began.generation_id) == (1, generation_id)

    rebuild.encoder.encoded.clear()
    assert (
        rebuild.manager.set_desired_state(rebuild.job_id, DesiredJobState.RUNNING).code
        == "resume_requested"
    )
    finished = await rebuild.until(JobState.SUCCEEDED)

    assert finished.rebuild_generation_id == generation_id
    encoded = " ".join(rebuild.encoder.encoded)
    assert _CHANGED in encoded and f"{kept}-original" not in encoded, (
        "the resume repeated confirmed work or skipped the changed source"
    )
    contents = rebuild.stored_contents()
    assert len(contents) == 3, contents
    assert not any(f"{changed}-original" in content for content in contents), (
        "a point of the source as it was before the change survived the resume"
    )
    assert any(_CHANGED in content for content in contents)
    after = capture_reset_epoch(
        rebuild.root, PublicSourceType.CODE, rebuild.store.backend_identity
    )
    assert (after.epoch, after.generation_id) == (1, generation_id)
    snapshot = acquire_publication_snapshot(rebuild.root, PublicSourceType.CODE)
    assert snapshot.proof.provenance is ProofProvenance.VERIFIED
    assert snapshot.proof.generation_id == generation_id
    assert set(read_all_publication_evidence(snapshot)) == {"a.py", "b.py", "c.py"}
    snapshot.validate()
