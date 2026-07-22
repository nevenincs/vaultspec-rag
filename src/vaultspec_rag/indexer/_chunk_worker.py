"""CPU-only chunking worker for the process-pool indexer.

This module is imported and executed inside spawn-started worker processes. It
must never construct an :class:`~vaultspec_rag.embeddings.EmbeddingModel`, touch
``torch.cuda``, or otherwise initialise a CUDA context: the embedding GPU is the
exclusive province of the single in-process consumer. Workers that initialise
CUDA reintroduce the fork/spawn CUDA-context crash class. The pool is always
created with the ``spawn`` start method so no parent CUDA context is inherited.
See ADR ``2026-06-02-index-perf-hardening`` and rule
``index-workers-stay-cpu-only``.

The chunking logic here is the byte-for-byte equivalent of the former
``CodebaseIndexer._chunk_file`` / ``_chunk_with_ast`` / ``_chunk_with_splitter``
methods, relocated to module scope so the worker callable is picklable and so
the in-process fallback shares the exact same code path (guaranteeing
chunk-identity parity between serial and parallel runs).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..store import CodeChunk
from ._ast_chunker import ASTChunker
from ._chunking import LANGUAGE_MAP, TextSplitter
from ._preprocess_cache import read_cached_output, write_cached_output
from ._preprocess_runner import run_preprocessor, run_preprocessor_batch

if TYPE_CHECKING:
    import pathlib

    from ._preprocess_config import PreprocessContext, PreprocessRule
    from ._preprocess_runner import PreprocessResult
    from ._preprocess_schema import PreprocOutput

logger = logging.getLogger(__name__)

# Per-worker reusable chunker. ``ASTChunker`` itself is cheap to build, but the
# tree-sitter parsers it drives are cached inside ``tree_sitter_language_pack``
# across calls, so a single instance per process avoids repeated lookups over
# tens of thousands of files (research O3).
_CHUNKER: ASTChunker | None = None


@dataclass(slots=True)
class FileChunkResult:
    """One file's chunks plus its content hash, returned from a worker.

    Carrying the blake2b hash back from the same read that produced the chunks
    lets the full-index path skip the separate hash pass - the tree is read
    once, not twice (#155 P03 / finding C4). ``slots=True`` keeps the pickled
    payload that crosses the process boundary lean (research O3).

    ``preprocess_status`` records the disposition of a document-preprocessing
    rule when one matched this file (#185): ``ok`` (chunks came from the
    preprocessor), ``skipped`` (the preprocessor failed under ``on_error=skip``;
    no chunks), ``passthrough`` (the raw file was chunked normally), or ``None``
    (no rule matched). The orchestrator accumulates skip counts and reasons from
    these for failure-visibility surfacing (D11).
    """

    rel_path: str
    content_hash: str
    chunks: list[CodeChunk]
    preprocess_status: str | None = None
    preprocess_reason: str | None = None


@dataclass(slots=True)
class _PreprocessOutcome:
    """Internal result of attempting to preprocess one file in the worker."""

    status: str  # "none" | "ok" | "skipped" | "passthrough"
    chunks: list[CodeChunk]
    reason: str | None


def _split_locator_value(value: int | str | None) -> tuple[int | None, str | None]:
    """Split a polymorphic locator value into typed (int, str) payload fields.

    ``bool`` is treated as a string so it never lands in the INTEGER field.
    """
    if isinstance(value, bool):
        return None, str(value)
    if isinstance(value, int):
        return value, None
    if isinstance(value, str):
        return None, value
    return None, None


def _chunks_from_output(output: PreprocOutput, rel_path: str) -> list[CodeChunk]:
    """Build ``CodeChunk``s from validated preprocessor output (D6, D12).

    In ``units`` mode each unit becomes one chunk carrying its anchor and split
    locator. In ``text`` mode the emitted text is run through the ordinary text
    splitter and each resulting chunk is stamped with the source path and
    preprocessor id so it is identifiable and purgeable by source path.
    """
    if output.units is not None:
        chunks: list[CodeChunk] = []
        for index, unit in enumerate(output.units):
            locator = unit.locator
            locator_kind = locator.kind if locator is not None else None
            value_int, value_str = _split_locator_value(
                locator.value if locator is not None else None
            )
            end_int, end_str = _split_locator_value(
                locator.end if locator is not None else None
            )
            chunk_hash = hashlib.blake2b(
                unit.text.encode("utf-8"),
                digest_size=6,
            ).hexdigest()
            chunks.append(
                CodeChunk(
                    id=f"{rel_path}::pp:{index}:{chunk_hash}",
                    path=rel_path,
                    language="text",
                    content=unit.text,
                    line_start=0,
                    line_end=0,
                    source_path=rel_path,
                    preprocessor_id=output.preprocessor_id,
                    anchor=unit.anchor,
                    locator_kind=locator_kind,
                    locator_value_int=value_int,
                    locator_value_str=value_str,
                    locator_end_int=end_int,
                    locator_end_str=end_str,
                    vector=[],
                ),
            )
        return chunks

    text = output.text or ""
    chunks = chunk_with_splitter(text, rel_path, "text")
    for chunk in chunks:
        chunk.source_path = rel_path
        chunk.preprocessor_id = output.preprocessor_id
    return chunks


def preprocess_file(
    content_hash: str,
    path: pathlib.Path,
    root_dir: pathlib.Path,
    prep: PreprocessContext,
) -> _PreprocessOutcome:
    """Run the matched preprocess rule for a file, consulting the cache (D6, D7).

    Returns an outcome whose ``status`` is ``none`` (no rule matched - chunk
    normally), ``ok`` (use the produced chunks), ``skipped`` (drop the file),
    or ``passthrough`` (chunk the raw file normally).

    Raises:
        PreprocessAbortError: If the rule fails and ``on_error == "fail"`` -
            propagates out of the worker to abort the run.
    """
    rel_path = str(path.relative_to(root_dir)).replace("\\", "/")
    rule = prep.config.match(rel_path)
    if rule is None or (rule.command is None and rule.entry_point is None):
        return _PreprocessOutcome("none", [], None)

    # Cache token identifies the invocation (command or entry_point) so a
    # version bump via either lever invalidates exactly its own files (D7).
    cache_token = rule.command or rule.entry_point or ""
    cached = read_cached_output(prep.cache_root, content_hash, cache_token)
    if cached is not None:
        return _PreprocessOutcome("ok", _chunks_from_output(cached, rel_path), None)

    if rule.batch:
        # A batch rule reaching the single-file path (a direct caller, or a
        # scoped change of one matched file) runs as a one-file manifest, so it
        # honours the same {paths} contract and cache token as the grouped path.
        result = run_preprocessor_batch(
            [path],
            rule,
            max_emitted_bytes=prep.max_emitted_bytes,
            project_root=prep.project_root,
        )[str(path)]
    else:
        result = run_preprocessor(
            path,
            rule,
            max_emitted_bytes=prep.max_emitted_bytes,
            project_root=prep.project_root,
        )
    if result.status == "ok" and result.output is not None:
        write_cached_output(prep.cache_root, content_hash, cache_token, result.output)
        return _PreprocessOutcome(
            "ok",
            _chunks_from_output(result.output, rel_path),
            None,
        )
    if result.status == "passthrough":
        return _PreprocessOutcome("passthrough", [], result.reason)
    return _PreprocessOutcome("skipped", [], result.reason)


def _get_chunker() -> ASTChunker:
    """Return the per-process reusable :class:`ASTChunker`, building it once."""
    global _CHUNKER
    if _CHUNKER is None:
        _CHUNKER = ASTChunker()  # pyright: ignore[reportConstantRedefinition]  # mutable per-process cache, not a true constant
    return _CHUNKER


def _resolve_html_strip() -> bool:
    """Resolve the ``html_strip`` knob (#185 adjacent ask).

    Read from config rather than threaded: it is an env-or-default boolean with
    no CLI override, so a spawn worker (which inherits the parent's environment)
    resolves the same value the parent would. ``config`` is torch-free, so this
    import does not violate ``index-workers-stay-cpu-only``.
    """
    from ..config import get_config

    return bool(get_config().html_strip)


def _decode_source(raw: bytes, path: pathlib.Path) -> str | None:
    """Decode raw file bytes as UTF-8 with universal-newline translation.

    Replicates :meth:`pathlib.Path.read_text` semantics (``\\r\\n`` and lone
    ``\\r`` collapse to ``\\n``) so chunk text, line numbers, and chunk ids are
    byte-identical to the pre-single-read code path. Returns ``None`` when the
    bytes are not valid UTF-8.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        logger.warning("Cannot decode %s: %s", path, e)
        return None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _chunk_decoded(
    content: str,
    path: pathlib.Path,
    root_dir: pathlib.Path,
    html_strip: bool = True,
) -> list[CodeChunk]:
    """Split already-decoded source into chunks, selecting AST vs splitter.

    For ``.html`` sources, when ``html_strip`` is set the markup is normalised
    to plain text before splitting so chunks carry semantic content rather than
    tag soup (#185 adjacent ask).
    """
    ext = path.suffix.lower()
    lang_entry = LANGUAGE_MAP.get(ext)
    language = lang_entry[0] if lang_entry else "text"
    grammar = lang_entry[1] if lang_entry else None
    rel_path = str(path.relative_to(root_dir)).replace("\\", "/")

    if grammar:
        return chunk_with_ast(content, rel_path, language, grammar)
    if html_strip and language == "html":
        from ._html import html_to_text

        content = html_to_text(content)
    return chunk_with_splitter(content, rel_path, language)


@dataclass(slots=True)
class ScopedChunkResult:
    """A scoped-path file's chunks plus its preprocess disposition.

    The scoped/incremental path hashes separately, so (unlike the full-index
    ``FileChunkResult``) this carries no content hash - only the chunks and the
    preprocess status/reason, so the orchestrator can surface skip counts on the
    incremental and watcher paths too (#185 D11, review VIS-001).
    """

    chunks: list[CodeChunk]
    preprocess_status: str | None = None
    preprocess_reason: str | None = None


def chunk_file_with_status(
    path: pathlib.Path,
    root_dir: pathlib.Path,
    prep: PreprocessContext | None = None,
) -> ScopedChunkResult:
    """Chunk one file (scoped path), carrying back the preprocess disposition.

    This is the picklable process-pool entry point for the incremental and
    scoped paths (which hash separately). It performs only CPU work: a single
    file read, optional preprocessing, tree-sitter parsing (or text-splitter
    fallback), and chunk construction with empty vectors for the consumer to
    embed.

    When ``prep`` is supplied and a preprocess rule matches, the matched
    preprocessor runs first (D6): on success its chunks are returned; on a skip
    the file yields no chunks but the status/reason are reported; on
    passthrough/no-match the raw file is chunked normally.

    Args:
        path: Absolute path to the source file.
        root_dir: Project root used to compute the chunk's relative path.
        prep: Optional preprocess context (rules + cache + cap).

    Returns:
        A :class:`ScopedChunkResult` with the chunks and the preprocess status.
    """
    try:
        raw = path.read_bytes()
    except OSError as e:
        logger.warning("Cannot read %s: %s", path, e)
        return ScopedChunkResult([])
    if prep is not None:
        content_hash = hashlib.blake2b(raw).hexdigest()
        outcome = preprocess_file(content_hash, path, root_dir, prep)
        if outcome.status == "ok":
            return ScopedChunkResult(outcome.chunks, "ok")
        if outcome.status == "skipped":
            return ScopedChunkResult([], "skipped", outcome.reason)
        # "passthrough" / "none" fall through to ordinary chunking below.
    content = _decode_source(raw, path)
    if content is None:
        return ScopedChunkResult([])
    chunks = _chunk_decoded(content, path, root_dir, _resolve_html_strip())
    return ScopedChunkResult(chunks)


def chunk_file(
    path: pathlib.Path,
    root_dir: pathlib.Path,
    prep: PreprocessContext | None = None,
) -> list[CodeChunk]:
    """Chunk one file and return just its chunks (thin wrapper over status form).

    Retained for callers and tests that only need the chunk list; the
    chunk-identity logic lives in :func:`chunk_file_with_status`.
    """
    return chunk_file_with_status(path, root_dir, prep).chunks


def chunk_and_hash_file(
    path: pathlib.Path,
    root_dir: pathlib.Path,
    prep: PreprocessContext | None = None,
) -> FileChunkResult | None:
    """Read a file once, returning both its content hash and its chunks.

    The full-index path uses this so the tree is read a single time rather than
    once for hashing and again for chunking (#155 P03). The blake2b hash is
    computed over the raw bytes, matching ``hashlib.file_digest`` exactly, so
    incremental-index change detection is unaffected. A file that is readable
    but not valid UTF-8 still yields its hash (with no chunks) so it remains
    tracked in the index metadata.

    Args:
        path: Absolute path to the source file.
        root_dir: Project root used to compute the relative path.

    Returns:
        A :class:`FileChunkResult`, or ``None`` when the file cannot be read.
    """
    try:
        raw = path.read_bytes()
    except OSError as e:
        logger.warning("Cannot read %s: %s", path, e)
        return None
    content_hash = hashlib.blake2b(raw).hexdigest()
    rel_path = str(path.relative_to(root_dir)).replace("\\", "/")
    if prep is not None:
        outcome = preprocess_file(content_hash, path, root_dir, prep)
        if outcome.status == "ok":
            return FileChunkResult(
                rel_path,
                content_hash,
                outcome.chunks,
                preprocess_status="ok",
            )
        if outcome.status == "skipped":
            return FileChunkResult(
                rel_path,
                content_hash,
                [],
                preprocess_status="skipped",
                preprocess_reason=outcome.reason,
            )
        # "passthrough" / "none" fall through to ordinary chunking below.
    return _raw_file_result(path, root_dir, rel_path, content_hash, raw)


def _raw_file_result(
    path: pathlib.Path,
    root_dir: pathlib.Path,
    rel_path: str,
    content_hash: str,
    raw: bytes,
) -> FileChunkResult:
    """Chunk already-read raw bytes into a hash-carrying :class:`FileChunkResult`.

    The hash is already computed, so a decode or chunk failure still returns a
    result (with no chunks) rather than raising: that keeps the file present in
    the index metadata, matching the pre-rework behaviour where hashing was an
    independent pass. Dropping it would make every later incremental run
    re-chunk the file.
    """
    content = _decode_source(raw, path)
    if content is None:
        return FileChunkResult(rel_path, content_hash, [])
    try:
        chunks = _chunk_decoded(content, path, root_dir, _resolve_html_strip())
    except Exception:
        logger.warning("Chunking failed for %s; indexing hash only", rel_path)
        return FileChunkResult(rel_path, content_hash, [])
    return FileChunkResult(rel_path, content_hash, chunks)


@dataclass(slots=True)
class _BatchMember:
    """One file's read-time state carried across the batch's phases."""

    path: pathlib.Path
    rel_path: str
    content_hash: str
    cached: PreprocOutput | None


def chunk_batch_files(
    paths: list[pathlib.Path],
    root_dir: pathlib.Path,
    rule: PreprocessRule,
    prep: PreprocessContext,
) -> list[FileChunkResult]:
    """Preprocess a group of files with one batch spawn, then chunk each (#241).

    Reads and hashes every file, consults the D7 cache per file (cache token =
    the batch rule's command), runs the batch hook once over the cache misses,
    writes a cache entry for each success, then turns every file's output into
    a :class:`FileChunkResult` exactly as the per-file path does: ``ok`` yields
    preprocessor chunks, ``skipped`` yields none, and a ``passthrough`` failure
    chunks the raw file normally. Unreadable files are dropped (no result),
    matching :func:`chunk_and_hash_file`.

    Raises:
        PreprocessAbortError: If any file fails and ``on_error == "fail"`` -
            propagates out of the worker to abort the run.
    """
    cache_token = rule.command or ""
    members: list[_BatchMember] = []
    misses: list[pathlib.Path] = []
    for path in paths:
        try:
            raw = path.read_bytes()
        except OSError as e:
            logger.warning("Cannot read %s: %s", path, e)
            continue
        content_hash = hashlib.blake2b(raw).hexdigest()
        rel_path = str(path.relative_to(root_dir)).replace("\\", "/")
        cached = read_cached_output(prep.cache_root, content_hash, cache_token)
        members.append(_BatchMember(path, rel_path, content_hash, cached))
        if cached is None:
            misses.append(path)

    batch_results: dict[str, PreprocessResult] = {}
    if misses:
        batch_results = run_preprocessor_batch(
            misses,
            rule,
            max_emitted_bytes=prep.max_emitted_bytes,
            project_root=prep.project_root,
        )
        for member in members:
            if member.cached is not None:
                continue
            result = batch_results.get(str(member.path))
            if (
                result is not None
                and result.status == "ok"
                and result.output is not None
            ):
                write_cached_output(
                    prep.cache_root,
                    member.content_hash,
                    cache_token,
                    result.output,
                )

    results: list[FileChunkResult] = []
    for member in members:
        results.append(_batch_member_result(member, root_dir, batch_results))
    return results


def _batch_member_result(
    member: _BatchMember,
    root_dir: pathlib.Path,
    batch_results: dict[str, PreprocessResult],
) -> FileChunkResult:
    """Turn one batch member's disposition into a :class:`FileChunkResult`."""
    output = member.cached
    if output is None:
        result = batch_results.get(str(member.path))
        if result is not None and result.status == "passthrough":
            return _passthrough_batch_member(member, root_dir)
        if result is None or result.status != "ok" or result.output is None:
            reason = result.reason if result is not None else None
            return FileChunkResult(
                member.rel_path,
                member.content_hash,
                [],
                preprocess_status="skipped",
                preprocess_reason=reason,
            )
        output = result.output
    return FileChunkResult(
        member.rel_path,
        member.content_hash,
        _chunks_from_output(output, member.rel_path),
        preprocess_status="ok",
    )


def _passthrough_batch_member(
    member: _BatchMember,
    root_dir: pathlib.Path,
) -> FileChunkResult:
    """Chunk a passthrough batch member's raw source, mirroring the per-file path.

    Passthrough re-reads the source rather than retaining every batch file's raw
    bytes in memory; it only fires on a hook failure under ``on_error =
    passthrough``. As on the per-file path, the raw chunks carry no preprocess
    status (the file is indexed as ordinary source).
    """
    try:
        raw = member.path.read_bytes()
    except OSError as e:
        logger.warning("Cannot read %s: %s", member.path, e)
        return FileChunkResult(member.rel_path, member.content_hash, [])
    return _raw_file_result(
        member.path, root_dir, member.rel_path, member.content_hash, raw
    )


def chunk_with_ast(
    content: str,
    rel_path: str,
    language: str,
    grammar: str,
) -> list[CodeChunk]:
    """Chunk source code using tree-sitter AST, falling back to the splitter."""
    chunker = _get_chunker()
    try:
        ast_chunks = chunker.chunk(content, grammar)
    except Exception:
        logger.warning(
            "AST parsing failed for %s, falling back to text splitter",
            rel_path,
            exc_info=True,
        )
        return chunk_with_splitter(content, rel_path, language)

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


def chunk_with_splitter(
    content: str,
    rel_path: str,
    language: str,
) -> list[CodeChunk]:
    """Chunk content using ``TextSplitter`` for non-AST languages."""
    # chunk_overlap=0 is required: non-zero overlap prepends content from the
    # previous chunk, making chunks not findable verbatim in the original source.
    # This breaks line number tracking below.
    splitter = TextSplitter(language=language, chunk_overlap=0)
    text_chunks = splitter.split_text(content)

    chunks: list[CodeChunk] = []
    search_offset = 0
    line_cursor_offset = 0
    line_cursor = 1
    for text in text_chunks:
        idx = content.find(text, search_offset)
        if idx != -1:
            chunk_offset = idx
            search_offset = idx + len(text)
        else:
            raise RuntimeError(
                "zero-overlap TextSplitter returned a chunk absent from "
                f"{rel_path} at or after offset {search_offset}"
            )
        line_cursor += content.count("\n", line_cursor_offset, chunk_offset)
        line_cursor_offset = chunk_offset
        line_start = line_cursor
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
