"""Real-process coverage for bounded, independently retried document work."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import textwrap
import threading
import time
import tracemalloc
from dataclasses import replace
from typing import TYPE_CHECKING

import psutil
import pytest

from ..._job_errors import JobError, JobErrorKind
from ..._store_models import DocumentChunk, DocumentPayload
from ..._store_writes import VolumeReading
from ...index_profiles import (
    AdmissionEnvironment,
    IndexDomain,
    SupportMeasurement,
    get_index_support_profile,
    validate_profile_admission,
)
from ...indexer._chunk_worker import (
    DocumentChunkingOptions,
    DocumentFileChunkResult,
    chunk_document_and_hash_file,
    chunk_file_with_status,
    stream_document_and_hash_file,
)
from ...indexer._document_indexer import _DocumentResourceBudget
from ...indexer._preprocess_config import (
    PreprocessConfig,
    PreprocessContext,
    load_preprocess_rules,
)
from ...indexer._preprocess_runner import run_preprocessor
from ...indexer._run_policy import RunPolicy
from ...indexer._streaming import (
    DocumentSliceStreamRequest,
    iter_weighted_document_slices,
)
from ...job_control import CancelRequested, RunControlToken
from ...job_dispatch import _AttemptDispatch, _run_indexing_attempt
from ...job_manager.manager import JobManager
from ...job_manager.models import JobAttemptContext
from ...job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    job_spec_error,
)
from ...jobs import (
    validate_document_index_policy,
    validate_document_support_profile,
)
from ...service import ServiceRegistry
from ...service_quiesce import ServiceQuiesceController
from ...watcher_retry import WatcherRetryPolicy, WatcherSource, _WatcherRetryOptions
from ._helpers import _document_policy

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.integration]


def _command(script: Path) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{path}}"


def _write_rule(
    root: Path,
    *,
    command: str,
    on_error: str = "skip",
    max_source_bytes: int | None = None,
) -> None:
    source_limit = (
        "" if max_source_bytes is None else f"max_source_bytes = {max_source_bytes}\n"
    )
    (root / ".vaultragpreprocess.toml").write_text(
        "version = 2\n\n"
        '[[rule]]\npattern = "*.blob"\n'
        f"command = '''{command}'''\n"
        'target = "document"\nextractor_version = "1"\n'
        f'on_error = "{on_error}"\n'
        f"{source_limit}",
        encoding="utf-8",
    )


def _context(root: Path) -> PreprocessContext:
    return PreprocessContext(
        config=load_preprocess_rules(root, strict=True),
        cache_root=root / "cache",
        max_emitted_bytes=64 * 1024,
        project_root=root,
    )


def test_extractor_owned_binary_bypasses_decoder_and_source_cap_prevents_launch(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "launched.txt"
    extractor = tmp_path / "extract.py"
    extractor.write_text(
        textwrap.dedent(f"""
            import json, pathlib, sys
            pathlib.Path({str(marker)!r}).write_text("launched", encoding="utf-8")
            print(json.dumps({{
                "schema_version": 1,
                "preprocessor_id": "real-extractor",
                "preprocessor_version": "1",
                "source_path": sys.argv[1],
                "text": "decoded by the extractor",
            }}))
        """),
        encoding="utf-8",
    )
    source = tmp_path / "manual.blob"
    source.write_bytes(b"\x00\xff\xfe binary input")
    _write_rule(tmp_path, command=_command(extractor))
    context = _context(tmp_path)

    extracted = chunk_document_and_hash_file(
        source, tmp_path, DocumentChunkingOptions(prep=context)
    )

    assert isinstance(extracted, DocumentFileChunkResult)
    assert extracted.preprocess_status == "ok"
    assert [chunk.payload.content for chunk in extracted.chunks] == [
        "decoded by the extractor"
    ]
    assert marker.exists()

    marker.unlink()
    matched = context.config.match(source.name)
    assert matched is not None
    capped = PreprocessContext(
        config=PreprocessConfig([replace(matched, max_source_bytes=4)]),
        cache_root=tmp_path / "capped-cache",
        max_emitted_bytes=context.max_emitted_bytes,
        project_root=tmp_path,
    )
    refused = chunk_document_and_hash_file(
        source, tmp_path, DocumentChunkingOptions(prep=capped)
    )

    assert refused.preprocess_status == "skipped"
    assert refused.chunks == []
    assert refused.preprocess_reason == "source exceeds max_source_bytes=4"
    assert not marker.exists()


def test_document_passthrough_stays_document_owned_and_code_worker_fails_closed(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "attempted.txt"
    extractor = tmp_path / "fail.py"
    extractor.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('attempted')\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    source = tmp_path / "opaque.blob"
    source.write_bytes(b"\xff\xfe\x00")
    _write_rule(tmp_path, command=_command(extractor), on_error="passthrough")
    context = _context(tmp_path)

    result = chunk_document_and_hash_file(
        source, tmp_path, DocumentChunkingOptions(prep=context)
    )

    assert marker.exists()
    assert isinstance(result, DocumentFileChunkResult)
    assert result.preprocess_status is None
    assert result.chunks == []

    marker.unlink()
    with pytest.raises(ValueError, match="non-code extraction rule"):
        chunk_file_with_status(source, tmp_path, context)
    assert not marker.exists()


def test_raw_document_stream_is_memory_bounded_and_cooperatively_cancelled(
    tmp_path: Path,
) -> None:
    source = tmp_path / "large.txt"
    block = b"bounded raw document content\n" * 32_768
    with source.open("wb") as stream:
        for _ in range(24):
            stream.write(block)
    source_bytes = source.stat().st_size

    tracemalloc.start()
    try:
        result = stream_document_and_hash_file(source, tmp_path)
        chunk_count = sum(1 for _chunk in result.chunks)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert chunk_count > 1_000
    assert peak < source_bytes

    control = RunControlToken()
    cancelled = stream_document_and_hash_file(
        source,
        tmp_path,
        DocumentChunkingOptions(run_control=control),
    )
    control.request_cancel()
    with pytest.raises(CancelRequested):
        next(iter(cancelled.chunks))


def test_real_extractor_cancellation_terminates_child(tmp_path: Path) -> None:
    started = tmp_path / "started.pid"
    finished = tmp_path / "finished.txt"
    extractor = tmp_path / "sleep.py"
    extractor.write_text(
        textwrap.dedent(f"""
            import os, pathlib, time
            pathlib.Path({str(started)!r}).write_text(str(os.getpid()))
            time.sleep(30)
            pathlib.Path({str(finished)!r}).write_text("finished")
        """),
        encoding="utf-8",
    )
    source = tmp_path / "slow.blob"
    source.write_bytes(b"source")
    _write_rule(tmp_path, command=_command(extractor))
    rule = load_preprocess_rules(tmp_path, strict=True).match(source.name)
    assert rule is not None
    control = RunControlToken()
    outcome: dict[str, BaseException] = {}

    def _run() -> None:
        try:
            run_preprocessor(
                source,
                rule,
                max_emitted_bytes=4096,
                project_root=tmp_path,
                checkpoint=control.checkpoint,
            )
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=_run)
    thread.start()
    deadline = time.monotonic() + 5
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert started.exists()
    child_pid = int(started.read_text())
    control.request_cancel()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert isinstance(outcome.get("error"), CancelRequested)
    assert not finished.exists()
    deadline = time.monotonic() + 3
    while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not psutil.pid_exists(child_pid)


def test_real_extractor_no_progress_watchdog_terminates_child(tmp_path: Path) -> None:
    started = tmp_path / "watchdog-started.pid"
    finished = tmp_path / "watchdog-finished.txt"
    extractor = tmp_path / "watchdog_sleep.py"
    extractor.write_text(
        textwrap.dedent(f"""
            import os, pathlib, time
            pathlib.Path({str(started)!r}).write_text(str(os.getpid()))
            time.sleep(30)
            pathlib.Path({str(finished)!r}).write_text("finished")
        """),
        encoding="utf-8",
    )
    source = tmp_path / "watchdog.blob"
    source.write_bytes(b"source")
    _write_rule(tmp_path, command=_command(extractor))
    rule = load_preprocess_rules(tmp_path, strict=True).match(source.name)
    assert rule is not None
    policy = RunPolicy(no_progress_timeout_seconds=0.2)

    with pytest.raises(JobError) as caught:
        run_preprocessor(
            source,
            rule,
            max_emitted_bytes=4096,
            project_root=tmp_path,
            checkpoint=lambda: policy.checkpoint("extractor watchdog"),
        )

    assert caught.value.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
    assert started.exists()
    assert not finished.exists()
    child_pid = int(started.read_text())
    deadline = time.monotonic() + 3
    while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not psutil.pid_exists(child_pid)


@pytest.mark.asyncio
async def test_document_attempt_honors_cancellation_before_admission(
    tmp_path: Path,
) -> None:
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=1,
        state_path=None,
    )
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.DOCUMENT,
            str(tmp_path),
            JobMode.INCREMENTAL,
        ),
        JobInitiator("integration", "cancel before admission", str(tmp_path)),
    )
    assert created.job is not None
    task = asyncio.current_task()
    assert task is not None
    control = RunControlToken()
    control.request_cancel()
    context = JobAttemptContext(manager, created.job.id, 1, task, control)
    registry = ServiceRegistry()
    try:
        with pytest.raises(CancelRequested):
            _run_indexing_attempt(
                context,
                dispatch=_AttemptDispatch(
                    JobSource.DOCUMENT,
                    manager,
                    created.job.id,
                    tmp_path,
                    False,
                    registry,
                ),
            )
    finally:
        registry.close_all()


def test_document_admission_checkpoints_policy_and_measurement(
    tmp_path: Path,
) -> None:
    source = tmp_path / "record.txt"
    source.write_text("document admission cancellation", encoding="utf-8")

    policy_control = RunControlToken()
    policy_control.request_cancel()
    with pytest.raises(CancelRequested):
        validate_document_index_policy(
            tmp_path,
            run_control=policy_control,
        )

    preflight = validate_document_index_policy(tmp_path)
    measurement_control = RunControlToken()
    measurement_control.request_cancel()
    with pytest.raises(CancelRequested):
        validate_document_support_profile(
            tmp_path,
            preflight,
            run_control=measurement_control,
        )


def test_document_runtime_budget_enforces_extracted_rss_and_cuda_dimensions() -> None:
    limits = get_index_support_profile("managed-service").document
    extracted_budget = _DocumentResourceBudget(
        replace(limits, extracted_bytes=4),
    )
    with pytest.raises(JobError, match="extracted_bytes") as extracted:
        extracted_budget.reserve(1, 1, 5)
    assert extracted.value.error_kind is JobErrorKind.CORPUS_LIMIT_EXCEEDED

    runtime_budget = _DocumentResourceBudget(
        replace(limits, rss_bytes=1),
    )
    with pytest.raises(JobError, match="RSS") as runtime:
        runtime_budget.checkpoint_runtime_resources()
    assert runtime.value.error_kind is JobErrorKind.RSS_MEMORY_CEILING
    assert runtime_budget.rss_bytes > 1
    assert runtime_budget.cuda_bytes >= 0

    cuda_budget = _DocumentResourceBudget(
        replace(limits, cuda_bytes=1),
    )
    with pytest.raises(JobError, match="CUDA allocated") as cuda:
        cuda_budget.record_runtime_resources(rss_bytes=1, cuda_bytes=2)
    assert cuda.value.error_kind is JobErrorKind.CUDA_MEMORY_CEILING


def test_document_retry_state_and_resource_profile_are_independent(
    tmp_path: Path,
) -> None:
    canonical_root = os.path.normcase(str(tmp_path.resolve()))
    code = WatcherRetryPolicy(
        tmp_path / "state" / "code.json",
        _WatcherRetryOptions(
            canonical_root=canonical_root,
            source=WatcherSource.CODE,
            base_seconds=10,
            max_seconds=60,
            jitter_fraction=0,
            failure_threshold=3,
            now=0,
        ),
    )
    document = WatcherRetryPolicy(
        tmp_path / "state" / "document.json",
        _WatcherRetryOptions(
            canonical_root=canonical_root,
            source=WatcherSource.DOCUMENT,
            base_seconds=10,
            max_seconds=60,
            jitter_fraction=0,
            failure_threshold=3,
            now=0,
        ),
    )
    code.mark_convergence_pending(now=1)
    code_before = code.state
    document.mark_convergence_pending(now=1)
    admitted = document.admit(now=1)
    assert admitted.attempt_generation is not None
    document.record_failure(
        JobError(JobErrorKind.EXTRACTION_RETRYABLE, "extractor unavailable"),
        admitted.attempt_generation,
        now=2,
        random_unit=0.5,
    )

    assert code.state == code_before
    assert document.state.consecutive_failures == 1
    assert (
        job_spec_error(
            JobSpec(
                operation=JobOperation.INDEX,
                source=JobSource.DOCUMENT,
                mode=JobMode.INCREMENTAL,
                project_root=str(tmp_path),
            )
        )
        is None
    )
    profile = get_index_support_profile("embedded-local")
    with pytest.raises(JobError) as caught:
        validate_profile_admission(
            profile.name,
            IndexDomain.DOCUMENT,
            SupportMeasurement(
                source_files=profile.document.source_files + 1,
                source_bytes=0,
            ),
            AdmissionEnvironment(
                backend="local",
                available_ram_bytes=profile.minimum_ram_bytes,
                store_volume=VolumeReading(
                    role="vector store",
                    path=tmp_path,
                    measured_path=tmp_path,
                    free_bytes=profile.minimum_free_disk_bytes,
                ),
            ),
        )
    assert caught.value.error_kind is JobErrorKind.CORPUS_LIMIT_EXCEEDED


def test_document_slices_enforce_chunk_and_weighted_queue_caps() -> None:
    chunks = [
        DocumentChunk(
            id=f"point-{index}",
            payload=DocumentPayload(
                source_path="records/manual.txt",
                unit_ordinal=index,
                content_fingerprint="digest",
                content=f"bounded content {index}",
            ),
        )
        for index in range(2)
    ]
    slices = tuple(
        iter_weighted_document_slices(
            DocumentSliceStreamRequest(
                chunks=chunks,
                max_chunks=1,
                max_bytes=1024 * 1024,
                dense_dimension=2,
                sparse_enabled=False,
            )
        )
    )
    assert [len(weighted.chunks) for weighted in slices] == [1, 1]
    assert all(weighted.estimated_bytes > 0 for weighted in slices)
    with pytest.raises(ValueError, match="queue ceiling"):
        tuple(
            iter_weighted_document_slices(
                DocumentSliceStreamRequest(
                    chunks=chunks,
                    max_chunks=2,
                    max_bytes=1,
                    dense_dimension=2,
                    sparse_enabled=False,
                )
            )
        )


@pytest.mark.timeout(600)
def test_failed_document_extraction_never_publishes_complete_hash_metadata(
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    from ...indexer import DocumentIndexer
    from ...indexer._document_meta import document_metadata_path, read_document_meta
    from ...progress import NullProgressReporter
    from ...store_runtime import VaultStore

    attempts = tmp_path / "attempts.txt"
    extractor = tmp_path / "fail_again.py"
    extractor.write_text(
        textwrap.dedent(f"""
            from pathlib import Path
            path = Path({str(attempts)!r})
            count = int(path.read_text()) + 1 if path.exists() else 1
            path.write_text(str(count))
            raise SystemExit(9)
        """),
        encoding="utf-8",
    )
    source = tmp_path / "retry.blob"
    source.write_bytes(b"\xff\xfe extractor-owned")
    _write_rule(tmp_path, command=_command(extractor), on_error="skip")
    store = VaultStore(tmp_path)
    try:
        indexer = DocumentIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=_document_policy("*.blob"),
        )
        first = indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        metadata = read_document_meta(document_metadata_path(tmp_path))
        assert first.preprocess_skipped == 1
        # A failed extraction must never publish complete/certified hash
        # metadata. A failed generation stays resumable without certifying a
        # sidecar at all - no sidecar is written (previously an empty,
        # incomplete sidecar was), which is the stronger guarantee: any
        # published metadata here, complete or not, fails this assertion.
        assert metadata is None
        assert store.count_document() == 0

        second = indexer.incremental_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
        )
        assert second.preprocess_skipped == 1
        assert attempts.read_text() == "2"
    finally:
        store.close()
