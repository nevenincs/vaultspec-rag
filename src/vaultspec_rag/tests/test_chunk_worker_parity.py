"""Parity tests for parallel chunking and single-read hashing (#155).

These exercise a real ``spawn`` process pool and real tree-sitter parsing with
no GPU, no model, and no mocks. They lock down the three correctness contracts
the indexing rework must preserve:

- the process-pool chunk path produces byte-identical chunk ids to the serial
  path (so search results never depend on worker count);
- the worker's content hash equals ``hashlib.file_digest`` (so incremental
  change detection is unaffected by the single-read fold);
- single-read decoding reproduces ``Path.read_text`` universal-newline
  semantics (so CRLF files chunk identically to the pre-rework code).
"""

from __future__ import annotations

import gc
import hashlib
import os
import shlex
import sys
import textwrap
import threading
import time
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any, cast

import pytest

from .. import CodebaseIndexer
from ..config._settings import reset_config
from ..config._types import EnvVar
from ..indexer import _chunk_worker
from ..indexer._content_policy import ContentKind
from ..indexer._preprocess_cache import preprocess_cache_dir
from ..indexer._preprocess_config import (
    PreprocessConfig,
    PreprocessContext,
    PreprocessRule,
)
from ..indexer._preprocess_runner import PreprocessAbortError
from ..indexer._run_ledger_models import CommitUnit, CommitUnitKind
from ._chunk_production import produce_chunks
from ._import_probe import assert_fresh_import_excludes, import_probe_source

if TYPE_CHECKING:
    from pathlib import Path

    from .._store_models import CodeChunk

pytestmark = [pytest.mark.unit]

_MODULE_TEMPLATE = '''"""Synthetic module {i}."""


class Widget{i}:
    """A small class with a couple of methods."""

    def __init__(self, value: int) -> None:
        self.value = value

    def scaled(self, factor: int) -> int:
        return self.value * factor + {i}

    def combined(self, other: "Widget{i}") -> int:
        return self.value + other.value


def helper_{i}(a: int, b: int) -> int:
    """Free function {i}."""
    total = a + b
    for _ in range(b):
        total += a
    return total + {i}
'''


def test_scoped_worker_reports_a_vanished_source_as_its_own_disposition(
    tmp_path: Path,
) -> None:
    """A vanished changed file converges; it no longer ends the run.

    These two previously required the read to raise, so that a file missing
    from the corpus could not be published as an ordinary empty result. The
    guarantee is unchanged - a vanished file still never reaches publication as
    content - but it is now carried as a disposition the consumer converges
    rather than an exception that ends the job, which is how one deleted file
    in a tree under active edit was killing whole index runs.
    """
    missing = tmp_path / "vanished.py"

    result = _chunk_worker.chunk_file_with_status(missing, tmp_path)

    assert result.preprocess_status == _chunk_worker.VANISHED_SOURCE_STATUS
    assert result.chunks == []


def test_full_worker_reports_a_vanished_source_as_its_own_disposition(
    tmp_path: Path,
) -> None:
    """The full-index path carries the same disposition as the scoped one."""
    missing = tmp_path / "vanished.py"

    result = _chunk_worker.chunk_and_hash_file(missing, tmp_path)

    assert result.preprocess_status == _chunk_worker.VANISHED_SOURCE_STATUS
    assert result.chunks == []


def test_an_unreadable_source_still_propagates(tmp_path: Path) -> None:
    """Only absence converges; a read that fails otherwise still ends the run.

    A directory occupying a source file's name is a real refusal from the OS,
    not a simulated one, and it must not be mistaken for a deleted file.
    """
    unreadable = tmp_path / "unreadable.py"
    unreadable.mkdir()

    with pytest.raises(OSError) as raised:
        _chunk_worker.chunk_and_hash_file(unreadable, tmp_path)

    assert not isinstance(raised.value, FileNotFoundError)


def test_batch_passthrough_hashes_the_bytes_it_chunks(tmp_path: Path) -> None:
    source = tmp_path / "changed.py"
    source.write_text("original = True\n", encoding="utf-8")
    original_hash = hashlib.blake2b(source.read_bytes()).hexdigest()
    member = _chunk_worker._BatchMember(
        path=source,
        rel_path=source.name,
        content_hash=original_hash,
        cached=None,
    )

    source.write_text("current = 'the bytes that are chunked'\n", encoding="utf-8")
    current_bytes = source.read_bytes()
    result = _chunk_worker._passthrough_batch_member(
        member,
        tmp_path,
    )

    assert result.content_hash == hashlib.blake2b(current_bytes).hexdigest()
    assert result.content_hash != original_hash
    assert result.chunks
    assert "the bytes that are chunked" in result.chunks[0].content


