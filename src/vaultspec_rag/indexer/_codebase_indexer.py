"""Source-code indexing orchestration.

Walks the project tree with gitignore-aware pruning, chunks files via
tree-sitter ASTs (or a text-splitter fallback), embeds, and upserts code
chunks, tracking content hashes for incremental re-indexing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from ._ast_chunker import ASTChunker
from ._chunking import (
    _MAX_FILE_SIZE,
    LANGUAGE_MAP,
    SUPPORTED_EXTENSIONS,
    TextSplitter,
    _is_binary,
)
from ._streaming import _stream_encode_and_upsert_codebase
from ._vault_prep import IndexResult

if TYPE_CHECKING:
    import threading

    import pathspec

    from ..embeddings import EmbeddingModel
    from ..progress import ProgressReporter
    from ..store import VaultStore

from ..store import CodeChunk

logger = logging.getLogger(__name__)


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
        # (#68 audit F6.6 — concurrent reindex race).
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
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if str(rel_dir) == ".":
                    patterns.append(stripped)
                else:
                    prefix = str(rel_dir).replace(chr(92), "/")
                    if stripped.startswith("!"):
                        # Negation must stay at the start: !subdir/pattern
                        inner = stripped[1:].lstrip("/")
                        patterns.append(f"!{prefix}/{inner}")
                    else:
                        patterns.append(f"{prefix}/{stripped.lstrip('/')}")

        return pathspec.GitIgnoreSpec.from_lines(patterns)

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
        ``pathspec``.  The two specs are independent — a file is
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
        return result

    def scan_files(self) -> list[pathlib.Path]:
        """Return the list of files that would be indexed.

        Does not require GPU or vector store — safe to call with
        ``model=None`` and ``store=None`` for dry-run usage.

        Returns:
            List of absolute paths to indexable source files.
        """
        return self._scan_codebase()

    def _chunk_file(self, path: pathlib.Path) -> list[CodeChunk]:
        """Read file and split into AST-aware CodeChunks.

        Uses tree-sitter AST chunking for languages with grammars,
        falling back to TextSplitter for config/data formats.

        Args:
            path: Absolute path to the source file.

        Returns:
            List of ``CodeChunk`` instances with empty vectors.
        """
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Cannot read %s: %s", path, e)
            return []

        ext = path.suffix.lower()
        lang_entry = LANGUAGE_MAP.get(ext)
        language = lang_entry[0] if lang_entry else "text"
        grammar = lang_entry[1] if lang_entry else None
        rel_path = str(path.relative_to(self.root_dir)).replace("\\", "/")

        if grammar:
            return self._chunk_with_ast(content, rel_path, language, grammar)
        return self._chunk_with_splitter(content, rel_path, language)

    def _chunk_with_ast(
        self,
        content: str,
        rel_path: str,
        language: str,
        grammar: str,
    ) -> list[CodeChunk]:
        """Chunk source code using tree-sitter AST.

        Falls back to ``_chunk_with_splitter`` if AST parsing fails
        (e.g. syntax errors or missing grammar).

        Args:
            content: Source code text.
            rel_path: File path relative to the project root.
            language: Language name (e.g. ``"python"``).
            grammar: tree-sitter grammar name (e.g. ``"python"``).

        Returns:
            List of ``CodeChunk`` instances with empty vectors.
        """
        chunker = ASTChunker()
        try:
            ast_chunks = chunker.chunk(content, grammar)
        except Exception:
            logger.warning(
                "AST parsing failed for %s, falling back to text splitter",
                rel_path,
                exc_info=True,
            )
            return self._chunk_with_splitter(content, rel_path, language)

        chunks: list[CodeChunk] = []
        for (
            text,
            line_start,
            line_end,
            node_type,
            function_name,
            class_name,
        ) in ast_chunks:
            if not text.strip():
                continue
            chunk_hash = hashlib.blake2b(
                text.encode("utf-8"),
                digest_size=6,
            ).hexdigest()
            chunks.append(
                CodeChunk(
                    id=f"{rel_path}:{line_start}-{line_end}:{chunk_hash}",
                    path=rel_path,
                    language=language,
                    content=text,
                    line_start=line_start,
                    line_end=line_end,
                    node_type=node_type,
                    function_name=function_name,
                    class_name=class_name,
                    vector=[],
                ),
            )
        return chunks

    def _chunk_with_splitter(
        self,
        content: str,
        rel_path: str,
        language: str,
    ) -> list[CodeChunk]:
        """Chunk content using TextSplitter for non-AST languages.

        Args:
            content: Source code or config file text.
            rel_path: File path relative to the project root.
            language: Language name passed to ``TextSplitter`` for
                separator selection.

        Returns:
            List of ``CodeChunk`` instances with empty vectors.
        """
        # chunk_overlap=0 is required: non-zero overlap prepends content from the
        # previous chunk, making chunks not findable verbatim in the original source.
        # This breaks line number tracking in _chunk_with_splitter.
        splitter = TextSplitter(language=language, chunk_overlap=0)
        text_chunks = splitter.split_text(content)

        chunks: list[CodeChunk] = []
        search_offset = 0
        for text in text_chunks:
            idx = content.find(text, search_offset)
            if idx != -1:
                line_start = content.count("\n", 0, idx) + 1
                search_offset = idx + len(text)
            else:
                # Chunk not found verbatim — happens when TextSplitter overlap
                # is > 0 and prepended tail text shifts the chunk boundary.
                # Fall back to search_offset as approximation; line number
                # may be off by the overlap size.
                logger.debug(
                    "Chunk not found verbatim in %s at offset %d; "
                    "line_start is approximate (chunk_overlap > 0?)",
                    rel_path,
                    search_offset,
                )
                line_start = content.count("\n", 0, search_offset) + 1
                search_offset += len(text)
            line_end = line_start + text.count("\n")

            chunk_hash = hashlib.blake2b(
                text.encode("utf-8"),
                digest_size=6,
            ).hexdigest()
            chunks.append(
                CodeChunk(
                    id=f"{rel_path}:{line_start}-{line_end}:{chunk_hash}",
                    path=rel_path,
                    language=language,
                    content=text,
                    line_start=line_start,
                    line_end=line_end,
                    vector=[],
                ),
            )
        return chunks

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
                F9.6 — codex P2). The default ``clean=False`` path
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

        reporter.phase_start("hash files", len(paths))
        meta: dict[str, str] = {}
        for p in paths:
            rel = str(p.relative_to(self.root_dir)).replace("\\", "/")
            try:
                with open(p, "rb") as f:
                    meta[rel] = hashlib.file_digest(f, "blake2b").hexdigest()
            except OSError:
                logger.warning("Cannot hash file for metadata: %s", rel)
            reporter.advance()
        reporter.phase_end()

        reporter.phase_start("chunk files", len(paths))
        all_chunks: list[CodeChunk] = []
        with ThreadPoolExecutor() as pool:
            futures = [pool.submit(self._chunk_file, p) for p in paths]
            for future in as_completed(futures):
                try:
                    file_chunks = future.result()
                except Exception:
                    logger.warning("Worker failed to chunk file", exc_info=True)
                    reporter.advance()
                    continue
                all_chunks.extend(file_chunks)
                reporter.advance()
        reporter.phase_end()

        # Fall through on an empty codebase as well — the purge step
        # must still run so a rebuild after deleting every source
        # file actually clears the old collection (F3.11 regression
        # guard).

        # Failure-safe rebuild (mirrors VaultIndexer.full_index): keep
        # the old chunks live until after streaming succeeds, then
        # purge only the chunk IDs that are absent from the new corpus.
        # When ``clean=True`` is explicitly passed, ALSO drop the
        # collection up front so schema-level changes (e.g. new
        # embedding dimension) take effect (#68 audit F9.6). The
        # default ``clean=False`` path remains failure-safe.
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

        _stream_encode_and_upsert_codebase(
            chunks=all_chunks,
            slice_size=slice_size,
            model=self.model,
            store=self.store,
            gpu_lock=self._gpu_lock,
            reporter=reporter,
        )

        new_ids = {chunk.id for chunk in all_chunks}
        stale_ids = sorted(existing_ids_before - new_ids)
        reporter.phase_start("purge stale chunks", len(stale_ids))
        try:
            if stale_ids:
                try:
                    self.store.delete_code_chunks(stale_ids)
                except OSError:
                    logger.error(
                        "Failed to purge stale code chunks after "
                        "successful rebuild — collection still "
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
            total=len(all_chunks),
            added=len(all_chunks),
            updated=0,
            # Mirror VaultIndexer.full_index — surface the post-stream
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
    ) -> IndexResult:
        """Incremental codebase re-index serialized through the writer lock.

        Thin wrapper that acquires ``self._writer_lock`` and delegates
        to :meth:`_incremental_index_locked`. Mirrors VaultIndexer
        and serializes concurrent reindex callers (#68 audit F6.6).
        """
        with self._writer_lock:
            return self._incremental_index_locked(reporter=reporter)

    def _incremental_index_locked(
        self,
        *,
        reporter: ProgressReporter,
    ) -> IndexResult:
        """Locked implementation of :meth:`incremental_index`.

        Uses blake2b content hashing to detect changes (not mtime). Emits
        phase events through ``reporter``.

        Args:
            reporter: Required progress reporter.

        Returns:
            An ``IndexResult`` with counts for newly added, updated, and
            removed chunks since the last index run.

        Raises:
            OSError: If source files cannot be read or hashed.
        """
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
            with ThreadPoolExecutor() as pool:
                futures = [pool.submit(self._chunk_file, p) for p in paths_to_index]
                for future in as_completed(futures):
                    try:
                        file_chunks = future.result()
                    except Exception:
                        logger.warning("Worker failed to chunk file", exc_info=True)
                        reporter.advance()
                        continue
                    all_new_chunks.extend(file_chunks)
                    reporter.advance()
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
