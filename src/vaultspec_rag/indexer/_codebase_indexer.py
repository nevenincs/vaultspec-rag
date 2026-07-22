"""Source-code indexing orchestration.

Walks the project tree with gitignore-aware pruning, chunks files via
tree-sitter ASTs (or a text-splitter fallback), embeds, and upserts code
chunks, tracking content hashes for incremental re-indexing.
"""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import json
import logging
import multiprocessing
import os
import pathlib
import queue
import time
from collections import deque
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ProcessPoolExecutor,
    wait,
)
from concurrent.futures.process import BrokenProcessPool
from typing import TYPE_CHECKING, NamedTuple

from ..job_control import NO_RUN_CONTROL, RunControlSignal
from ..logging_config import log_event
from . import _chunk_worker, _code_meta, _ignore_specs, _preprocess_glue
from ._chunking import (
    _MAX_FILE_SIZE,
    SUPPORTED_EXTENSIONS,
    _is_binary,
)
from ._code_meta import (
    CODE_EMBED_SCHEMA,
    CONTENT_EPOCH_KEY,
    EMBED_SCHEMA_KEY,
    MEMBERSHIP_EPOCH_KEY,
)
from ._streaming import (
    CodeFileSegment,
    _release_cuda_cache,
    _stream_encode_and_upsert_codebase,
    encode_and_upsert_code_slice,
    iter_code_file_segments,
    iter_weighted_code_slices,
)
from ._vault_prep import IndexResult

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Iterable, Iterator
    from multiprocessing.context import BaseContext

    import pathspec

    from ..embeddings import EmbeddingModel
    from ..job_control import RunControl
    from ..progress import ProgressReporter
    from ..store import CodeChunk, VaultStore
    from ._chunk_worker import FileChunkResult
    from ._preprocess_config import (
        PreprocessConfig,
        PreprocessContext,
        PreprocessRule,
    )

logger = logging.getLogger(__name__)

# Upper bound on how long pipeline shutdown waits for the GPU consumer thread
# to drain its final batch and terminate. Generous enough for any healthy
# final encode (a couple of slices) yet finite, so a wedged CUDA/Qdrant call
# escalates to a raised error instead of hanging the producer and holding the
# indexer's writer lock forever (#155 index-gpu-pipeline review C1/H1/H2).
_CONSUMER_SHUTDOWN_TIMEOUT_S = 300.0

# Polling bound for cooperative control while the parent waits on CPU workers
# or either pipeline side waits on the bounded producer/consumer queue.
_CONTROL_POLL_SECONDS = 0.1

#: Conservative chunks-per-file factor for the pre-pool disk pre-flight;
#: a measured large mixed-language tree averaged ~12 chunks per source file.
_CHUNKS_PER_FILE_ESTIMATE = 12

# Maximum number of source paths handed to one batch preprocess spawn (#241).
# A batch rule's matched files are grouped into manifests of at most this many
# paths, each group running as a single pool task, so the hook's spawn cost is
# amortised across the group instead of paid per file.
BATCH_SIZE = 64

# Keep one queued single-file task behind each active worker. This absorbs the
# coordinator's result/accounting latency without retaining one Future (and
# potentially one completed chunk result) per source path on large trees.
_CHUNK_FUTURE_WINDOW_PER_WORKER = 2


class _UnsettledCodeConsumerError(RuntimeError):
    """The code consumer remained live after its bounded shutdown wait."""


class _ScanInputs(NamedTuple):
    """Ignore specs and preprocess config resolved in one pass.

    The compiled specs (for the scan) and the raw pattern lists (for the
    config epoch) come from a single ``.gitignore`` rglob, so the scoped
    watcher path computes the epoch and scans without a second tree walk.
    ``vaultragignore_patterns`` are the file-only patterns; CLI ``--exclude``
    entries live in ``rag_spec`` but are kept out of the epoch inputs.
    """

    git_spec: pathspec.GitIgnoreSpec
    rag_spec: pathspec.GitIgnoreSpec | None
    gitignore_patterns: list[str]
    vaultragignore_patterns: list[str]
    preprocess_config: PreprocessConfig


class _CodePipelineLimits(NamedTuple):
    """Frozen weighted limits shared by code-index producers and consumer."""

    segment_max_chunks: int
    segment_max_bytes: int
    queue_max_chunks: int
    queue_max_bytes: int
    slice_max_chunks: int
    slice_max_bytes: int
    dense_dimension: int
    sparse_enabled: bool
    sparse_dimension: int
    encode_batch_size: int
    flush_slices: int


class _WeightedCodeSegmentQueue:
    """Thread-safe queue bounded by queued chunk and byte weights."""

    __slots__ = (
        "_condition",
        "_items",
        "_max_bytes",
        "_max_chunks",
        "_queued_bytes",
        "_queued_chunks",
    )

    def __init__(self, *, max_chunks: int, max_bytes: int) -> None:
        import threading

        if isinstance(max_chunks, bool) or max_chunks <= 0:
            raise ValueError("max_chunks must be a positive integer")
        if isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self._max_chunks = max_chunks
        self._max_bytes = max_bytes
        self._queued_chunks = 0
        self._queued_bytes = 0
        self._items: deque[CodeFileSegment | None] = deque()
        self._condition = threading.Condition()

    @property
    def queued_chunks(self) -> int:
        """Return the number of chunks waiting in the queue."""
        with self._condition:
            return self._queued_chunks

    @property
    def queued_bytes(self) -> int:
        """Return the estimated bytes waiting in the queue."""
        with self._condition:
            return self._queued_bytes

    def _can_admit(self, segment: CodeFileSegment) -> bool:
        return (
            self._queued_chunks + len(segment.chunks) <= self._max_chunks
            and self._queued_bytes + segment.estimated_bytes <= self._max_bytes
        )

    def _wait_until_admitted(
        self,
        segment: CodeFileSegment,
        *,
        block: bool,
        timeout: float | None,
    ) -> None:
        if self._can_admit(segment):
            return
        if not block:
            raise queue.Full
        if timeout is None:
            while not self._can_admit(segment):
                self._condition.wait()
            return
        deadline = time.monotonic() + timeout
        while not self._can_admit(segment):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Full
            self._condition.wait(remaining)

    def put(
        self,
        item: CodeFileSegment | None,
        block: bool = True,
        timeout: float | None = None,
    ) -> None:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be a non-negative number")
        if item is not None and (
            len(item.chunks) > self._max_chunks
            or item.estimated_bytes > self._max_bytes
        ):
            raise ValueError(
                f"segment {item.path!r}#{item.ordinal} exceeds queue capacity"
            )
        with self._condition:
            if item is not None:
                self._wait_until_admitted(item, block=block, timeout=timeout)
                self._queued_chunks += len(item.chunks)
                self._queued_bytes += item.estimated_bytes
            self._items.append(item)
            self._condition.notify_all()

    def get(
        self,
        block: bool = True,
        timeout: float | None = None,
    ) -> CodeFileSegment | None:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be a non-negative number")
        with self._condition:
            if not block and not self._items:
                raise queue.Empty
            if timeout is None:
                while not self._items:
                    self._condition.wait()
            else:
                deadline = time.monotonic() + timeout
                while not self._items:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise queue.Empty
                    self._condition.wait(remaining)
            item = self._items.popleft()
            if item is not None:
                self._queued_chunks -= len(item.chunks)
                self._queued_bytes -= item.estimated_bytes
            self._condition.notify_all()
            return item


def _drain_code_chunks(chunks: list[CodeChunk]) -> Iterator[CodeChunk]:
    """Yield a file's chunks in order while releasing its source list."""
    chunks.reverse()
    while chunks:
        yield chunks.pop()