def test_scoped_worker_retains_readable_unsupported_encoding_disposition(
    tmp_path: Path,
) -> None:
    """Readable non-UTF-8 content remains a successful zero-chunk disposition."""
    source = tmp_path / "encoded.py"
    source.write_bytes(b"\xff\xfe\x00\x01")

    result = _chunk_worker.chunk_file_with_status(source, tmp_path)

    assert result.chunks == []
    assert result.preprocess_status is None


def test_the_production_sink_converges_a_vanished_source(tmp_path: Path) -> None:
    """The run survives a file deleted between enumeration and read.

    Driven through the shared production helper, whose publish callback is the
    pipeline's real sink - it records the disposition and calls the typed
    failure raiser, which is the seam that decides whether one deleted file
    ends the job. Asserting at the worker alone would miss that entirely: the
    worker returning a disposition changes nothing if the sink still raises on
    it.

    Mutation: removed the vanished-source convergence from
    ``raise_code_result_failure``. Observed this fail with
    ``JobError: chunk_failed: admitted code source produced no indexable
    chunks`` escaping the production call - one deleted file ending the run,
    which is the whole defect.
    """
    from ._chunk_production import produce_file_results

    survivor = tmp_path / "present.py"
    survivor.write_text("value = 1\n", encoding="utf-8")
    missing = tmp_path / "deleted_mid_run.py"

    indexer = _chunk_only_indexer(tmp_path)
    results = produce_file_results(indexer, [survivor, missing])

    by_path = {result.rel_path: result for result in results}
    assert by_path["deleted_mid_run.py"].preprocess_status == (
        _chunk_worker.VANISHED_SOURCE_STATUS
    )
    assert by_path["present.py"].chunks, "the surviving file still indexes"


def test_the_production_sink_converges_a_preprocessor_skipped_source(
    tmp_path: Path,
) -> None:
    """``on_error = "skip"`` must not end the run it was configured to survive.

    ``skipped`` is not a defect report: it means the runner already resolved a
    failing rule against the operator's own disposition and chose to skip, as
    ``FileChunkResult`` documents. Raising on it at the sink overrides that
    policy, and does so under a ``retryable`` label that a permanently
    unparseable source can never satisfy - so one corrupt document ends every
    run over the tree that holds it, indefinitely.

    Asserted at the sink because that is where the decision lives; the worker
    returning ``skipped`` changes nothing if the sink still raises on it.

    Mutation: restored the ``skipped`` branch in ``_code_result_failure``.
    Observed this fail with ``JobError: extract_retryable: preprocessor exited
    1`` escaping the call below, which is the defect exactly.
    """
    from .._job_errors import JobError

    pipeline = _chunk_only_indexer(tmp_path)._consumer_pipeline

    skipped = _chunk_worker.FileChunkResult(
        rel_path="corpus/corrupt.pdf",
        content_hash="a" * 64,
        chunks=[],
        preprocess_status="skipped",
        preprocess_reason="preprocessor exited 1: Data-loss while decompressing",
    )
    # The whole assertion: this must return rather than raise.
    pipeline.raise_code_result_failure(skipped, None)

    # And the sink must still fail a genuine defect, or the convergence above
    # would just be a blanket "never raise".
    unindexable = _chunk_worker.FileChunkResult(
        rel_path="src/unindexable.py",
        content_hash="b" * 64,
        chunks=[],
        preprocess_status="ok",
    )
    with pytest.raises(JobError):
        pipeline.raise_code_result_failure(unindexable, None)


def _chunk_only_indexer(root: Path) -> CodebaseIndexer:
    """Build a CodebaseIndexer for chunk-only use without a model or store.

    Constructed through the production entry point: the chunking, scanning, and
    worker-planning methods never reach the embedding model or vector store, so
    those two collaborators stay absent while everything the indexer itself
    owns is exactly what a real run would hold.
    """
    return CodebaseIndexer(root, cast("Any", None), cast("Any", None))


