"""Source-code indexing orchestration.

Walks the project tree with gitignore-aware pruning, chunks files via
tree-sitter ASTs (or a text-splitter fallback), embeds, and upserts code
chunks, tracking content hashes for incremental re-indexing.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
import multiprocessing
import os
import pathlib
import queue
import time
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ProcessPoolExecutor,
    as_completed,
    wait,
)
from concurrent.futures.process import BrokenProcessPool
from typing import TYPE_CHECKING

from . import _chunk_worker
from ._chunking import (
    _MAX_FILE_SIZE,
    LANGUAGE_MAP,
    SUPPORTED_EXTENSIONS,
    _is_binary,
)
from ._streaming import (
    _stream_encode_and_upsert_codebase,
    encode_and_upsert_code_slice,
)
from ._vault_prep import IndexResult

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Iterable, Iterator

    import pathspec

    from ..embeddings import EmbeddingModel
    from ..progress import ProgressReporter
    from ..store import CodeChunk, VaultStore

logger = logging.getLogger(__name__)

# Upper bound on how long pipeline shutdown waits for the GPU consumer thread
# to drain its final batch and terminate. Generous enough for any healthy
# final encode (a couple of slices) yet finite, so a wedged CUDA/Qdrant call
# escalates to a raised error instead of hanging the producer and holding the
# indexer's writer lock forever (#155 index-gpu-pipeline review C1/H1/H2).
_CONSUMER_SHUTDOWN_TIMEOUT_S = 300.0


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
        self._meta_path = root_dir / cfg.data_dir / cfg.code_index_metadata_file

    @staticmethod
    def _get_language(path: pathlib.Path) -> str:
        """Return the language name for a file extension.

        Args:
            path: File path whose suffix determines the language.

        Returns:
            Language name string (e.g. ``"python"``), or ``"text"``
            if the extension is not in ``LANGUAGE_MAP``.
        """
        entry = LANGUAGE_MAP.get(path.suffix.lower())
        return entry[0] if entry else "text"

    def _build_gitignore_spec(self) -> pathspec.GitIgnoreSpec:
        """Build a pathspec from hardcoded exclusions and ``.gitignore`` files.

        Collects patterns from all ``.gitignore`` files in the project
        tree, prefixing each pattern by the file's relative directory
        so that patterns work correctly from the project root.

        Returns:
            A compiled ``GitIgnoreSpec`` covering hardcoded dirs and
            all ``.gitignore`` entries.
        """
        import pathspec

        from ..config import get_config

        cfg = get_config()
        patterns: list[str] = [
            # Always exclude these directories.
            ".venv/",
            ".git/",
            ".vault/",
            ".vaultspec/",
            "node_modules/",
            "__pycache__/",
            f"{cfg.data_dir}/",
        ]
        for gitignore in self.root_dir.rglob(".gitignore"):
            try:
                lines = gitignore.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                logger.debug("gitignore %s unreadable; skipping: %s", gitignore, exc)
                continue
            rel_dir = gitignore.parent.relative_to(self.root_dir)
            self._process_gitignore_lines(lines, rel_dir, patterns)

        return pathspec.GitIgnoreSpec.from_lines(patterns)

    def _process_gitignore_lines(
        self,
        lines: list[str],
        rel_dir: pathlib.Path,
        patterns: list[str],
    ) -> None:
        rel_dir_str = str(rel_dir)
        prefix = rel_dir_str.replace(chr(92), "/")
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if rel_dir_str == ".":
                patterns.append(stripped)
            else:
                if stripped.startswith("!"):
                    # Negation must stay at the start: !subdir/pattern
                    inner = stripped[1:].lstrip("/")
                    patterns.append(f"!{prefix}/{inner}")
                else:
                    patterns.append(f"{prefix}/{stripped.lstrip('/')}")

    def _build_vaultragignore_spec(self) -> pathspec.GitIgnoreSpec | None:
        """Build a pathspec from ``.vaultragignore`` and CLI ``--exclude`` patterns.

        Reads patterns from the ``.vaultragignore`` file at the project
        root (if it exists) and merges any ``extra_excludes`` passed via
        the constructor.  Returns ``None`` when no patterns are present.

        Returns:
            A compiled ``GitIgnoreSpec``, or ``None`` if there are no
            patterns to apply.
        """
        import pathspec

        patterns: list[str] = []
        ignore_file = self.root_dir / ".vaultragignore"
        if ignore_file.is_file():
            try:
                lines = ignore_file.read_text(encoding="utf-8").splitlines()
                patterns.extend(
                    line.strip()
                    for line in lines
                    if line.strip() and not line.strip().startswith("#")
                )
            except OSError as exc:
                logger.debug(
                    ".vaultragignore at %s unreadable; using --exclude only: %s",
                    ignore_file,
                    exc,
                )
        patterns.extend(self._extra_excludes)
        if not patterns:
            return None
        return pathspec.GitIgnoreSpec.from_lines(patterns)

    def _scan_codebase(self) -> list[pathlib.Path]:
        """Scan codebase for supported source files.

        Walks the project tree using ``os.walk``, pruning directories
        matched by ``.gitignore`` and ``.vaultragignore`` patterns via
        ``pathspec``.  The two specs are independent - a file is
        excluded if **either** matches (OR logic), so
        ``.vaultragignore`` can never un-ignore ``.gitignore`` entries.
        Skips binary files and files exceeding ``_MAX_FILE_SIZE``.

        Returns:
            List of absolute paths to indexable source files.

        Raises:
            OSError: If the root directory cannot be traversed.
        """
        git_spec = self._build_gitignore_spec()
        rag_spec = self._build_vaultragignore_spec()

        def _is_excluded(rel_path: str) -> bool:
            if git_spec.match_file(rel_path):
                return True
            return rag_spec is not None and rag_spec.match_file(rel_path)

        result: list[pathlib.Path] = []
        root_str = str(self.root_dir)
        for dirpath, dirs, files in os.walk(self.root_dir, topdown=True):
            # Prune ignored directories in-place to avoid traversal
            rel_dir = os.path.relpath(dirpath, root_str).replace("\\", "/")
            if rel_dir == ".":
                dirs[:] = [d for d in dirs if not _is_excluded(f"{d}/")]
            else:
                dirs[:] = [d for d in dirs if not _is_excluded(f"{rel_dir}/{d}/")]
            self._process_scan_files(dirpath, files, rel_dir, _is_excluded, result)
        return result

    def _process_scan_files(
        self,
        dirpath: str,
        files: list[str],
        rel_dir: str,
        _is_excluded: Callable[[str], bool],
        result: list[pathlib.Path],
    ) -> None:
        for fname in files:
            p = pathlib.Path(dirpath) / fname
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            rel = fname if rel_dir == "." else f"{rel_dir}/{fname}"
            if _is_excluded(rel):
                continue
            if p.stat().st_size > _MAX_FILE_SIZE:
                logger.debug("Skipping oversized file: %s", rel)
                continue
            if _is_binary(p):
                logger.debug("Skipping binary file: %s", rel)
                continue
            result.append(p)

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

    def _chunk_paths(
        self,
        paths: list[pathlib.Path],
        *,
        reporter: ProgressReporter,
    ) -> list[CodeChunk]:
        """Chunk files in parallel via a spawn-based process pool.

        tree-sitter AST chunking is CPU-bound and holds the GIL for both parse
        and traverse, so a process pool (not threads) is required to use more
        than one core. CUDA/torch are never touched in the workers, and the
        pool uses the ``spawn`` start method so no parent CUDA context is
        inherited (#155 ADR, rule ``index-workers-stay-cpu-only``). Falls back
        to the serial in-process path when a single worker is resolved, or when
        the pool cannot start before any progress has been reported.

        Args:
            paths: Absolute file paths to chunk.
            reporter: Progress reporter, advanced once per file.

        Returns:
            All ``CodeChunk``s across every file, with empty vectors.
        """
        all_chunks: list[CodeChunk] = []
        if not paths:
            return all_chunks

        workers = self._plan_chunk_workers(paths)
        if workers <= 1:
            return self._chunk_paths_serial(paths, reporter)

        completed = 0
        ctx = multiprocessing.get_context("spawn")
        try:
            with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
                futures = {
                    pool.submit(_chunk_worker.chunk_file, p, self.root_dir): p
                    for p in paths
                }
                for future in as_completed(futures):
                    try:
                        all_chunks.extend(future.result())
                    except BrokenProcessPool:
                        # Pool-level fatal - propagate rather than mis-record
                        # it as a single-file failure.
                        raise
                    except Exception:
                        logger.warning(
                            "Worker failed to chunk %s",
                            futures[future],
                            exc_info=True,
                        )
                    completed += 1
                    reporter.advance()
        except BrokenProcessPool:
            if completed:
                # Progress already reported for some files; re-chunking would
                # double-count. Fail loud rather than silently truncate.
                logger.error(
                    "Chunk process pool broke after %d/%d files; aborting",
                    completed,
                    len(paths),
                )
                raise
            logger.warning("Chunk process pool could not start; chunking serially")
            return self._chunk_paths_serial(paths, reporter)
        return all_chunks

    def _chunk_paths_serial(
        self,
        paths: list[pathlib.Path],
        reporter: ProgressReporter,
    ) -> list[CodeChunk]:
        """Chunk files serially in-process (single-worker / fallback path).

        Args:
            paths: Absolute file paths to chunk.
            reporter: Progress reporter, advanced once per file.

        Returns:
            All ``CodeChunk``s across every file, with empty vectors.
        """
        all_chunks: list[CodeChunk] = []
        for p in paths:
            try:
                all_chunks.extend(_chunk_worker.chunk_file(p, self.root_dir))
            except Exception:
                logger.warning("Failed to chunk %s", p, exc_info=True)
            reporter.advance()
        return all_chunks

    def _run_serial_chunk_and_embed(
        self,
        paths: list[pathlib.Path],
        meta: dict[str, str],
        encode_batch_size: int,
        flush_slices: int,
        reporter: ProgressReporter,
        total_in: int,
        new_ids: set[str],
    ) -> tuple[int, int]:
        from ..config import get_config

        slice_size = max(1, get_config().embedding_batch_size)
        total = total_in
        advanced = 0
        acc: list[CodeChunk] = []
        state = [0]

        def _encode_accumulated(force: bool) -> None:
            nonlocal total
            while len(acc) >= slice_size or (force and acc):
                take = acc[:slice_size]
                del acc[:slice_size]
                state[0] += 1
                is_final = force and not acc
                release = is_final or state[0] % flush_slices == 0
                encode_and_upsert_code_slice(
                    take,
                    model=self.model,
                    store=self.store,
                    gpu_lock=self._gpu_lock,
                    release_cache=release,
                    encode_batch_size=encode_batch_size,
                )
                new_ids.update(c.id for c in take)
                total += len(take)

        for p in paths:
            try:
                res = _chunk_worker.chunk_and_hash_file(p, self.root_dir)
                if res is not None:
                    meta[res.rel_path] = res.content_hash
                    acc.extend(res.chunks)
            except Exception:
                logger.warning("Failed to chunk %s", p, exc_info=True)
            advanced += 1
            reporter.advance()
            _encode_accumulated(force=False)
        _encode_accumulated(force=True)
        return total, advanced

    def _drain_pool(
        self,
        workers: int,
        ctx: multiprocessing.context.BaseContext,
        paths_iter: Iterator[pathlib.Path],
        window: int,
        meta: dict[str, str],
        put_fn: Callable[[list[CodeChunk]], bool],
        reporter: ProgressReporter,
    ) -> tuple[bool, bool, int]:
        from concurrent.futures import ProcessPoolExecutor

        _broke = False
        _consumer_died = False
        _advanced_inc = 0
        try:
            with ProcessPoolExecutor(
                max_workers=workers,
                mp_context=ctx,
            ) as pool:
                pending = {
                    pool.submit(
                        _chunk_worker.chunk_and_hash_file,
                        p,
                        self.root_dir,
                    )
                    for p in itertools.islice(paths_iter, window)
                }
                while pending and not _consumer_died:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for fut in done:
                        died, advanced_inc = self._process_future(
                            fut, pool, pending, paths_iter, meta, put_fn, reporter
                        )
                        _advanced_inc += advanced_inc
                        if died:
                            _consumer_died = True
                            break
        except BrokenProcessPool:
            _broke = True
        return _broke, _consumer_died, _advanced_inc

    def _process_future(
        self,
        fut: Future,
        pool: ProcessPoolExecutor,
        pending: set[Future],
        paths_iter: Iterator[pathlib.Path],
        meta: dict[str, str],
        put_fn: Callable[[list[CodeChunk]], bool],
        reporter: ProgressReporter,
    ) -> tuple[bool, int]:
        try:
            res = fut.result()
        except BrokenProcessPool:
            raise
        except Exception:
            logger.warning("Worker failed to chunk a file", exc_info=True)
            res = None

        died = False
        if res is not None:
            meta[res.rel_path] = res.content_hash
            if res.chunks and not put_fn(res.chunks):
                died = True

        reporter.advance()
        nxt = next(paths_iter, None)
        if nxt is not None:
            pending.add(
                pool.submit(_chunk_worker.chunk_and_hash_file, nxt, self.root_dir)
            )
        return died, 1

    def _spawn_consumer(
        self,
        chunk_q: queue.Queue[list[CodeChunk] | None],
        consumer_exc: list[BaseException],
        encode_fn: Callable[..., None],
    ) -> threading.Thread:
        import queue
        import threading

        def _consumer_loop() -> None:
            try:
                acc: list[CodeChunk] = []
                state = [0]
                while True:
                    try:
                        batch = chunk_q.get(timeout=1.0)
                    except queue.Empty:
                        continue
                    if batch is None:
                        encode_fn(acc, state, force=True)
                        break
                    acc.extend(batch)
                    encode_fn(acc, state, force=False)
            except BaseException as e:
                consumer_exc.append(e)

        consumer = threading.Thread(
            target=_consumer_loop, name="codebase-indexer-consumer"
        )
        consumer.start()
        return consumer

    def _shutdown_consumer(
        self, consumer: threading.Thread, chunk_q: queue.Queue[list[CodeChunk] | None]
    ) -> bool:
        import queue
        import time

        deadline = time.monotonic() + _CONSUMER_SHUTDOWN_TIMEOUT_S
        while consumer.is_alive():
            try:
                chunk_q.put(None, timeout=0.5)
                break
            except queue.Full:
                if time.monotonic() >= deadline:
                    break
        consumer.join(timeout=max(0.0, deadline - time.monotonic()))
        return consumer.is_alive()

    def _handle_pipeline_errors(
        self,
        consumer_hung: bool,
        consumer_exc: list[BaseException],
        broke: bool,
        advanced: int,
        total: int,
        run_serial_fn: Callable[[], None],
    ) -> None:
        from concurrent.futures.process import BrokenProcessPool

        if consumer_hung:
            logger.error(
                "GPU consumer thread did not terminate within %.0fs; "
                "aborting (a CUDA or Qdrant call may be wedged)",
                _CONSUMER_SHUTDOWN_TIMEOUT_S,
            )
            raise RuntimeError(
                "codebase index GPU consumer thread did not terminate",
            )
        if consumer_exc:
            raise consumer_exc[0]
        if broke:
            if advanced or total:
                logger.error(
                    "Chunk process pool broke after %d files (%d chunks "
                    "embedded); aborting. Set index_chunk_workers=1 to "
                    "force the serial path.",
                    advanced,
                    total,
                )
                raise BrokenProcessPool(
                    "codebase chunk process pool broke mid-run",
                )
            logger.warning(
                "Chunk process pool could not start; running chunk + embed serially",
            )
            run_serial_fn()

    def _do_encode_accumulated(
        self,
        acc: list[CodeChunk],
        state: list[int],
        force: bool,
        slice_size: int,
        flush_slices: int,
        encode_batch_size: int,
        new_ids: set[str],
    ) -> int:
        consumed = 0
        while len(acc) >= slice_size or (force and acc):
            take = acc[:slice_size]
            del acc[:slice_size]
            state[0] += 1
            is_final = force and not acc
            release = is_final or state[0] % flush_slices == 0
            encode_and_upsert_code_slice(
                take,
                model=self.model,
                store=self.store,
                gpu_lock=self._gpu_lock,
                release_cache=release,
                encode_batch_size=encode_batch_size,
            )
            new_ids.update(c.id for c in take)
            consumed += len(take)
        return consumed

    def _pipeline_chunk_and_embed(
        self,
        paths: list[pathlib.Path],
        *,
        slice_size: int,
        reporter: ProgressReporter,
    ) -> tuple[set[str], int, dict[str, str]]:
        """Overlap process-pool chunking with GPU encode/upsert.

        Worker processes read, hash, and chunk files in parallel while this
        thread - the sole CUDA consumer - encodes and upserts completed chunks
        in ``slice_size`` batches. A bounded submission window caps both
        in-flight futures and buffered results, so peak memory is proportional
        to the window rather than to the whole tree (#155 ADR P02, research
        O7). Each file is read exactly once: the worker returns the content
        hash alongside the chunks so no separate hash pass is needed (#155 P03,
        finding C4). The upsert is idempotent by chunk id, so streaming
        mid-rebuild preserves the failure-safe contract.

        Args:
            paths: Absolute file paths to chunk and embed.
            slice_size: Number of chunks per GPU encode/upsert batch.
            reporter: Progress reporter, advanced once per file chunked.

        Returns:
            ``(new_ids, total_chunks, meta)``: the set of upserted chunk ids,
            the total number of chunks embedded, and the relative-path to
            blake2b content-hash metadata for every readable file.
        """
        from ..config import get_config

        cfg = get_config()
        encode_batch_size = int(cfg.embedding_code_encode_batch_size)
        flush_slices = max(1, int(cfg.index_cache_flush_slices))

        new_ids: set[str] = set()
        meta: dict[str, str] = {}
        total = 0
        advanced = 0

        def _encode_accumulated(
            acc: list[CodeChunk],
            state: list[int],
            *,
            force: bool,
        ) -> None:
            nonlocal total
            consumed = self._do_encode_accumulated(
                acc, state, force, slice_size, flush_slices, encode_batch_size, new_ids
            )
            total += consumed

        def _run_serial() -> None:
            nonlocal advanced, total
            total, adv_inc = self._run_serial_chunk_and_embed(
                paths, meta, encode_batch_size, flush_slices, reporter, total, new_ids
            )
            advanced += adv_inc

        reporter.phase_start("chunk + embed", len(paths))
        try:
            if not paths:
                return new_ids, total, meta

            workers = self._plan_chunk_workers(paths)
            if workers <= 1:
                _run_serial()
                return new_ids, total, meta

            ctx = multiprocessing.get_context("spawn")
            window = max(2 * slice_size, 8 * workers)

            # Decoupled producer/consumer (#155 index-gpu-pipeline ADR): a
            # single dedicated GPU consumer thread drains a bounded queue while
            # this thread (the producer) drains the spawn pool and feeds it.
            # torch releases the GIL during async CUDA, so the producer refills
            # while the GPU runs - keeping the GPU saturated instead of idling
            # during pool bookkeeping. The queue's maxsize is the sole
            # backpressure + memory bound. The consumer owns the gpu_lock.
            # ``None`` is the shutdown sentinel: it is never a legitimate
            # payload because only non-empty chunk lists are ever enqueued.
            chunk_q: queue.Queue[list[CodeChunk] | None] = queue.Queue(
                maxsize=window,
            )
            consumer_exc: list[BaseException] = []

            consumer = self._spawn_consumer(chunk_q, consumer_exc, _encode_accumulated)

            def _put(chunks: list[CodeChunk]) -> bool:
                """Enqueue chunks; return False if the consumer has died."""
                while True:
                    if consumer_exc or not consumer.is_alive():
                        return False
                    try:
                        chunk_q.put(chunks, timeout=0.5)
                        return True
                    except queue.Full:
                        continue

            broke = False
            consumer_hung = False
            paths_iter = iter(paths)

            try:
                broke, _consumer_died, advanced_inc = self._drain_pool(
                    workers,
                    ctx,
                    paths_iter,
                    window,
                    meta,
                    _put,
                    reporter,
                )
                advanced += advanced_inc
            finally:
                consumer_hung = self._shutdown_consumer(consumer, chunk_q)

            self._handle_pipeline_errors(
                consumer_hung, consumer_exc, broke, advanced, total, _run_serial
            )
        finally:
            reporter.phase_end()
        return new_ids, total, meta

    def full_index(
        self,
        clean: bool = False,
        *,
        reporter: ProgressReporter,
    ) -> IndexResult:
        """Full codebase re-index serialized through the writer lock.

        Thin wrapper that acquires ``self._writer_lock`` and delegates
        to :meth:`_full_index_locked`. Mirrors the VaultIndexer wrapper
        and serializes against concurrent reindex callers (#68 audit
        F6.6).
        """
        with self._writer_lock:
            return self._full_index_locked(clean=clean, reporter=reporter)

    def _full_index_locked(
        self,
        clean: bool = False,
        *,
        reporter: ProgressReporter,
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

        Returns:
            An ``IndexResult`` where ``added`` equals the total chunk
            count and ``removed`` reports the post-stream stale-chunk
            purge count.

        Raises:
            OSError: If source files cannot be read or hashed.
        """
        from ..config import get_config

        start = time.time()
        slice_size = max(1, get_config().embedding_batch_size)

        reporter.phase_start("scan codebase", None)
        paths = self._scan_codebase()
        reporter.phase_end()

        # Failure-safe rebuild (mirrors VaultIndexer.full_index): snapshot the
        # existing chunk ids BEFORE streaming, keep the old chunks live, and
        # purge only the ids absent from the new corpus afterwards. When
        # ``clean=True`` is passed, ALSO drop the collection up front so
        # schema-level changes (e.g. a new embedding dimension) take effect
        # (#68 audit F9.6). The snapshot must precede the pipeline because the
        # pipeline upserts as it goes; an empty tree still falls through to the
        # purge below so a rebuild after deleting every source file clears the
        # old collection (F3.11 regression guard).
        reporter.phase_start("prepare collection", 1)
        try:
            if clean:
                self.store.drop_code_table()
            self.store.ensure_code_table()
            try:
                existing_ids_before: set[str] = set(self.store.get_all_code_ids())
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

        # Pipelined chunk -> embed: process-pool workers read, hash, and chunk
        # files while the single in-process GPU consumer encodes and upserts
        # completed slices, so the GPU never idles waiting for the whole tree
        # to be chunked (#155 ADR P02). The workers return the content hash
        # from the same read, so ``meta`` needs no separate hash pass (P03).
        new_ids, total_chunks, meta = self._pipeline_chunk_and_embed(
            paths,
            slice_size=slice_size,
            reporter=reporter,
        )

        stale_ids = sorted(existing_ids_before - new_ids)
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
        )

    def incremental_index(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
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
        with self._writer_lock:
            return self._incremental_index_locked(
                reporter=reporter,
                changed_paths=changed_paths,
            )

    def _incremental_index_locked(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
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
        if changed_paths is not None:
            return self._scoped_incremental_locked(
                changed_paths=changed_paths,
                reporter=reporter,
            )

        from ..config import get_config

        start = time.time()
        slice_size = max(1, get_config().embedding_batch_size)

        prev_meta = self._load_meta()

        reporter.phase_start("scan codebase", None)
        current_paths = self._scan_codebase()
        current_files: dict[str, pathlib.Path] = {
            str(p.relative_to(self.root_dir)).replace("\\", "/"): p
            for p in current_paths
        }
        reporter.phase_end()

        reporter.phase_start("hash files", len(current_files))
        current_hashes: dict[str, str] = {}
        for rel, path in current_files.items():
            try:
                with open(path, "rb") as f:
                    current_hashes[rel] = hashlib.file_digest(
                        f,
                        "blake2b",
                    ).hexdigest()
            except OSError:
                logger.warning("Cannot hash file, skipping: %s", rel)
            reporter.advance()
        reporter.phase_end()

        for rel in set(current_files) - set(current_hashes):
            del current_files[rel]

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
        if to_index:
            paths_to_index = [current_files[f] for f in to_index]
            all_new_chunks = self._chunk_paths(paths_to_index, reporter=reporter)
        reporter.phase_end()

        files_to_remove = modified_files | deleted_files
        reporter.phase_start("delete removed", len(files_to_remove))
        if files_to_remove:
            old_chunk_ids = self._get_chunk_ids_for_files(files_to_remove)
            if old_chunk_ids:
                self.store.delete_code_chunks(old_chunk_ids)
            reporter.advance(len(files_to_remove))
        reporter.phase_end()

        if all_new_chunks:
            _stream_encode_and_upsert_codebase(
                chunks=all_new_chunks,
                slice_size=slice_size,
                model=self.model,
                store=self.store,
                gpu_lock=self._gpu_lock,
                reporter=reporter,
            )
        else:
            reporter.phase_start("embed + upsert chunks", 0)
            reporter.phase_end()

        reporter.phase_start("write metadata", 1)
        self._write_meta(current_hashes)
        reporter.advance(1)
        reporter.phase_end()

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
        )

    def _scan_changed_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
        prev_meta: dict[str, str],
        reporter: ProgressReporter,
    ) -> tuple[dict[str, pathlib.Path], set[str]]:
        git_spec = self._build_gitignore_spec()
        rag_spec = self._build_vaultragignore_spec()

        def _is_excluded(rel_path: str) -> bool:
            if git_spec.match_file(rel_path):
                return True
            return rag_spec is not None and rag_spec.match_file(rel_path)

        reporter.phase_start("scan changed", None)
        to_hash: dict[str, pathlib.Path] = {}
        delete_files: set[str] = set()
        for path in changed_paths:
            self._process_changed_path(
                path, prev_meta, _is_excluded, to_hash, delete_files
            )
        reporter.phase_end()
        return to_hash, delete_files

    def _process_changed_path(
        self,
        path: pathlib.Path,
        prev_meta: dict[str, str],
        _is_excluded: Callable[[str], bool],
        to_hash: dict[str, pathlib.Path],
        delete_files: set[str],
    ) -> None:
        try:
            rel = str(path.relative_to(self.root_dir)).replace("\\", "/")
        except ValueError:
            return
        indexable = (
            path.is_file()
            and path.suffix.lower() in SUPPORTED_EXTENSIONS
            and not _is_excluded(rel)
        )
        if indexable:
            try:
                too_big = path.stat().st_size > _MAX_FILE_SIZE
            except OSError:
                return
            if too_big or _is_binary(path):
                if rel in prev_meta:
                    delete_files.add(rel)
                return
            to_hash[rel] = path
        elif rel in prev_meta:
            delete_files.add(rel)

    def _hash_changed_paths(
        self,
        to_hash: dict[str, pathlib.Path],
        reporter: ProgressReporter,
    ) -> dict[str, str]:
        reporter.phase_start("hash files", len(to_hash))
        changed_hashes: dict[str, str] = {}
        for rel, path in to_hash.items():
            try:
                with open(path, "rb") as f:
                    changed_hashes[rel] = hashlib.file_digest(
                        f,
                        "blake2b",
                    ).hexdigest()
            except OSError:
                logger.warning("Cannot hash file, skipping: %s", rel)
            reporter.advance()
        reporter.phase_end()
        return changed_hashes

    def _scoped_incremental_locked(
        self,
        *,
        changed_paths: Iterable[pathlib.Path],
        reporter: ProgressReporter,
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
        prev_meta = self._load_meta()

        to_hash, delete_files = self._scan_changed_paths(
            changed_paths, prev_meta, reporter
        )
        changed_hashes = self._hash_changed_paths(to_hash, reporter)

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
        if to_index:
            paths_to_index = [to_hash[r] for r in to_index]
            all_new_chunks = self._chunk_paths(paths_to_index, reporter=reporter)
        reporter.phase_end()

        # Modified files have their old chunks dropped before re-upsert
        # (chunk ids embed line ranges + content hash, so stale chunks
        # would otherwise linger); vanished files are dropped outright.
        files_to_remove = modified_files | delete_files
        reporter.phase_start("delete removed", len(files_to_remove))
        if files_to_remove:
            old_chunk_ids = self._get_chunk_ids_for_files(files_to_remove)
            if old_chunk_ids:
                self.store.delete_code_chunks(old_chunk_ids)
            reporter.advance(len(files_to_remove))
        reporter.phase_end()

        if all_new_chunks:
            _stream_encode_and_upsert_codebase(
                chunks=all_new_chunks,
                slice_size=slice_size,
                model=self.model,
                store=self.store,
                gpu_lock=self._gpu_lock,
                reporter=reporter,
            )
        else:
            reporter.phase_start("embed + upsert chunks", 0)
            reporter.phase_end()

        new_meta = dict(prev_meta)
        new_meta.update(changed_hashes)
        for rel in delete_files:
            new_meta.pop(rel, None)
        reporter.phase_start("write metadata", 1)
        self._write_meta(new_meta)
        reporter.advance(1)
        reporter.phase_end()

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

    def _write_meta(self, meta: dict[str, str]) -> None:
        """Atomically write content-hash metadata to the sidecar JSON file.

        Uses write-to-temp + ``os.replace`` so a crash mid-write never
        corrupts the metadata file.

        Args:
            meta: Mapping of relative file path to blake2b hex digest.

        Raises:
            OSError: If the metadata directory cannot be created or the
                file cannot be written.
        """
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._meta_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        os.replace(tmp_path, self._meta_path)

    def _load_meta(self) -> dict[str, str]:
        """Load codebase index metadata from the sidecar JSON file.

        Returns:
            Mapping of relative file path to blake2b hex digest, or
            an empty dict if the file does not exist or cannot be
            parsed.
        """
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except (KeyError, ValueError, OSError) as exc:
            logger.debug(
                "codebase meta %s unreadable; treating as empty: %s",
                self._meta_path,
                exc,
                exc_info=True,
            )
            return {}