class CodebaseIndexer:
    """Orchestrates source code indexing into the vector store.

    Walks the project tree with ``.gitignore``-aware pruning, chunks source
    files using tree-sitter AST analysis when a grammar is available or
    ``TextSplitter`` as a fallback, generates dense and sparse embeddings,
    and upserts the results into Qdrant. Supports 16+ languages via
    tree-sitter grammars and incremental indexing using blake2b content
    hashing to skip unchanged files.
    """

    def __init__(
        self,
        root_dir: pathlib.Path,
        model: EmbeddingModel,
        store: VaultStore,
        *,
        gpu_lock: threading.Lock | None = None,
        extra_excludes: list[str] | None = None,
    ) -> None:
        """Initialize the codebase indexer.

        Args:
            root_dir: Path to the project root directory to index.
            model: Embedding model used to encode code chunks.
            store: Vector store where indexed code chunks are
                persisted.
            gpu_lock: Optional ``threading.Lock`` that serializes
                GPU operations (encoding) with concurrent searches.
            extra_excludes: Additional gitignore-syntax exclusion
                patterns (e.g. from CLI ``--exclude``). Merged into
                the ``.vaultragignore`` spec.
        """
        self.root_dir = root_dir
        self.model = model
        self.store = store
        self._gpu_lock = gpu_lock
        self._extra_excludes = extra_excludes or []
        # Indexer-level writer lock that serializes full_index and
        # incremental_index against each other on the same instance
        # (#68 audit F6.6 - concurrent reindex race).
        import threading as _threading

        self._writer_lock: _threading.Lock = _threading.Lock()
        from ..config import get_config

        cfg = get_config()
        self._data_root = root_dir / cfg.data_dir
        self._meta_path = self._data_root / cfg.code_index_metadata_file
        # Per-run document-preprocessing state (#185). Both are reset at the
        # start of each full/incremental run; the writer lock serialises runs
        # so instance-scoped state is safe. ``_prep_ctx`` is the context handed
        # to chunk workers; ``_prep_skips`` accumulates "rel_path: reason" for
        # files a preprocess rule skipped and ``_prep_ok`` counts rule-fed
        # files, both surfaced in the run's IndexResult.
        self._prep_ctx: PreprocessContext | None = None
        self._prep_skips: list[str] = []
        self._prep_ok: int = 0
        # Config epochs for the current run (D1-D3). Set at the start of each
        # locked run from the same resolved inputs the scan uses, then stamped
        # by ``_write_meta``; ``None`` means "not yet resolved this run" and the
        # writer recomputes them as a fallback.
        self._membership_epoch: str | None = None
        self._content_epoch: str | None = None

    def _collect_gitignore_patterns(self) -> list[str]:
        """Collect the hardcoded and ``.gitignore``-sourced exclusion patterns.

        Delegates to :func:`_ignore_specs.collect_gitignore_patterns`; kept as
        a method so callers (and tests) can monkeypatch the single tree walk.
        """
        return _ignore_specs.collect_gitignore_patterns(self.root_dir)

    def _process_gitignore_lines(
        self,
        lines: list[str],
        rel_dir: pathlib.Path,
        patterns: list[str],
    ) -> None:
        _ignore_specs.process_gitignore_lines(lines, rel_dir, patterns)

    def _collect_vaultragignore_patterns(self) -> list[str]:
        """Collect the root ``.vaultragignore`` patterns (excluding ``--exclude``)."""
        return _ignore_specs.collect_vaultragignore_patterns(self.root_dir)

    def _build_vaultragignore_spec(self) -> pathspec.GitIgnoreSpec | None:
        """Build a pathspec from ``.vaultragignore`` and CLI ``--exclude`` patterns."""
        return _ignore_specs.build_vaultragignore_spec(
            self.root_dir, self._extra_excludes
        )

    def _resolve_scan_inputs(self) -> _ScanInputs:
        """Resolve ignore specs and preprocess config in a single tree walk.

        The compiled specs drive the scan; the raw pattern lists and the
        preprocess config drive the membership/content epochs. Sharing one
        ``.gitignore`` rglob keeps the scoped path free of a second traversal.
        """
        import pathspec

        git_patterns = self._collect_gitignore_patterns()
        rag_patterns = self._collect_vaultragignore_patterns()
        prep_config = self._build_preprocess_rules()

        git_spec = pathspec.GitIgnoreSpec.from_lines(git_patterns)
        extra_excludes: list[str] = getattr(self, "_extra_excludes", None) or []
        rag_all = [*rag_patterns, *extra_excludes]
        rag_spec = pathspec.GitIgnoreSpec.from_lines(rag_all) if rag_all else None
        return _ScanInputs(
            git_spec=git_spec,
            rag_spec=rag_spec,
            gitignore_patterns=git_patterns,
            vaultragignore_patterns=rag_patterns,
            preprocess_config=prep_config,
        )

    def _compute_code_epochs(self, inputs: _ScanInputs) -> tuple[str, str]:
        """Compute the (membership, content) epoch pair from resolved inputs."""
        return _code_meta.compute_code_epochs(
            gitignore_patterns=inputs.gitignore_patterns,
            vaultragignore_patterns=inputs.vaultragignore_patterns,
            preprocess_rules=inputs.preprocess_config.rules,
        )

    def _classify_config_drift(self, membership: str, content: str) -> str:
        """Classify config drift against the stored epochs.

        Returns ``"clean"`` (content drift - clean rebuild), ``"unscoped"``
        (membership drift or a legacy sidecar missing the keys - force the
        unscoped incremental), or ``"ok"`` (no drift, or a fresh index with no
        sidecar to compare against). Content drift outranks membership drift
        because the clean rebuild subsumes the membership reconcile.
        """
        return _code_meta.classify_config_drift(
            self._read_meta_raw(), membership, content
        )

    def _config_drift_dispatch(
        self,
        changed_paths: Iterable[pathlib.Path] | None,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[_ScanInputs, Iterable[pathlib.Path] | None, bool]:
        """Resolve inputs, stamp the run's epochs, and classify config drift.

        Runs once at the incremental entry (D2): the ignore specs and
        preprocess config are resolved a single time and returned so the scan
        reuses them without a second tree walk. Returns the resolved inputs,
        the possibly-nulled ``changed_paths`` (a membership mismatch, or a
        legacy sidecar missing the keys, forces the unscoped incremental), and
        whether a content mismatch requires a clean rebuild.
        """
        run_control.checkpoint()
        inputs = self._resolve_scan_inputs()
        run_control.checkpoint()
        membership, content = self._compute_code_epochs(inputs)
        run_control.checkpoint()
        self._membership_epoch = membership
        self._content_epoch = content
        drift = self._classify_config_drift(membership, content)
        if drift == "clean":
            return inputs, changed_paths, True
        if drift == "unscoped" and changed_paths is not None:
            logger.info(
                "Codebase membership config changed; forcing an unscoped "
                "incremental reconcile of the code collection",
            )
            changed_paths = None
        return inputs, changed_paths, False

    def _build_preprocess_rules(self) -> PreprocessConfig:
        """Resolve ``.vaultragpreprocess.toml`` into compiled preprocess rules.

        Kept as a method (delegating to :func:`_preprocess_glue`) so callers
        and tests can monkeypatch the root-only resolution.
        """
        return _preprocess_glue.build_preprocess_rules(self.root_dir)

    def preprocess_config(self) -> PreprocessConfig:
        """Resolve the project's preprocess rules (public accessor, #185).

        Used by the watcher to make its change filter preprocess-aware (D8).
        """
        return self._build_preprocess_rules()

    def _clear_preprocess_cache(self) -> None:
        """Remove the preprocess output cache subtree for a clean rebuild (D7)."""
        _preprocess_glue.clear_preprocess_cache_for(self._data_root)

    def _resolve_preprocess_context(self) -> PreprocessContext | None:
        """Build the per-run preprocess context, or ``None`` when no rules apply."""
        return _preprocess_glue.resolve_preprocess_context(
            self.root_dir, self._data_root, self._build_preprocess_rules()
        )

    def _begin_preprocess_run(
        self,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Reset per-run preprocess state at the start of a full/incremental run."""
        run_control.checkpoint()
        self._prep_ctx = self._resolve_preprocess_context()
        self._prep_skips = []
        self._prep_ok = 0
        run_control.checkpoint()

    def _prep_rule_count(self) -> int:
        """Return the number of preprocess rules active for the current run."""
        return _preprocess_glue.prep_rule_count(self._prep_ctx)

    def _record_preprocess_result(self, res: FileChunkResult | None) -> None:
        """Accumulate a worker result's preprocess disposition (D11)."""
        self._prep_ok += _preprocess_glue.record_preprocess_result(
            res, self._prep_skips
        )

    def _record_scoped_preprocess(
        self,
        path: pathlib.Path,
        result: _chunk_worker.ScopedChunkResult,
    ) -> None:
        """Accumulate a scoped-path preprocess disposition (D11)."""
        self._prep_ok += _preprocess_glue.record_scoped_preprocess(
            self.root_dir, path, result, self._prep_skips
        )

    def _scan_codebase(
        self,
        inputs: _ScanInputs | None = None,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> list[pathlib.Path]:
        """Scan codebase for supported source files.

        Walks the project tree using ``os.walk``, pruning directories
        matched by ``.gitignore`` and ``.vaultragignore`` patterns via
        ``pathspec``.  The two specs are independent - a file is
        excluded if **either** matches (OR logic), so
        ``.vaultragignore`` can never un-ignore ``.gitignore`` entries.
        Skips binary files and files exceeding ``_MAX_FILE_SIZE``.

        Args:
            inputs: Pre-resolved ignore specs. When ``None`` the specs are
                built here; callers that already resolved them (to compute the
                config epoch) pass them in to avoid a second tree walk.

        Returns:
            List of absolute paths to indexable source files.

        Raises:
            OSError: If the root directory cannot be traversed.
        """
        if inputs is None:
            inputs = self._resolve_scan_inputs()
        git_spec = inputs.git_spec
        rag_spec = inputs.rag_spec

        def _is_excluded(rel_path: str) -> bool:
            if git_spec.match_file(rel_path):
                return True
            return rag_spec is not None and rag_spec.match_file(rel_path)

        result: list[pathlib.Path] = []
        root_str = str(self.root_dir)
        for dirpath, dirs, files in os.walk(self.root_dir, topdown=True):
            run_control.checkpoint()
            # Prune ignored directories in-place to avoid traversal
            rel_dir = os.path.relpath(dirpath, root_str).replace("\\", "/")
            if rel_dir == ".":
                dirs[:] = [d for d in dirs if not _is_excluded(f"{d}/")]
            else:
                dirs[:] = [d for d in dirs if not _is_excluded(f"{rel_dir}/{d}/")]
            self._process_scan_files(
                dirpath,
                files,
                rel_dir,
                _is_excluded,
                result,
                run_control=run_control,
            )
            run_control.checkpoint()
        return result

    def _matches_preprocess_rule(self, rel: str) -> bool:
        """Return whether a preprocess rule matches this project-relative path.

        Ignore always wins (this is only consulted after the ignore gate), but a
        match expands the indexable set: a matched file is admitted even when its
        extension is unsupported, it exceeds ``_MAX_FILE_SIZE``, or it is binary,
        because the preprocessor extracts indexable text from it (D2, D10).
        """
        return _preprocess_glue.matches_preprocess_rule(
            getattr(self, "_prep_ctx", None), rel
        )

    def _process_scan_files(
        self,
        dirpath: str,
        files: list[str],
        rel_dir: str,
        _is_excluded: Callable[[str], bool],
        result: list[pathlib.Path],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        for fname in files:
            run_control.checkpoint()
            p = pathlib.Path(dirpath) / fname
            rel = fname if rel_dir == "." else f"{rel_dir}/{fname}"
            if _is_excluded(rel):
                continue
            # A preprocess-rule match relaxes the extension, size, and binary
            # gates (D2, D10); ignore has already been applied above and wins.
            if self._matches_preprocess_rule(rel):
                result.append(p)
                continue
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if p.stat().st_size > _MAX_FILE_SIZE:
                logger.debug("Skipping oversized file: %s", rel)
                continue
            if _is_binary(p):
                logger.debug("Skipping binary file: %s", rel)
                continue
            result.append(p)
            run_control.checkpoint()

    def scan_files(self) -> list[pathlib.Path]:
        """Return the list of files that would be indexed.

        Does not require GPU or vector store - safe to call with
        ``model=None`` and ``store=None`` for dry-run usage.

        Returns:
            List of absolute paths to indexable source files.
        """
        return self._scan_codebase()

    def _chunk_file(self, path: pathlib.Path) -> list[CodeChunk]:
        """Read a file and split it into AST-aware ``CodeChunk``s.

        Delegates to the module-level worker (`_chunk_worker.chunk_file`) so the
        serial in-process path and the process-pool path share a single code
        path and produce byte-identical chunk ids.

        Args:
            path: Absolute path to the source file.

        Returns:
            List of ``CodeChunk`` instances with empty vectors.
        """
        return _chunk_worker.chunk_file(path, self.root_dir)

    def _chunk_with_ast(
        self,
        content: str,
        rel_path: str,
        language: str,
        grammar: str,
    ) -> list[CodeChunk]:
        """Chunk source code using tree-sitter AST (delegates to the worker)."""
        return _chunk_worker.chunk_with_ast(content, rel_path, language, grammar)

    def _chunk_with_splitter(
        self,
        content: str,
        rel_path: str,
        language: str,
    ) -> list[CodeChunk]:
        """Chunk content using TextSplitter (delegates to the worker)."""
        return _chunk_worker.chunk_with_splitter(content, rel_path, language)

    def _resolve_chunk_workers(self, n_paths: int) -> int:
        """Resolve the number of chunk worker processes to use.

        Reads the ``index_chunk_workers`` config knob: ``0`` means auto
        (``os.process_cpu_count()``); any positive value is honoured verbatim.
        The result is clamped to ``[1, n_paths]`` so a tiny change set never
        spawns more workers than there are files.

        Args:
            n_paths: Number of files about to be chunked.

        Returns:
            Worker count, at least 1.
        """
        from ..config import get_config

        configured = int(get_config().index_chunk_workers)
        workers = configured if configured > 0 else (os.process_cpu_count() or 1)
        return max(1, min(workers, n_paths))

    def _plan_chunk_workers(self, paths: list[pathlib.Path]) -> int:
        """Decide the worker count for *paths*, gating auto mode on workload.

        Spawn workers cost ~0.3s each to start, so on small or medium trees the
        process pool loses to serial chunking (#155 benchmark). In AUTO mode
        (``index_chunk_workers=0``) the pool engages only once the total source
        size crosses ``index_parallel_min_bytes``; below that the path stays
        serial. An explicit ``index_chunk_workers`` >= 1 bypasses the gate so a
        caller can force parallelism (or serial) regardless of size.

        Args:
            paths: Files about to be chunked.

        Returns:
            Worker count; ``1`` means run the serial in-process path.
        """
        from ..config import get_config

        cfg = get_config()
        workers = self._resolve_chunk_workers(len(paths))
        if workers <= 1:
            return 1
        if int(cfg.index_chunk_workers) > 0:
            return workers  # explicit request bypasses the byte gate

        min_bytes = int(cfg.index_parallel_min_bytes)
        total = 0
        for p in paths:
            try:
                total += p.stat().st_size
            except OSError:
                continue
            if total >= min_bytes:
                return workers
        return 1

    def _partition_batch_work(
        self,
        paths: list[pathlib.Path],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[list[tuple[PreprocessRule, list[pathlib.Path]]], list[pathlib.Path]]:
        """Split paths into batch-rule groups and everything else (#241).

        Files matched by a ``batch = true`` rule are grouped per rule (keyed by
        rule identity - :meth:`PreprocessConfig.match` returns the same rule
        object each time) and chunked into manifests of at most
        :data:`BATCH_SIZE`, so each group runs as one batch spawn. Every other
        file - unmatched, or matched by a non-batch rule - stays a single, so
        the existing per-file flow is untouched.

        Returns:
            ``(batch_groups, singles)``: batch groups as ``(rule, paths)`` pairs
            and the single-file paths, together covering every input path.
        """
        prep = getattr(self, "_prep_ctx", None)
        if prep is None or not any(rule.batch for rule in prep.config.rules):
            # No batch rule configured: every file keeps the per-file flow and
            # pays zero extra per-path match cost.
            return [], list(paths)

        groups: dict[int, list[pathlib.Path]] = {}
        rules: dict[int, PreprocessRule] = {}
        singles: list[pathlib.Path] = []
        for p in paths:
            run_control.checkpoint()
            try:
                rel = str(p.relative_to(self.root_dir)).replace("\\", "/")
            except ValueError:
                singles.append(p)
                continue
            rule = prep.config.match(rel)
            if rule is not None and rule.batch and rule.command is not None:
                rid = id(rule)
                groups.setdefault(rid, []).append(p)
                rules[rid] = rule
            else:
                singles.append(p)
            run_control.checkpoint()

        batch_groups: list[tuple[PreprocessRule, list[pathlib.Path]]] = []
        for rid, group in groups.items():
            run_control.checkpoint()
            rule = rules[rid]
            for start in range(0, len(group), BATCH_SIZE):
                batch_groups.append((rule, group[start : start + BATCH_SIZE]))
            run_control.checkpoint()
        return batch_groups, singles

    def _submit_batch_futures(
        self,
        pool: ProcessPoolExecutor,
        batch_groups: list[tuple[PreprocessRule, list[pathlib.Path]]],
        prep: PreprocessContext,
        run_control: RunControl,
    ) -> dict[Future[list[FileChunkResult]], int]:
        """Submit batch worker tasks while retaining cooperative ownership."""
        futures: dict[Future[list[FileChunkResult]], int] = {}
        try:
            for rule, group in batch_groups:
                run_control.checkpoint()
                future = pool.submit(
                    _chunk_worker.chunk_batch_files,
                    group,
                    self.root_dir,
                    rule,
                    prep,
                )
                futures[future] = len(group)
                run_control.checkpoint()
        except BaseException:
            for future in futures:
                future.cancel()
            raise
        return futures

    def _submit_single_futures(
        self,
        pool: ProcessPoolExecutor,
        paths: list[pathlib.Path],
        prep: PreprocessContext | None,
        run_control: RunControl,
    ) -> dict[Future[_chunk_worker.ScopedChunkResult], pathlib.Path]:
        """Submit single-file worker tasks with cooperative cancellation."""
        futures: dict[Future[_chunk_worker.ScopedChunkResult], pathlib.Path] = {}
        try:
            for path in paths:
                run_control.checkpoint()
                future = pool.submit(
                    _chunk_worker.chunk_file_with_status,
                    path,
                    self.root_dir,
                    prep,
                )
                futures[future] = path
                run_control.checkpoint()
        except BaseException:
            for future in futures:
                future.cancel()
            raise
        return futures

    def _run_batch_groups(
        self,
        batch_groups: list[tuple[PreprocessRule, list[pathlib.Path]]],
        reporter: ProgressReporter,
        handle_group: Callable[[list[FileChunkResult]], None],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Run batch groups through a bounded spawned-worker window."""
        prep = getattr(self, "_prep_ctx", None)
        if not batch_groups or prep is None:
            return
        workers = self._resolve_chunk_workers(len(batch_groups))
        if workers <= 1:
            self._run_batch_groups_serial(
                batch_groups, reporter, handle_group, run_control=run_control
            )
            return

        completed = 0
        ctx = multiprocessing.get_context("spawn")
        try:
            with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
                group_iter = iter(batch_groups)
                futures: dict[Future[list[FileChunkResult]], int] = {}

                def _submit_one() -> bool:
                    run_control.checkpoint()
                    try:
                        rule, group = next(group_iter)
                    except StopIteration:
                        return False
                    future = pool.submit(
                        _chunk_worker.chunk_batch_files,
                        group,
                        self.root_dir,
                        rule,
                        prep,
                    )
                    futures[future] = len(group)
                    run_control.checkpoint()
                    return True

                try:
                    for _ in range(min(len(batch_groups), workers)):
                        _submit_one()
                    while futures:
                        run_control.checkpoint()
                        done, _pending = wait(
                            set(futures),
                            timeout=_CONTROL_POLL_SECONDS,
                            return_when=FIRST_COMPLETED,
                        )
                        run_control.checkpoint()
                        while done:
                            completed += self._process_batch_future(
                                done.pop(), futures, reporter, handle_group
                            )
                            run_control.checkpoint()
                            _submit_one()
                except BaseException:
                    for future in futures:
                        future.cancel()
                    raise
        except BrokenProcessPool:
            if completed:
                logger.error(
                    "Batch process pool broke after %d files; aborting",
                    completed,
                )
                raise
            logger.warning(
                "Batch process pool could not start; running batch groups serially"
            )
            self._run_batch_groups_serial(
                batch_groups, reporter, handle_group, run_control=run_control
            )

    def _process_batch_future(
        self,
        future: Future[list[FileChunkResult]],
        futures: dict[Future[list[FileChunkResult]], int],
        reporter: ProgressReporter,
        handle_group: Callable[[list[FileChunkResult]], None],
    ) -> int:
        """Publish one completed worker group, propagating fatal failures."""
        group_len = futures.pop(future)
        try:
            results = future.result()
        except BrokenProcessPool:
            raise
        except PreprocessAbortError:
            raise
        except Exception:
            logger.error(
                "Batch worker failed for a group of %d files",
                group_len,
                exc_info=True,
            )
            raise
        handle_group(results)
        for _ in range(group_len):
            reporter.advance()
        return group_len

    def _run_batch_groups_serial(
        self,
        batch_groups: list[tuple[PreprocessRule, list[pathlib.Path]]],
        reporter: ProgressReporter,
        handle_group: Callable[[list[FileChunkResult]], None],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Run batch groups serially in-process."""
        prep = getattr(self, "_prep_ctx", None)
        if prep is None:
            return
        for rule, group in batch_groups:
            run_control.checkpoint()
            results = _chunk_worker.chunk_batch_files(
                group, self.root_dir, rule, prep
            )
            handle_group(results)
            run_control.checkpoint()
            for _ in range(len(group)):
                reporter.advance()
            run_control.checkpoint()

    def _chunk_paths(
        self,
        paths: list[pathlib.Path],
        *,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> list[CodeChunk]:
        """Chunk files, batching batch-rule matches and pooling the rest.

        Files matched by a ``batch = true`` rule are grouped and run through the
        batch path (one spawn per group); every other file keeps the per-file
        process-pool flow. Returns all chunks across both, recording each file's
        preprocess disposition.

        Args:
            paths: Absolute file paths to chunk.
            reporter: Progress reporter, advanced once per file.

        Returns:
            All ``CodeChunk``s across every file, with empty vectors.
        """
        all_chunks: list[CodeChunk] = []
        if not paths:
            return all_chunks

        batch_groups, singles = self._partition_batch_work(
            paths,
            run_control=run_control,
        )

        def _collect(results: list[FileChunkResult]) -> None:
            for res in results:
                self._record_preprocess_result(res)
                all_chunks.extend(res.chunks)

        self._run_batch_groups(
            batch_groups,
            reporter,
            _collect,
            run_control=run_control,
        )
        if singles:
            all_chunks.extend(
                self._chunk_singles(
                    singles,
                    reporter,
                    run_control=run_control,
                )
            )
        return all_chunks

    def _chunk_singles(
        self,
        paths: list[pathlib.Path],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> list[CodeChunk]:
        """Chunk singles with a bounded spawned-worker submit window."""
        all_chunks: list[CodeChunk] = []
        if not paths:
            return all_chunks
        workers = self._plan_chunk_workers(paths)
        if workers <= 1:
            return self._chunk_singles_serial(
                paths, reporter, run_control=run_control
            )

        completed = 0
        ctx = multiprocessing.get_context("spawn")
        prep = getattr(self, "_prep_ctx", None)
        try:
            with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
                paths_iter = iter(paths)
                window = min(
                    len(paths), _CHUNK_FUTURE_WINDOW_PER_WORKER * workers
                )
                futures: dict[
                    Future[_chunk_worker.ScopedChunkResult], pathlib.Path
                ] = {}
                try:
                    for path in itertools.islice(paths_iter, window):
                        run_control.checkpoint()
                        futures[
                            pool.submit(
                                _chunk_worker.chunk_file_with_status,
                                path,
                                self.root_dir,
                                prep,
                            )
                        ] = path
                        run_control.checkpoint()
                    while futures:
                        run_control.checkpoint()
                        done, _pending = wait(
                            set(futures),
                            timeout=_CONTROL_POLL_SECONDS,
                            return_when=FIRST_COMPLETED,
                        )
                        run_control.checkpoint()
                        while done:
                            future = done.pop()
                            path = futures.pop(future)
                            self._process_single_future(
                                future, path, all_chunks, reporter
                            )
                            completed += 1
                            run_control.checkpoint()
                            next_path = next(paths_iter, None)
                            if next_path is not None:
                                futures[
                                    pool.submit(
                                        _chunk_worker.chunk_file_with_status,
                                        next_path,
                                        self.root_dir,
                                        prep,
                                    )
                                ] = next_path
                                run_control.checkpoint()
                except BaseException:
                    for future in futures:
                        future.cancel()
                    raise
        except BrokenProcessPool:
            if completed:
                logger.error(
                    "Chunk process pool broke after %d/%d files; aborting",
                    completed,
                    len(paths),
                )
                raise
            logger.warning("Chunk process pool could not start; chunking serially")
            return self._chunk_singles_serial(
                paths, reporter, run_control=run_control
            )
        return all_chunks

    def _process_single_future(
        self,
        future: Future[_chunk_worker.ScopedChunkResult],
        path: pathlib.Path,
        all_chunks: list[CodeChunk],
        reporter: ProgressReporter,
    ) -> None:
        """Publish one completed single-file result."""
        try:
            result = future.result()
        except BrokenProcessPool:
            raise
        except PreprocessAbortError:
            raise
        except Exception:
            logger.warning("Worker failed to chunk %s", path, exc_info=True)
            raise
        else:
            self._record_scoped_preprocess(path, result)
            all_chunks.extend(result.chunks)
        finally:
            reporter.advance()

    def _chunk_paths_serial(
        self,
        paths: list[pathlib.Path],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> list[CodeChunk]:
        """Chunk files serially in-process (single-worker / fallback path).

        Batch-rule matches are batched serially (one spawn per group); every
        other file is chunked one at a time. Returns all chunks across both.

        Args:
            paths: Absolute file paths to chunk.
            reporter: Progress reporter, advanced once per file.

        Returns:
            All ``CodeChunk``s across every file, with empty vectors.
        """
        all_chunks: list[CodeChunk] = []
        batch_groups, singles = self._partition_batch_work(
            paths,
            run_control=run_control,
        )

        def _collect(results: list[FileChunkResult]) -> None:
            for res in results:
                self._record_preprocess_result(res)
                all_chunks.extend(res.chunks)

        self._run_batch_groups_serial(
            batch_groups,
            reporter,
            _collect,
            run_control=run_control,
        )
        all_chunks.extend(
            self._chunk_singles_serial(
                singles,
                reporter,
                run_control=run_control,
            )
        )
        return all_chunks

    def _chunk_singles_serial(
        self,
        paths: list[pathlib.Path],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> list[CodeChunk]:
        """Chunk single files serially in-process."""
        all_chunks: list[CodeChunk] = []
        prep = getattr(self, "_prep_ctx", None)
        for path in paths:
            run_control.checkpoint()
            try:
                result = _chunk_worker.chunk_file_with_status(
                    path, self.root_dir, prep
                )
            except PreprocessAbortError:
                raise
            except Exception:
                logger.warning("Failed to chunk %s", path, exc_info=True)
                raise
            else:
                self._record_scoped_preprocess(path, result)
                all_chunks.extend(result.chunks)
            finally:
                reporter.advance()
            run_control.checkpoint()
        return all_chunks

    def _run_serial_chunk_producer(
        self,
        paths: list[pathlib.Path],
        publish_result: Callable[[FileChunkResult], bool],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> int:
        """Produce file results serially into the bounded queue."""
        advanced = 0
        for path in paths:
            run_control.checkpoint()
            try:
                result = _chunk_worker.chunk_and_hash_file(
                    path, self.root_dir, self._prep_ctx
                )
            except PreprocessAbortError:
                raise
            except Exception:
                logger.warning("Failed to chunk %s", path, exc_info=True)
                raise
            run_control.checkpoint()
            if not publish_result(result):
                raise RuntimeError("code-index segment consumer terminated")
            advanced += 1
            reporter.advance()
            run_control.checkpoint()
        return advanced

    def _produce_batch_groups(
        self,
        batch_groups: list[tuple[PreprocessRule, list[pathlib.Path]]],
        publish_result: Callable[[FileChunkResult], bool],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Produce batch-preprocessed results into the weighted queue."""

        def _publish_group(results: list[FileChunkResult]) -> None:
            for result in results:
                run_control.checkpoint()
                if not publish_result(result):
                    raise RuntimeError("code-index segment consumer terminated")
                run_control.checkpoint()

        self._run_batch_groups(
            batch_groups, reporter, _publish_group, run_control=run_control
        )

    def _drain_pool(
        self,
        workers: int,
        ctx: BaseContext,
        paths_iter: Iterator[pathlib.Path],
        window: int,
        publish_result: Callable[[FileChunkResult], bool],
        consumer_failed: Callable[[], bool],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[bool, bool, int]:
        """Drain a bounded spawned-worker window into the consumer."""
        broke = False
        consumer_died = False
        advanced = 0
        try:
            with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
                pending: set[Future[FileChunkResult]] = set()
                try:
                    for path in itertools.islice(paths_iter, window):
                        run_control.checkpoint()
                        pending.add(
                            pool.submit(
                                _chunk_worker.chunk_and_hash_file,
                                path,
                                self.root_dir,
                                self._prep_ctx,
                            )
                        )
                        run_control.checkpoint()
                    while pending and not consumer_died:
                        run_control.checkpoint()
                        if consumer_failed():
                            consumer_died = True
                            break
                        done, pending = wait(
                            pending,
                            timeout=_CONTROL_POLL_SECONDS,
                            return_when=FIRST_COMPLETED,
                        )
                        run_control.checkpoint()
                        for future in done:
                            died, advanced_inc = self._process_future(
                                future,
                                pool,
                                pending,
                                paths_iter,
                                publish_result,
                                reporter,
                                run_control=run_control,
                            )
                            advanced += advanced_inc
                            if died:
                                consumer_died = True
                                break
                    if consumer_died:
                        for future in pending:
                            future.cancel()
                except BaseException:
                    for future in pending:
                        future.cancel()
                    raise
        except BrokenProcessPool:
            broke = True
        return broke, consumer_died, advanced

    def _process_future(
        self,
        future: Future[FileChunkResult],
        pool: ProcessPoolExecutor,
        pending: set[Future[FileChunkResult]],
        paths_iter: Iterator[pathlib.Path],
        publish_result: Callable[[FileChunkResult], bool],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[bool, int]:
        """Publish one worker result and refill its bounded slot."""
        run_control.checkpoint()
        try:
            result = future.result()
        except BrokenProcessPool:
            raise
        except PreprocessAbortError:
            raise
        except Exception:
            logger.warning("Worker failed to chunk a file", exc_info=True)
            raise
        run_control.checkpoint()
        died = not publish_result(result)
        reporter.advance()
        run_control.checkpoint()
        if died:
            return True, 1
        next_path = next(paths_iter, None)
        if next_path is not None:
            run_control.checkpoint()
            pending.add(
                pool.submit(
                    _chunk_worker.chunk_and_hash_file,
                    next_path,
                    self.root_dir,
                    self._prep_ctx,
                )
            )
            run_control.checkpoint()
        return False, 1

    def _spawn_weighted_consumer(
        self,
        segment_queue: _WeightedCodeSegmentQueue,
        consumer_exceptions: list[BaseException],
        limits: _CodePipelineLimits,
        new_ids: set[str],
        total: list[int],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> threading.Thread:
        """Start the sole GPU consumer for weighted file segments."""
        import queue as queue_module
        import threading

        from ..memory_probe import MemoryProbe

        def _segments() -> Iterator[CodeFileSegment]:
            while True:
                run_control.checkpoint()
                try:
                    segment = segment_queue.get(timeout=_CONTROL_POLL_SECONDS)
                except queue_module.Empty:
                    continue
                run_control.checkpoint()
                if segment is None:
                    return
                yield segment

        def _consumer_loop() -> None:
            probe: MemoryProbe | None = None
            try:
                probe = MemoryProbe(name="codebase-index")
                with probe:
                    slice_index = 0
                    for weighted_slice in iter_weighted_code_slices(
                        _segments(),
                        max_chunks=limits.slice_max_chunks,
                        max_bytes=limits.slice_max_bytes,
                    ):
                        run_control.checkpoint()
                        slice_chunks = sorted(
                            weighted_slice.chunks,
                            key=lambda chunk: -len(chunk.content),
                        )
                        try:
                            probe.checkpoint(f"slice-{slice_index}-before-encode")
                            slice_index += 1
                            encode_and_upsert_code_slice(
                                slice_chunks,
                                model=self.model,
                                store=self.store,
                                gpu_lock=self._gpu_lock,
                                release_cache=(
                                    slice_index % limits.flush_slices == 0
                                ),
                                encode_batch_size=limits.encode_batch_size,
                                run_control=run_control,
                            )
                            run_control.checkpoint()
                            new_ids.update(chunk.id for chunk in slice_chunks)
                            total[0] += len(slice_chunks)
                            probe.checkpoint(f"slice-{slice_index}-after-store")
                        finally:
                            del slice_chunks
            except BaseException as exc:
                consumer_exceptions.append(exc)
            finally:
                try:
                    _release_cuda_cache()
                    if probe is not None and probe.samples:
                        logger.info("%s", probe.report())
                except BaseException as exc:
                    consumer_exceptions.append(exc)

        consumer = threading.Thread(
            target=_consumer_loop, name="codebase-indexer-consumer"
        )
        consumer.start()
        return consumer

    def _shutdown_consumer(
        self,
        consumer: threading.Thread,
        segment_queue: _WeightedCodeSegmentQueue,
    ) -> bool:
        """Send the sentinel and join within the shutdown bound."""
        deadline = time.monotonic() + _CONSUMER_SHUTDOWN_TIMEOUT_S
        while consumer.is_alive():
            try:
                segment_queue.put(None, timeout=_CONTROL_POLL_SECONDS)
                break
            except queue.Full:
                if time.monotonic() >= deadline:
                    break
        consumer.join(timeout=max(0.0, deadline - time.monotonic()))
        return consumer.is_alive()

    def _resolve_code_pipeline_limits(self) -> _CodePipelineLimits:
        """Freeze code segment, queue, slice, and model limits."""
        from ..config import get_config

        config = get_config()
        return _CodePipelineLimits(
            segment_max_chunks=int(config.index_segment_max_chunks),
            segment_max_bytes=int(config.index_segment_max_bytes),
            queue_max_chunks=int(config.index_queue_max_chunks),
            queue_max_bytes=int(config.index_queue_max_bytes),
            slice_max_chunks=int(config.index_queue_max_chunks),
            slice_max_bytes=int(config.index_queue_max_bytes),
            dense_dimension=int(config.embedding_dimension),
            sparse_enabled=bool(config.sparse_enabled),
            sparse_dimension=int(self.model.sparse_dimension),
            encode_batch_size=int(config.embedding_code_encode_batch_size),
            flush_slices=max(1, int(config.index_cache_flush_slices)),
        )

    def _enqueue_code_result(
        self,
        result: FileChunkResult,
        *,
        limits: _CodePipelineLimits,
        segment_queue: _WeightedCodeSegmentQueue,
        consumer: threading.Thread,
        consumer_exceptions: list[BaseException],
        metadata: dict[str, str],
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> bool:
        """Drain one file result into bounded weighted segments."""
        run_control.checkpoint()
        metadata[result.rel_path] = result.content_hash
        self._record_preprocess_result(result)
        segments = iter_code_file_segments(
            _drain_code_chunks(result.chunks),
            max_chunks=limits.segment_max_chunks,
            max_bytes=limits.segment_max_bytes,
            dense_dimension=limits.dense_dimension,
            sparse_enabled=limits.sparse_enabled,
            sparse_dimension=limits.sparse_dimension,
        )
        for segment in segments:
            while not consumer_exceptions and consumer.is_alive():
                run_control.checkpoint()
                try:
                    segment_queue.put(segment, timeout=_CONTROL_POLL_SECONDS)
                except queue.Full:
                    continue
                run_control.checkpoint()
                break
            else:
                return False
        return True

    def _produce_code_singles(
        self,
        singles: list[pathlib.Path],
        *,
        publish_result: Callable[[FileChunkResult], bool],
        consumer_failed: Callable[[], bool],
        reporter: ProgressReporter,
        total: list[int],
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> int:
        """Produce ordinary files serially or through the CPU pool."""
        workers = self._plan_chunk_workers(singles)
        if workers <= 1:
            return self._run_serial_chunk_producer(
                singles, publish_result, reporter, run_control=run_control
            )
        ctx = multiprocessing.get_context("spawn")
        window = min(
            len(singles),
            max(1, _CHUNK_FUTURE_WINDOW_PER_WORKER * workers),
        )
        broke, _consumer_died, advanced = self._drain_pool(
            workers,
            ctx,
            iter(singles),
            window,
            publish_result,
            consumer_failed,
            reporter,
            run_control=run_control,
        )
        if not broke:
            return advanced
        if advanced or total[0]:
            logger.error(
                "Chunk process pool broke after %d files (%d chunks embedded); "
                "aborting. Set index_chunk_workers=1 to force the serial path.",
                advanced,
                total[0],
            )
            raise BrokenProcessPool("codebase chunk process pool broke mid-run")
        logger.warning(
            "Chunk process pool could not start; running chunk + embed serially"
        )
        return self._run_serial_chunk_producer(
            singles, publish_result, reporter, run_control=run_control
        )

    def _finish_weighted_consumer(
        self,
        consumer: threading.Thread,
        segment_queue: _WeightedCodeSegmentQueue,
        consumer_exceptions: list[BaseException],
        producer_exception: BaseException | None,
    ) -> None:
        """Stop the consumer and preserve cleanup/error precedence."""
        if self._shutdown_consumer(consumer, segment_queue):
            logger.error(
                "GPU consumer thread did not terminate within %.0fs; "
                "aborting (a CUDA or Qdrant call may be wedged)",
                _CONSUMER_SHUTDOWN_TIMEOUT_S,
            )
            error = _UnsettledCodeConsumerError(
                "codebase index GPU consumer thread did not terminate"
            )
            if producer_exception is not None:
                raise error from producer_exception
            raise error
        consumer_failure = next(
            (
                exc
                for exc in consumer_exceptions
                if not isinstance(exc, RunControlSignal)
            ),
            None,
        )
        if consumer_failure is not None:
            raise consumer_failure
        if producer_exception is not None:
            raise producer_exception
        if consumer_exceptions:
            raise consumer_exceptions[0]

    def _pipeline_chunk_and_embed(
        self,
        paths: list[pathlib.Path],
        *,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[set[str], int, dict[str, str]]:
        """Overlap bounded CPU production with one weighted GPU consumer."""
        new_ids: set[str] = set()
        metadata: dict[str, str] = {}
        total = [0]
        self.store.disk_headroom_preflight(
            len(paths) * _CHUNKS_PER_FILE_ESTIMATE
        )
        run_control.checkpoint()
        reporter.phase_start("chunk + embed", len(paths))
        try:
            if not paths:
                return new_ids, total[0], metadata
            limits = self._resolve_code_pipeline_limits()
            segment_queue = _WeightedCodeSegmentQueue(
                max_chunks=limits.queue_max_chunks,
                max_bytes=limits.queue_max_bytes,
            )
            consumer_exceptions: list[BaseException] = []
            consumer = self._spawn_weighted_consumer(
                segment_queue,
                consumer_exceptions,
                limits,
                new_ids,
                total,
                run_control=run_control,
            )

            def _publish_result(result: FileChunkResult) -> bool:
                return self._enqueue_code_result(
                    result,
                    limits=limits,
                    segment_queue=segment_queue,
                    consumer=consumer,
                    consumer_exceptions=consumer_exceptions,
                    metadata=metadata,
                    run_control=run_control,
                )

            producer_exception: BaseException | None = None
            try:
                batch_groups, singles = self._partition_batch_work(
                    paths, run_control=run_control
                )
                if batch_groups:
                    self._produce_batch_groups(
                        batch_groups,
                        _publish_result,
                        reporter,
                        run_control=run_control,
                    )
                if singles:
                    self._produce_code_singles(
                        singles,
                        publish_result=_publish_result,
                        consumer_failed=lambda: (
                            bool(consumer_exceptions) or not consumer.is_alive()
                        ),
                        reporter=reporter,
                        total=total,
                        run_control=run_control,
                    )
            except BaseException as exc:
                producer_exception = exc
            finally:
                self._finish_weighted_consumer(
                    consumer,
                    segment_queue,
                    consumer_exceptions,
                    producer_exception,
                )
        finally:
            reporter.phase_end()
        run_control.checkpoint()
        return new_ids, total[0], metadata


    def _prepare_full_paths(
        self,
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> list[pathlib.Path]:
        """Resolve full-run inputs and scan with bounded control checkpoints."""
        self._begin_preprocess_run(run_control=run_control)
        run_control.checkpoint()
        inputs = self._resolve_scan_inputs()
        run_control.checkpoint()
        self._membership_epoch, self._content_epoch = self._compute_code_epochs(inputs)
        run_control.checkpoint()

        reporter.phase_start("scan codebase", None)
        try:
            paths = self._scan_codebase(inputs, run_control=run_control)
        finally:
            reporter.phase_end()
        run_control.checkpoint()
        return paths

    def _publish_incremental_replacement(
        self,
        *,
        chunks: list[CodeChunk],
        files_to_remove: set[str],
        old_chunk_ids: list[str],
        metadata: dict[str, str],
        slice_size: int,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Publish one incremental change set without exposing invalid files.

        The code pipeline batches chunks across changed files. When any old
        file state must be removed, the protected span conservatively covers
        the whole batched delete-and-replacement interval. This preserves GPU
        batching while ensuring every individual file replacement is valid at
        each cooperative safe edge. New-only publication remains interruptible.
        """
        run_control.checkpoint()
        replacement_span = (
            run_control.protected() if files_to_remove else contextlib.nullcontext()
        )
        with replacement_span:
            reporter.phase_start("delete removed", len(files_to_remove))
            try:
                if files_to_remove:
                    if old_chunk_ids:
                        self.store.delete_code_chunks(old_chunk_ids)
                    reporter.advance(len(files_to_remove))
            finally:
                reporter.phase_end()

            if chunks:
                _stream_encode_and_upsert_codebase(
                    chunks=chunks,
                    slice_size=slice_size,
                    model=self.model,
                    store=self.store,
                    gpu_lock=self._gpu_lock,
                    reporter=reporter,
                    run_control=run_control,
                )
            else:
                reporter.phase_start("embed + upsert chunks", 0)
                reporter.phase_end()

            reporter.phase_start("write metadata", 1)
            try:
                self._write_meta(metadata)
                reporter.advance(1)
            finally:
                reporter.phase_end()
        run_control.checkpoint()

    def _scan_and_hash_incremental_inputs(
        self,
        inputs: _ScanInputs,
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[dict[str, pathlib.Path], dict[str, str]]:
        """Scan and hash one unscoped incremental corpus cooperatively."""
        reporter.phase_start("scan codebase", None)
        try:
            current_paths = self._scan_codebase(inputs, run_control=run_control)
            current_files: dict[str, pathlib.Path] = {}
            for path in current_paths:
                run_control.checkpoint()
                current_files[
                    str(path.relative_to(self.root_dir)).replace("\\", "/")
                ] = path
                run_control.checkpoint()
        finally:
            reporter.phase_end()
        run_control.checkpoint()

        reporter.phase_start("hash files", len(current_files))
        current_hashes: dict[str, str] = {}
        try:
            for rel, path in current_files.items():
                run_control.checkpoint()
                try:
                    with open(path, "rb") as stream:
                        current_hashes[rel] = hashlib.file_digest(
                            stream,
                            "blake2b",
                        ).hexdigest()
                except OSError:
                    logger.warning("Cannot hash file, skipping: %s", rel)
                reporter.advance()
                run_control.checkpoint()
        finally:
            reporter.phase_end()
        run_control.checkpoint()

        for rel in set(current_files) - set(current_hashes):
            del current_files[rel]
        return current_files, current_hashes

    def full_index(
        self,
        clean: bool = False,
        *,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Full codebase re-index serialized through the writer lock.

        Thin wrapper that acquires ``self._writer_lock`` and delegates
        to :meth:`_full_index_locked`. Mirrors the VaultIndexer wrapper
        and serializes against concurrent reindex callers (#68 audit
        F6.6).
        """
        run_control.checkpoint()
        with self._writer_lock:
            run_control.checkpoint()
            log_event(
                logger,
                "service.index",
                "started",
                source="code",
                mode="full",
                clean=clean,
                root=self.root_dir,
            )
            try:
                # Stamp the activity clock at run START as well as at
                # completion: a long run spanning a maintenance tick must
                # advance the ephemeral idle clock before any reclaim
                # evaluation can see a stale stamp mid-write.
                run_control.checkpoint()
                self.store.touch_manifest_last_indexed()
                run_control.checkpoint()
                result = self._full_index_locked(
                    clean=clean,
                    reporter=reporter,
                    run_control=run_control,
                )
                run_control.checkpoint()
                self.store.touch_manifest_last_indexed()
                run_control.checkpoint()
            except Exception as exc:
                log_event(
                    logger,
                    "service.index",
                    "failed",
                    severity=logging.ERROR,
                    exc_info=True,
                    source="code",
                    mode="full",
                    clean=clean,
                    root=self.root_dir,
                    error=exc,
                )
                raise
            log_event(
                logger,
                "service.index",
                "completed",
                source="code",
                mode="full",
                clean=clean,
                root=self.root_dir,
                total=result.total,
                added=result.added,
                updated=result.updated,
                removed=result.removed,
                duration_ms=result.duration_ms,
                files=result.files,
                preprocess_rules=self._prep_rule_count(),
                preprocess_ok=result.preprocess_ok,
                preprocess_skipped=result.preprocess_skipped,
            )
            return result

    def _full_index_locked(
        self,
        clean: bool = False,
        *,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Locked implementation of :meth:`full_index`.

        Args:
            clean: When ``True``, drop and recreate the codebase
                collection up front so schema-level changes (e.g.
                a new embedding dimension) take effect (#68 audit
                F9.6 - codex P2). The default ``clean=False`` path
                is failure-safe: it streams upserts in place and
                purges only the stale chunk IDs after a successful
                rebuild, so an interrupted run never leaves the
                collection empty.
            reporter: Required progress reporter.
            run_control: Cooperative attempt control checked before the clean
                destructive span and delivered after valid collection and
                metadata publication.

        Returns:
            An ``IndexResult`` where ``added`` equals the total chunk
            count and ``removed`` reports the post-stream stale-chunk
            purge count.

        Raises:
            OSError: If source files cannot be read or hashed.
        """
        start = time.time()
        paths = self._prepare_full_paths(reporter, run_control=run_control)

        # Failure-safe rebuild (mirrors VaultIndexer.full_index): snapshot the
        # existing chunk ids BEFORE streaming, keep the old chunks live, and
        # purge only the ids absent from the new corpus afterwards. When
        # ``clean=True`` is passed, ALSO drop the collection up front so
        # schema-level changes (e.g. a new embedding dimension) take effect
        # (#68 audit F9.6). The snapshot must precede the pipeline because the
        # pipeline upserts as it goes; an empty tree still falls through to the
        # purge below so a rebuild after deleting every source file clears the
        # old collection (F3.11 regression guard).
        # A request already pending is delivered by ``protected`` before a
        # clean collection can be dropped. Once the drop begins, defer new
        # requests through recreation, the bounded producer/consumer pipeline,
        # stale cleanup, and atomic metadata publication. Non-clean rebuilding
        # remains failure-safe and interruptible between bounded slices.
        publication_span = (
            run_control.protected() if clean else contextlib.nullcontext()
        )
        with publication_span:
            reporter.phase_start("prepare collection", 1)
            try:
                if clean:
                    self.store.drop_code_table()
                    self._clear_preprocess_cache()
                    self.store.ensure_code_table()
                    # The collection was just dropped: the snapshot is
                    # empty by construction, and a full id scan of a large
                    # local collection costs minutes of GIL-holding CPU.
                    existing_ids_before: set[str] = set()
                else:
                    self.store.ensure_code_table()
                    try:
                        existing_ids_before = set(self.store.get_all_code_ids())
                    except (OSError, RuntimeError):
                        logger.warning(
                            "Could not snapshot existing code-chunk IDs "
                            "before rebuild; stale-chunk purge will be "
                            "skipped",
                            exc_info=True,
                        )
                        existing_ids_before = set()
                reporter.advance(1)
            finally:
                reporter.phase_end()
            run_control.checkpoint()

            # Pipelined chunk -> embed: process-pool workers read, hash, and chunk
            # files while the single in-process GPU consumer encodes and upserts
            # completed slices, so the GPU never idles waiting for the whole tree
            # to be chunked (#155 ADR P02). The workers return the content hash
            # from the same read, so ``meta`` needs no separate hash pass (P03).
            new_ids, total_chunks, meta = self._pipeline_chunk_and_embed(
                paths,
                reporter=reporter,
                run_control=run_control,
            )

            stale_ids = sorted(existing_ids_before - new_ids)
            run_control.checkpoint()
            reporter.phase_start("purge stale chunks", len(stale_ids))
            try:
                if stale_ids:
                    try:
                        self.store.delete_code_chunks(stale_ids)
                    except OSError:
                        logger.error(
                            "Failed to purge stale code chunks after "
                            "successful rebuild - collection still "
                            "contains valid new chunks plus %d stale rows",
                            len(stale_ids),
                        )
                        raise
                    reporter.advance(len(stale_ids))
            finally:
                reporter.phase_end()

            reporter.phase_start("write metadata", 1)
            try:
                self._write_meta(meta)
                reporter.advance(1)
            finally:
                reporter.phase_end()
        run_control.checkpoint()

        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total_chunks,
            added=total_chunks,
            updated=0,
            # Mirror VaultIndexer.full_index - surface the post-stream
            # purge count so MCP / CLI clients can observe how many
            # stale chunks were swept (#68 audit F6.3 / F6.10).
            removed=len(stale_ids),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(paths),
            preprocess_ok=self._prep_ok,
            preprocess_skipped=len(self._prep_skips),
            preprocess_failures=list(self._prep_skips),
        )

    def incremental_index(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Incremental codebase re-index serialized through the writer lock.

        Thin wrapper that acquires ``self._writer_lock`` and delegates
        to :meth:`_incremental_index_locked`. Mirrors VaultIndexer
        and serializes concurrent reindex callers (#68 audit F6.6).

        Args:
            reporter: Required progress reporter.
            changed_paths: When provided, only the given filesystem paths
                are reconciled (scoped reindex, #151). Work becomes
                proportional to the change set rather than the whole tree.
                When ``None`` the full ``.gitignore``-aware scan runs.
        """
        run_control.checkpoint()
        with self._writer_lock:
            run_control.checkpoint()
            mode = "scoped_incremental" if changed_paths is not None else "incremental"
            log_event(
                logger,
                "service.index",
                "started",
                source="code",
                mode=mode,
                clean=False,
                root=self.root_dir,
            )
            try:
                # Stamp the activity clock at run START as well as at
                # completion: a long run spanning a maintenance tick must
                # advance the ephemeral idle clock before any reclaim
                # evaluation can see a stale stamp mid-write.
                run_control.checkpoint()
                self.store.touch_manifest_last_indexed()
                run_control.checkpoint()
                result = self._incremental_index_locked(
                    reporter=reporter,
                    changed_paths=changed_paths,
                    run_control=run_control,
                )
                run_control.checkpoint()
                self.store.touch_manifest_last_indexed()
                run_control.checkpoint()
            except Exception as exc:
                log_event(
                    logger,
                    "service.index",
                    "failed",
                    severity=logging.ERROR,
                    exc_info=True,
                    source="code",
                    mode=mode,
                    clean=False,
                    root=self.root_dir,
                    error=exc,
                )
                raise
            log_event(
                logger,
                "service.index",
                "completed",
                source="code",
                mode=mode,
                clean=False,
                root=self.root_dir,
                total=result.total,
                added=result.added,
                updated=result.updated,
                removed=result.removed,
                duration_ms=result.duration_ms,
                files=result.files,
                preprocess_rules=self._prep_rule_count(),
                preprocess_ok=result.preprocess_ok,
                preprocess_skipped=result.preprocess_skipped,
            )
            return result

    def _incremental_index_locked(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Locked implementation of :meth:`incremental_index`.

        Uses blake2b content hashing to detect changes (not mtime). Emits
        phase events through ``reporter``.

        Args:
            reporter: Required progress reporter.
            changed_paths: When provided, delegates to
                :meth:`_scoped_incremental_locked`. When ``None`` the full
                codebase scan below runs.

        Returns:
            An ``IndexResult`` with counts for newly added, updated, and
            removed chunks since the last index run.

        Raises:
            OSError: If source files cannot be read or hashed.
        """
        run_control.checkpoint()
        needs_embed_rebuild = self._needs_embed_rebuild()
        run_control.checkpoint()
        if needs_embed_rebuild:
            logger.info(
                "Codebase embedding input format changed; running a "
                "one-time clean rebuild of the code collection",
            )
            return self._full_index_locked(
                clean=True,
                reporter=reporter,
                run_control=run_control,
            )

        inputs, changed_paths, escalate_clean = self._config_drift_dispatch(
            changed_paths,
            run_control=run_control,
        )
        if escalate_clean:
            logger.info(
                "Codebase content-shaping config changed; running a "
                "one-time clean rebuild of the code collection",
            )
            return self._full_index_locked(
                clean=True,
                reporter=reporter,
                run_control=run_control,
            )

        if changed_paths is not None:
            return self._scoped_incremental_locked(
                changed_paths=changed_paths,
                reporter=reporter,
                inputs=inputs,
                run_control=run_control,
            )

        from ..config import get_config

        start = time.time()
        slice_size = max(1, get_config().embedding_batch_size)
        self._begin_preprocess_run(run_control=run_control)

        run_control.checkpoint()
        prev_meta = self._load_meta()
        run_control.checkpoint()

        current_files, current_hashes = self._scan_and_hash_incremental_inputs(
            inputs,
            reporter,
            run_control=run_control,
        )

        prev_files = set(prev_meta.keys())
        curr_files = set(current_hashes.keys())
        new_files = curr_files - prev_files
        deleted_files = prev_files - curr_files
        modified_files = {
            f for f in curr_files & prev_files if current_hashes[f] != prev_meta.get(f)
        }

        to_index = new_files | modified_files
        all_new_chunks: list[CodeChunk] = []

        reporter.phase_start("chunk files", len(to_index))
        try:
            if to_index:
                paths_to_index = [current_files[f] for f in to_index]
                all_new_chunks = self._chunk_paths(
                    paths_to_index,
                    reporter=reporter,
                    run_control=run_control,
                )
        finally:
            reporter.phase_end()
        run_control.checkpoint()

        files_to_remove = modified_files | deleted_files
        old_chunk_ids: list[str] = []
        if files_to_remove:
            run_control.checkpoint()
            old_chunk_ids = self._get_chunk_ids_for_files(files_to_remove)
            run_control.checkpoint()

        self._publish_incremental_replacement(
            chunks=all_new_chunks,
            files_to_remove=files_to_remove,
            old_chunk_ids=old_chunk_ids,
            metadata=current_hashes,
            slice_size=slice_size,
            reporter=reporter,
            run_control=run_control,
        )

        total = self.store.count_code()
        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total,
            added=len(new_files),
            updated=len(modified_files),
            removed=len(deleted_files),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(to_index),
            preprocess_ok=self._prep_ok,
            preprocess_skipped=len(self._prep_skips),
            preprocess_failures=list(self._prep_skips),
        )

    def _scan_changed_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
        prev_meta: dict[str, str],
        reporter: ProgressReporter,
        inputs: _ScanInputs | None = None,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[dict[str, pathlib.Path], set[str]]:
        if inputs is None:
            inputs = self._resolve_scan_inputs()
        git_spec = inputs.git_spec
        rag_spec = inputs.rag_spec

        def _is_excluded(rel_path: str) -> bool:
            if git_spec.match_file(rel_path):
                return True
            return rag_spec is not None and rag_spec.match_file(rel_path)

        run_control.checkpoint()
        reporter.phase_start("scan changed", None)
        to_hash: dict[str, pathlib.Path] = {}
        delete_files: set[str] = set()
        try:
            for path in changed_paths:
                run_control.checkpoint()
                self._process_changed_path(
                    path,
                    prev_meta,
                    _is_excluded,
                    to_hash,
                    delete_files,
                    run_control=run_control,
                )
                run_control.checkpoint()
        finally:
            reporter.phase_end()
        run_control.checkpoint()
        return to_hash, delete_files

    def _process_changed_path(
        self,
        path: pathlib.Path,
        prev_meta: dict[str, str],
        _is_excluded: Callable[[str], bool],
        to_hash: dict[str, pathlib.Path],
        delete_files: set[str],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        run_control.checkpoint()
        try:
            rel = str(path.relative_to(self.root_dir)).replace("\\", "/")
        except ValueError:
            return
        if path.is_file() and not _is_excluded(rel):
            # A preprocess-rule match admits the file regardless of extension,
            # size, or binary content (D2, D8, D10) - the preprocessor turns it
            # into indexable text. Ignore was already applied above and wins.
            if self._matches_preprocess_rule(rel):
                to_hash[rel] = path
                return
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                try:
                    too_big = path.stat().st_size > _MAX_FILE_SIZE
                except OSError:
                    return
                if too_big or _is_binary(path):
                    if rel in prev_meta:
                        delete_files.add(rel)
                    return
                to_hash[rel] = path
                return
        if rel in prev_meta:
            delete_files.add(rel)
        run_control.checkpoint()

    def _hash_changed_paths(
        self,
        to_hash: dict[str, pathlib.Path],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> dict[str, str]:
        run_control.checkpoint()
        reporter.phase_start("hash files", len(to_hash))
        changed_hashes: dict[str, str] = {}
        try:
            for rel, path in to_hash.items():
                run_control.checkpoint()
                try:
                    with open(path, "rb") as f:
                        changed_hashes[rel] = hashlib.file_digest(
                            f,
                            "blake2b",
                        ).hexdigest()
                except OSError:
                    logger.warning("Cannot hash file, skipping: %s", rel)
                reporter.advance()
                run_control.checkpoint()
        finally:
            reporter.phase_end()
        run_control.checkpoint()
        return changed_hashes

    def _scoped_incremental_locked(
        self,
        *,
        changed_paths: Iterable[pathlib.Path],
        reporter: ProgressReporter,
        inputs: _ScanInputs | None = None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Reconcile only ``changed_paths`` against the code index (#151).

        Applies the same ``.gitignore``/``.vaultragignore``, extension,
        size, and binary filters as the full scan, then re-chunks the
        added/modified files, deletes chunks for vanished or
        no-longer-indexable files, and persists a partial read-modify-write
        of the hash metadata. Work is proportional to the change set.

        Args:
            changed_paths: Filesystem paths reported as changed.
            reporter: Required progress reporter.

        Returns:
            An ``IndexResult`` with added/updated/removed file counts and
            the post-reconcile total chunk count.
        """
        from ..config import get_config

        start = time.time()
        slice_size = max(1, get_config().embedding_batch_size)
        self._begin_preprocess_run(run_control=run_control)
        run_control.checkpoint()
        prev_meta = self._load_meta()
        run_control.checkpoint()

        to_hash, delete_files = self._scan_changed_paths(
            changed_paths,
            prev_meta,
            reporter,
            inputs,
            run_control=run_control,
        )
        changed_hashes = self._hash_changed_paths(
            to_hash,
            reporter,
            run_control=run_control,
        )

        for rel in set(to_hash) - set(changed_hashes):
            to_hash.pop(rel, None)

        new_files = {r for r in changed_hashes if r not in prev_meta}
        modified_files = {
            r
            for r in changed_hashes
            if r in prev_meta and changed_hashes[r] != prev_meta.get(r)
        }
        to_index = new_files | modified_files

        all_new_chunks: list[CodeChunk] = []
        reporter.phase_start("chunk files", len(to_index))
        try:
            if to_index:
                paths_to_index = [to_hash[r] for r in to_index]
                all_new_chunks = self._chunk_paths(
                    paths_to_index,
                    reporter=reporter,
                    run_control=run_control,
                )
        finally:
            reporter.phase_end()
        run_control.checkpoint()

        # Modified files have their old chunks dropped before re-upsert
        # (chunk ids embed line ranges + content hash, so stale chunks
        # would otherwise linger); vanished files are dropped outright.
        files_to_remove = modified_files | delete_files
        old_chunk_ids: list[str] = []
        if files_to_remove:
            run_control.checkpoint()
            old_chunk_ids = self._get_chunk_ids_for_files(files_to_remove)
            run_control.checkpoint()

        new_meta = dict(prev_meta)
        new_meta.update(changed_hashes)
        for rel in delete_files:
            new_meta.pop(rel, None)

        self._publish_incremental_replacement(
            chunks=all_new_chunks,
            files_to_remove=files_to_remove,
            old_chunk_ids=old_chunk_ids,
            metadata=new_meta,
            slice_size=slice_size,
            reporter=reporter,
            run_control=run_control,
        )

        total = self.store.count_code()
        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total,
            added=len(new_files),
            updated=len(modified_files),
            removed=len(delete_files),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(to_index),
            preprocess_ok=self._prep_ok,
            preprocess_skipped=len(self._prep_skips),
            preprocess_failures=list(self._prep_skips),
        )

    def _get_chunk_ids_for_files(
        self,
        rel_paths: set[str],
    ) -> list[str]:
        """Return chunk IDs from the store that belong to the given files.

        Args:
            rel_paths: Set of file paths (relative to the project
                root) whose chunk IDs should be retrieved.

        Returns:
            List of chunk ID strings stored for the given files.
        """
        return self.store.get_code_ids_by_paths(rel_paths)

    def _needs_embed_rebuild(self) -> bool:
        """Return True when stored vectors predate the embed-input format.

        Chunk vectors embed a locational header alongside the chunk
        text; older stores embedded the bare chunk text. Mixing the two
        regimes (and querying them with the current instruction prompt)
        silently degrades retrieval, so a marker mismatch triggers a
        one-time clean rebuild. A missing sidecar over a non-empty
        collection is treated the same way.
        """
        return _code_meta.needs_embed_rebuild(
            self._read_meta_raw(), self.store.count_code
        )

    def _write_meta(self, meta: dict[str, str]) -> None:
        """Atomically write content-hash metadata to the sidecar JSON file.

        Uses write-to-temp + ``os.replace`` so a crash mid-write never
        corrupts the metadata file. The current embedding-input format
        version is stamped under a reserved key so later runs can
        detect format changes.

        Args:
            meta: Mapping of relative file path to blake2b hex digest.

        Raises:
            OSError: If the metadata directory cannot be created or the
                file cannot be written.
        """
        membership = getattr(self, "_membership_epoch", None)
        content = getattr(self, "_content_epoch", None)
        if (membership is None or content is None) and getattr(
            self, "root_dir", None
        ) is not None:
            # Fallback for a direct call that did not resolve inputs this run;
            # recompute from the current config so the epochs are still stamped.
            membership, content = self._compute_code_epochs(self._resolve_scan_inputs())
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._meta_path.with_suffix(".tmp")
        stamped = {**meta, EMBED_SCHEMA_KEY: CODE_EMBED_SCHEMA}
        if membership is not None:
            stamped[MEMBERSHIP_EPOCH_KEY] = membership
        if content is not None:
            stamped[CONTENT_EPOCH_KEY] = content
        tmp_path.write_text(json.dumps(stamped, indent=2), encoding="utf-8")
        os.replace(tmp_path, self._meta_path)

    def _read_meta_raw(self) -> dict[str, str]:
        """Load the sidecar JSON verbatim, reserved keys included."""
        return _code_meta.read_meta_raw(self._meta_path)

    def _load_meta(self) -> dict[str, str]:
        """Load codebase index metadata from the sidecar JSON file.

        Reserved dunder keys (the embed-format marker) are stripped so
        they can never participate in file-path set arithmetic - the
        marker would otherwise be counted as a deleted file on every
        incremental run.

        Returns:
            Mapping of relative file path to blake2b hex digest, or
            an empty dict if the file does not exist or cannot be
            parsed.
        """
        return _code_meta.load_meta(self._meta_path)