def _make_code_tree(root: Path, n_files: int) -> None:
    """Write *n_files* synthetic Python modules plus one YAML file."""
    for i in range(n_files):
        (root / f"mod_{i}.py").write_text(
            _MODULE_TEMPLATE.format(i=i),
            encoding="utf-8",
        )
    (root / "config.yaml").write_text(
        "name: synthetic\nversion: 1\nitems:\n  - a\n  - b\n  - c\n",
        encoding="utf-8",
    )


class _Workers:
    """Context manager forcing a specific ``index_chunk_workers`` value.

    Uses the real environment variable + ``reset_config`` rather than a mock so
    the production resolution path is exercised end to end.
    """

    def __init__(self, value: int) -> None:
        self._value = str(value)
        self._prev: str | None = None

    def __enter__(self) -> None:
        self._prev = os.environ.get(EnvVar.INDEX_CHUNK_WORKERS.value)
        os.environ[EnvVar.INDEX_CHUNK_WORKERS.value] = self._value
        reset_config()

    def __exit__(self, *exc: object) -> None:
        if self._prev is None:
            os.environ.pop(EnvVar.INDEX_CHUNK_WORKERS.value, None)
        else:
            os.environ[EnvVar.INDEX_CHUNK_WORKERS.value] = self._prev
        reset_config()


def _pending_futures() -> set[Future[object]]:
    """Return live executor futures for scheduler-retention assertions."""
    pending: set[Future[object]] = set()
    for candidate in gc.get_objects():
        if isinstance(candidate, Future) and not candidate.done():
            pending.add(cast("Future[object]", candidate))
    return pending


def _wait_for_started(marker_dir: Path, minimum: int) -> list[Path]:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        started = list(marker_dir.glob("*.started"))
        if len(started) >= minimum:
            return started
        time.sleep(0.02)
    raise AssertionError(
        f"only {len(list(marker_dir.glob('*.started')))} tasks started"
    )


def _blocking_preprocess_context(
    root: Path,
    marker_dir: Path,
    release_dir: Path,
) -> PreprocessContext:
    script = root / "blocking_preprocessor.py"
    script.write_text(
        textwrap.dedent(
            """
            import json
            import pathlib
            import sys
            import time

            marker_dir = pathlib.Path(sys.argv[1])
            release_dir = pathlib.Path(sys.argv[2])
            source = pathlib.Path(sys.argv[3])
            (marker_dir / f"{source.name}.started").write_text(
                "started", encoding="utf-8"
            )
            release = release_dir / f"{source.name}.release"
            while not release.exists():
                time.sleep(0.01)
            print(json.dumps({
                "schema_version": 1,
                "preprocessor_id": "scheduler-window",
                "preprocessor_version": "1.0",
                "source_path": str(source),
                "units": [{"text": f"unit for {source.name}"}],
            }))
            """
        ),
        encoding="utf-8",
    )
    command = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} "
        f"{shlex.quote(str(marker_dir))} {shlex.quote(str(release_dir))} {{path}}"
    )
    rule = PreprocessRule(
        pattern="*.wait",
        command=command,
        entry_point=None,
        priority=100,
        # The scheduler under test is the code pool, so the rule it dispatches
        # must be code-targeted: an explicit code route admitting unconventional
        # source. A document target belongs to the document worker instead.
        target=ContentKind.CODE,
        extractor_version="1.0.0",
        on_error="fail",
        timeout_s=30.0,
        options={},
        order=0,
    )
    return PreprocessContext(
        config=PreprocessConfig([rule]),
        cache_root=preprocess_cache_dir(root),
        max_emitted_bytes=1024 * 1024,
        project_root=root,
    )


class TestSingleFileScheduler:
    """The real spawn pool retains a bounded, continuously refilled window."""

    def test_pool_bounds_futures_refills_and_accounts(self, tmp_path: Path) -> None:
        workers = 2
        paths = [tmp_path / f"source_{index:02d}.wait" for index in range(12)]
        for path in paths:
            path.write_bytes(path.name.encode())

        marker_dir = tmp_path / "started"
        release_dir = tmp_path / "release"
        marker_dir.mkdir()
        release_dir.mkdir()
        indexer = _chunk_only_indexer(tmp_path)
        indexer._prep_ctx = _blocking_preprocess_context(
            tmp_path,
            marker_dir,
            release_dir,
        )

        baseline_futures = _pending_futures()
        chunks: list[CodeChunk] = []
        failures: list[BaseException] = []

        def _run() -> None:
            try:
                chunks.extend(produce_chunks(indexer, paths))
            except BaseException as exc:
                failures.append(exc)

        with _Workers(workers):
            runner = threading.Thread(target=_run, daemon=True)
            runner.start()
            try:
                started = _wait_for_started(marker_dir, workers)
                scheduler_futures = _pending_futures() - baseline_futures
                assert len(scheduler_futures) == workers * 2

                # Keep one worker occupied while the other completes enough
                # tasks to cross the initial four-future window. Seeing the
                # fifth hook start proves released slots are refilled promptly.
                held = started[0]
                while len(started) < 5:
                    for marker in started:
                        if marker != held:
                            source_name = marker.name.removesuffix(".started")
                            (release_dir / f"{source_name}.release").touch()
                    started = _wait_for_started(marker_dir, len(started) + 1)
                held_source = held.name.removesuffix(".started")
                assert not (release_dir / f"{held_source}.release").exists()
            finally:
                for path in paths:
                    (release_dir / f"{path.name}.release").touch()
                runner.join(timeout=30.0)

        assert not runner.is_alive()
        assert failures == []
        assert {chunk.path for chunk in chunks} == {path.name for path in paths}
        assert indexer._prep_ok == len(paths)

    def test_pool_propagates_fatal_preprocess_error(self, tmp_path: Path) -> None:
        script = tmp_path / "fatal_preprocessor.py"
        script.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
        command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{path}}"
        rule = PreprocessRule(
            pattern="*.fatal",
            command=command,
            entry_point=None,
            priority=100,
            # Fatal-abort propagation is being asserted for the code pool, so
            # the rule stays on the code side of the boundary.
            target=ContentKind.CODE,
            extractor_version="1.0.0",
            on_error="fail",
            timeout_s=30.0,
            options={},
            order=0,
        )
        indexer = _chunk_only_indexer(tmp_path)
        indexer._prep_ctx = PreprocessContext(
            config=PreprocessConfig([rule]),
            cache_root=preprocess_cache_dir(tmp_path),
            max_emitted_bytes=1024 * 1024,
            project_root=tmp_path,
        )
        paths = [tmp_path / f"source_{index}.fatal" for index in range(4)]
        for path in paths:
            path.write_bytes(path.name.encode())

        with _Workers(2), pytest.raises(PreprocessAbortError):
            produce_chunks(indexer, paths)


class TestChunkIdentityParity:
    """Process-pool chunking must match the serial path exactly.

    Both sides drive the shipped producers, so worker count is the only
    difference between the runs: four workers routes the files through the
    spawn pool, one worker takes the in-process serial producer. Comparing
    ids element-wise (not as sets) also binds the per-file emission order,
    which a set comparison would let drift silently.

    Proven able to fail: giving the pooled branch a different root than the
    serial branch (so its relative paths, and therefore its chunk ids, must
    diverge) fails this test on the id comparison itself - not on a setup or
    import error - and restoring the root returns it to green. Drive both
    sides through the shipped producers or that proof is worthless: an
    earlier version of this test compared two helpers that production had
    stopped calling, and passed while proving nothing about what ships.
    """

    def test_parallel_matches_serial(self, tmp_path: Path) -> None:
        _make_code_tree(tmp_path, 40)
        indexer = _chunk_only_indexer(tmp_path)
        paths = indexer.scan_files()
        assert len(paths) >= 40

        with _Workers(4):
            parallel = produce_chunks(indexer, paths)
        with _Workers(1):
            serial = produce_chunks(indexer, paths)

        assert [c.id for c in parallel] == [c.id for c in serial]
        assert [c.content for c in parallel] == [c.content for c in serial]
        assert len(parallel) == len(serial)

    def test_parallel_pipeline_hashes_every_file(self, tmp_path: Path) -> None:
        _make_code_tree(tmp_path, 20)
        indexer = _chunk_only_indexer(tmp_path)
        paths = indexer.scan_files()
        # An empty scan would make the count below compare 0 to 0 and assert
        # nothing about the worker at all.
        assert len(paths) >= 20
        # chunk_and_hash_file is the pipeline worker; its meta must cover every
        # readable file even when a file yields zero chunks.
        meta: dict[str, str] = {}
        for p in paths:
            res = _chunk_worker.chunk_and_hash_file(p, tmp_path)
            assert res is not None
            meta[res.rel_path] = res.content_hash
        assert len(meta) == len(paths)


class TestChunkIdentityUniqueness:
    """A file's chunk identifiers must be unique so a commit unit is accepted.

    Guard for the repeated-content collision: an over-budget line of one
    repeated character is split into byte-identical fixed-width slices that
    share a line span, so the pre-fix ``{path}:{span}:{hash}`` identifier
    form collided and failed the whole code-index update. These assertions
    bind to the emit-ordinal discriminator in ``chunk_with_ast`` /
    ``chunk_with_splitter``; removing that ordinal makes both fail on the
    uniqueness/commit-unit assertion, not on any incidental error.
    """

    def test_repeated_content_long_line_yields_unique_ids(self, tmp_path: Path) -> None:
        # A single 6000-char line of one repeated character: an oversized
        # childless leaf routed through _split_large_leaf, whose slices are
        # byte-identical and share one (line_start, line_end) span.
        source = f"DATA = '{'x' * 6000}'\n"
        path = tmp_path / "generated_blob.py"
        path.write_text(source, encoding="utf-8")

        chunks = _chunk_worker.chunk_file(path, tmp_path)

        # More than one chunk (the leaf was split), and every id distinct.
        assert len(chunks) > 1
        ids = [c.id for c in chunks]
        assert len(set(ids)) == len(ids), f"duplicate chunk ids: {ids}"

    def test_repeated_content_chunks_form_valid_commit_unit(
        self, tmp_path: Path
    ) -> None:
        source = f"DATA = '{'x' * 6000}'\n"
        path = tmp_path / "generated_blob.py"
        path.write_text(source, encoding="utf-8")

        chunks = _chunk_worker.chunk_file(path, tmp_path)
        digest = hashlib.blake2b(source.encode("utf-8")).hexdigest()

        # Plurality matters: if the oversized leaf ever stopped being split,
        # a single-chunk unit would satisfy the uniqueness invariant
        # vacuously and this guard would go green without exercising it.
        assert len(chunks) > 1

        # The commit-unit uniqueness invariant is the exact check that failed
        # in production; constructing the unit IS the assertion - it raises on
        # a duplicate id. This is what the emit-ordinal defends.
        unit = CommitUnit(
            rel_path="generated_blob.py",
            kind=CommitUnitKind.UPSERT,
            source_digest=digest,
            segment_ordinal=0,
            is_file_end=True,
            point_ids=tuple(c.id for c in chunks),
        )
        # Carry information the constructor did not already enforce: the unit
        # preserves the chunker's emitted ids in emit order.
        assert unit.point_ids == tuple(c.id for c in chunks)


class _MinBytes:
    """Context manager overriding ``index_parallel_min_bytes`` (real env)."""

    def __init__(self, value: int) -> None:
        self._value = str(value)
        self._prev: str | None = None

    def __enter__(self) -> None:
        self._prev = os.environ.get(EnvVar.INDEX_PARALLEL_MIN_BYTES.value)
        os.environ[EnvVar.INDEX_PARALLEL_MIN_BYTES.value] = self._value
        reset_config()

    def __exit__(self, *exc: object) -> None:
        if self._prev is None:
            os.environ.pop(EnvVar.INDEX_PARALLEL_MIN_BYTES.value, None)
        else:
            os.environ[EnvVar.INDEX_PARALLEL_MIN_BYTES.value] = self._prev
        reset_config()


class TestWorkerGating:
    """Auto worker selection must gate on total source bytes (#155)."""

    def test_byte_gate_controls_auto_parallelism(self, tmp_path: Path) -> None:
        """The byte gate, not the core count, decides serial vs parallel."""
        _make_code_tree(tmp_path, 20)  # ~tens of KB, well under 8 MiB
        indexer = _chunk_only_indexer(tmp_path)
        paths = indexer.scan_files()

        if (os.cpu_count() or 1) < 2:
            # No parallelism is possible; auto must be serial regardless.
            with _Workers(0):
                assert indexer._producer.plan_workers(paths) == 1
            return

        # Multi-core: the SAME small tree is serial under the default gate but
        # parallel once the gate is lowered to 0 - so the gate, not the core
        # count, is what forced serial. This contrast is the non-tautological
        # proof that the gate logic actually runs.
        with _Workers(0):
            assert indexer._producer.plan_workers(paths) == 1
            with _MinBytes(0):
                assert indexer._producer.plan_workers(paths) > 1

    def test_explicit_workers_bypass_gate(self, tmp_path: Path) -> None:
        _make_code_tree(tmp_path, 20)
        indexer = _chunk_only_indexer(tmp_path)
        paths = indexer.scan_files()
        # An explicit request resolves to min(request, n_paths) regardless of
        # core count or the byte gate.
        with _Workers(3):
            assert indexer._producer.plan_workers(paths) == 3


def test_worker_import_does_not_load_torch() -> None:
    """Importing the chunk worker must not pull in torch (spawn/no-CUDA rule).

    Spawn workers re-import this module; if any module on its import chain
    eagerly imported torch, every worker would initialise CUDA on startup and
    reintroduce the fork/spawn CUDA-context crash class that keeping worker
    imports torch-free prevents.
    Checked in a fresh interpreter so the parent process's already-loaded torch
    cannot mask a regression.
    """
    assert_fresh_import_excludes(
        import_probe_source("vaultspec_rag.indexer._chunk_worker")
    )


class TestHashParity:
    """The worker hash must equal hashlib.file_digest over the raw bytes."""

    def test_content_hash_matches_file_digest(self, tmp_path: Path) -> None:
        _make_code_tree(tmp_path, 5)
        indexer = _chunk_only_indexer(tmp_path)
        scanned = indexer.scan_files()
        # Without this the loop body is the whole test: a scan that returns
        # nothing runs zero iterations and the parity below is never checked.
        assert len(scanned) >= 5
        for p in scanned:
            res = _chunk_worker.chunk_and_hash_file(p, tmp_path)
            assert res is not None
            with open(p, "rb") as f:
                expected = hashlib.file_digest(f, "blake2b").hexdigest()
            assert res.content_hash == expected


class TestNewlineParity:
    """Single-read decoding must reproduce Path.read_text newline handling."""

    def test_crlf_chunks_match_read_text(self, tmp_path: Path) -> None:
        crlf = tmp_path / "crlf_module.py"
        crlf.write_bytes(
            b'"""CRLF doc."""\r\n\r\n\r\n'
            b"class Thing:\r\n"
            b"    def run(self, x):\r\n"
            b"        return x + 1\r\n\r\n\r\n"
            b"def standalone(a, b):\r\n"
            b"    return a * b\r\n",
        )
        # New single-read path.
        new_chunks = _chunk_worker.chunk_file(crlf, tmp_path)
        # Reference: the pre-rework behaviour decoded via Path.read_text, which
        # applies universal-newline translation.
        ref_content = crlf.read_text(encoding="utf-8")
        ref_chunks = _chunk_worker._chunk_decoded(ref_content, crlf, tmp_path)

        # Both sides run through the same decoder, so a decoder that emits
        # nothing satisfies every parity comparison below by comparing two
        # empty lists. Match the twin test's guard and require real output.
        assert new_chunks, "the CRLF module must produce chunks"
        assert [c.id for c in new_chunks] == [c.id for c in ref_chunks]
        assert [c.content for c in new_chunks] == [c.content for c in ref_chunks]
        # And no carriage returns survive translation.
        assert all("\r" not in c.content for c in new_chunks)

    def test_crlf_file_and_lf_twin_chunk_identically(self, tmp_path: Path) -> None:
        """CRLF and LF twins must yield identical chunk ids and contents.

        Decode-time newline normalization makes a chunk's identity a
        function of its logical text, not its on-disk line endings. Donor
        vector reuse verifies adoption by chunk id and text, so a Windows
        worktree (CRLF checkout) must chunk byte-identically to its LF
        twin or every donor lookup silently misses.
        """
        body = (
            '"""Twin doc."""\n\n\n'
            "class Twin:\n"
            "    def run(self, x):\n"
            "        return x + 1\n\n\n"
            "def standalone(a, b):\n"
            "    return a * b\n"
        )
        lf_root = tmp_path / "lf-root"
        crlf_root = tmp_path / "crlf-root"
        lf_root.mkdir()
        crlf_root.mkdir()
        (lf_root / "twin_module.py").write_bytes(body.encode("utf-8"))
        (crlf_root / "twin_module.py").write_bytes(
            body.replace("\n", "\r\n").encode("utf-8")
        )

        lf_chunks = _chunk_worker.chunk_file(lf_root / "twin_module.py", lf_root)
        crlf_chunks = _chunk_worker.chunk_file(crlf_root / "twin_module.py", crlf_root)

        assert lf_chunks, "the twin module must produce chunks"
        assert [c.id for c in crlf_chunks] == [c.id for c in lf_chunks]
        assert [c.content for c in crlf_chunks] == [c.content for c in lf_chunks]
