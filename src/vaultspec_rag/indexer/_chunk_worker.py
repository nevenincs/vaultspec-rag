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

from .._store_models import (
    CodeChunk,
    DocumentChunk,
    DocumentLocator,
    DocumentMetadata,
    DocumentPayload,
)
from ..job_control import NO_RUN_CONTROL
from ._ast_chunker import ASTChunker
from ._chunking import LANGUAGE_MAP, TextSplitter
from ._content_policy import ContentKind
from ._document_identity import document_point_id
from ._preprocess_cache import (
    PreprocessCacheIdentity,
    read_cached_output,
    write_cached_output,
)
from ._preprocess_runner import run_preprocessor, run_preprocessor_batch

if TYPE_CHECKING:
    import pathlib

    from ..job_control import RunControl
    from ._preprocess_config import PreprocessContext, PreprocessRule
    from ._preprocess_runner import PreprocessResult
    from ._preprocess_schema import PreprocOutput

logger = logging.getLogger(__name__)
_SOURCE_READ_BLOCK_BYTES = 1024 * 1024

# Per-worker reusable chunker. ``ASTChunker`` itself is cheap to build, but the
# tree-sitter parsers it drives are cached inside ``tree_sitter_language_pack``
# across calls, so a single instance per process avoids repeated lookups over
# tens of thousands of files (research O3).
_CHUNKER: ASTChunker | None = None


class _SourceLimitExceededError(ValueError):
    """One source crossed its effective pre-extraction byte ceiling."""


def _effective_source_limit(
    prep: PreprocessContext | None,
    rule: PreprocessRule | None,
) -> int | None:
    """Return the strictest positive context and rule source ceiling."""
    candidates = (
        getattr(prep, "max_source_bytes", None),
        getattr(rule, "max_source_bytes", None),
    )
    limits = [
        value
        for value in candidates
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
    return min(limits) if limits else None


def _stream_source(
    path: pathlib.Path,
    *,
    max_source_bytes: int | None,
    retain_bytes: bool,
) -> tuple[str, bytes | None]:
    """Hash one source incrementally and optionally retain bounded raw bytes."""
    digest = hashlib.blake2b()
    retained = bytearray() if retain_bytes else None
    total = 0
    try:
        with path.open("rb") as stream:
            while block := stream.read(_SOURCE_READ_BLOCK_BYTES):
                total += len(block)
                if max_source_bytes is not None and total > max_source_bytes:
                    raise _SourceLimitExceededError(
                        f"source exceeds max_source_bytes={max_source_bytes}"
                    )
                digest.update(block)
                if retained is not None:
                    retained.extend(block)
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        raise
    return digest.hexdigest(), bytes(retained) if retained is not None else None


def _limit_disposition(rule: PreprocessRule, error: _SourceLimitExceededError) -> str:
    """Map a pre-launch source refusal through the rule's declared policy."""
    if rule.on_error == "fail":
        from ._preprocess_runner import PreprocessAbortError

        raise PreprocessAbortError(str(error)) from error
    return "skipped"


@dataclass(slots=True)
class FileChunkResult:
    """One file's chunks plus its content hash, returned from a worker.

    Carrying the blake2b hash back from the same read that produced the chunks
    lets the shared code producer skip a separate hash pass - the tree is read
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
class DocumentFileChunkResult:
    """One document source's independently typed chunks and source hash."""

    rel_path: str
    content_hash: str
    chunks: list[DocumentChunk]
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


def _cached_output_within_cap(output: PreprocOutput, cap: int) -> bool:
    """Revalidate cached emitted text against the current operation ceiling."""
    texts = (
        (unit.text for unit in output.units)
        if output.units is not None
        else (output.text or "",)
    )
    return sum(len(text.encode("utf-8")) for text in texts) <= cap


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

    cache_identity = PreprocessCacheIdentity.from_rule(
        source_path=rel_path,
        source_hash=content_hash,
        rule=rule,
        mode="batch" if rule.batch else "single",
        max_emitted_bytes=prep.max_emitted_bytes,
    )
    cached = read_cached_output(prep.cache_root, cache_identity)
    if cached is not None and not _cached_output_within_cap(
        cached,
        prep.max_emitted_bytes,
    ):
        cached = None
    if cached is not None:
        if rule.path_independent:
            cached = cached.model_copy(update={"source_path": rel_path})
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
        write_cached_output(prep.cache_root, cache_identity, result.output)
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


@dataclass(frozen=True, slots=True)
class ChunkExecutionPolicy:
    """Picklable byte-decoding and raw-chunk semantics for one operation."""

    encoding: str = "utf-8"
    errors: str = "strict"
    normalize_newlines: bool = True
    html_strip: bool = True


_DEFAULT_EXECUTION_POLICY = ChunkExecutionPolicy()


def _decode_source(
    raw: bytes,
    path: pathlib.Path,
    execution_policy: ChunkExecutionPolicy,
) -> str | None:
    """Decode raw bytes using the operation's immutable decoder semantics.

    Replicates :meth:`pathlib.Path.read_text` semantics (``\\r\\n`` and lone
    ``\\r`` collapse to ``\\n``) so chunk text, line numbers, and chunk ids are
    byte-identical to the pre-single-read code path. Returns ``None`` when the
    bytes are not valid UTF-8.
    """
    try:
        text = raw.decode(execution_policy.encoding, execution_policy.errors)
    except UnicodeDecodeError as e:
        logger.warning("Cannot decode %s: %s", path, e)
        return None
    if execution_policy.normalize_newlines:
        return text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _document_chunks_from_text(
    text: str,
    *,
    rel_path: str,
    content_hash: str,
    document_metadata: DocumentMetadata | None = None,
    extractor_id: str | None = None,
    extractor_version: str | None = None,
) -> list[DocumentChunk]:
    """Split decoded text into document-native chunks with stable identities."""
    splitter = TextSplitter(language="text", chunk_overlap=0)
    chunks: list[DocumentChunk] = []
    for ordinal, content in enumerate(splitter.split_text(text)):
        if not content.strip():
            continue
        payload = DocumentPayload(
            source_path=rel_path,
            unit_ordinal=ordinal,
            content_fingerprint=content_hash,
            content=content,
            document_metadata=document_metadata or DocumentMetadata(),
            extractor_id=extractor_id,
            extractor_version=extractor_version,
        )
        chunks.append(
            DocumentChunk(
                document_point_id(
                    source_path=rel_path,
                    unit_ordinal=ordinal,
                    content_fingerprint=content_hash,
                ),
                payload,
            )
        )
    return chunks


def _document_chunks_from_output(
    output: PreprocOutput,
    *,
    rel_path: str,
    content_hash: str,
) -> list[DocumentChunk]:
    """Preserve every validated document and unit field on native chunks."""
    document_metadata = DocumentMetadata.from_mapping(dict(output.metadata))
    if output.units is None:
        return _document_chunks_from_text(
            output.text or "",
            rel_path=rel_path,
            content_hash=content_hash,
            document_metadata=document_metadata,
            extractor_id=output.preprocessor_id,
            extractor_version=output.preprocessor_version,
        )

    chunks: list[DocumentChunk] = []
    for ordinal, unit in enumerate(output.units):
        locator = (
            DocumentLocator(unit.locator.kind, unit.locator.value, unit.locator.end)
            if unit.locator is not None
            else None
        )
        payload = DocumentPayload(
            source_path=rel_path,
            unit_ordinal=ordinal,
            content_fingerprint=content_hash,
            content=unit.text,
            title=unit.title,
            section=unit.section,
            anchor=unit.anchor,
            locator=locator,
            document_metadata=document_metadata,
            unit_metadata=DocumentMetadata.from_mapping(dict(unit.metadata)),
            extractor_id=output.preprocessor_id,
            extractor_version=output.preprocessor_version,
        )
        chunks.append(
            DocumentChunk(
                document_point_id(
                    source_path=rel_path,
                    unit_ordinal=ordinal,
                    content_fingerprint=content_hash,
                    locator=locator,
                ),
                payload,
            )
        )
    return chunks


def _document_preprocess_output(
    *,
    content_hash: str,
    path: pathlib.Path,
    root_dir: pathlib.Path,
    prep: PreprocessContext,
    run_control: RunControl,
) -> tuple[str, PreprocOutput | None, str | None]:
    """Run one document extractor while retaining cache and error disposition."""
    rel_path = path.relative_to(root_dir).as_posix()
    rule = prep.config.match(rel_path)
    if rule is None or (rule.command is None and rule.entry_point is None):
        return "none", None, None
    identity = PreprocessCacheIdentity.from_rule(
        source_path=rel_path,
        source_hash=content_hash,
        rule=rule,
        mode="batch" if rule.batch else "single",
        max_emitted_bytes=prep.max_emitted_bytes,
    )
    output = read_cached_output(prep.cache_root, identity)
    if output is not None and not _cached_output_within_cap(
        output,
        prep.max_emitted_bytes,
    ):
        output = None
    if output is not None:
        if rule.path_independent:
            output = output.model_copy(update={"source_path": rel_path})
        return "ok", output, None
    if rule.batch:
        result = run_preprocessor_batch(
            [path],
            rule,
            max_emitted_bytes=prep.max_emitted_bytes,
            project_root=prep.project_root,
            checkpoint=run_control.checkpoint,
        )[str(path)]
    else:
        result = run_preprocessor(
            path,
            rule,
            max_emitted_bytes=prep.max_emitted_bytes,
            project_root=prep.project_root,
            checkpoint=run_control.checkpoint,
        )
    if result.status == "ok" and result.output is not None:
        write_cached_output(prep.cache_root, identity, result.output)
        return "ok", result.output, None
    return result.status, None, result.reason


def chunk_document_and_hash_file(
    path: pathlib.Path,
    root_dir: pathlib.Path,
    prep: PreprocessContext | None = None,
    execution_policy: ChunkExecutionPolicy = _DEFAULT_EXECUTION_POLICY,
    run_control: RunControl = NO_RUN_CONTROL,
) -> DocumentFileChunkResult:
    """Read and chunk one explicitly admitted document without code models."""
    rel_path = path.relative_to(root_dir).as_posix()
    run_control.checkpoint()
    rule = prep.config.match(rel_path) if prep is not None else None
    if rule is not None and rule.target is not ContentKind.DOCUMENT:
        raise ValueError("document worker received a non-document extraction rule")
    source_limit = _effective_source_limit(prep, rule)
    if rule is not None:
        try:
            content_hash, _raw = _stream_source(
                path,
                max_source_bytes=source_limit,
                retain_bytes=False,
            )
        except _SourceLimitExceededError as exc:
            return DocumentFileChunkResult(
                rel_path,
                "unpublished",
                [],
                preprocess_status=_limit_disposition(rule, exc),
                preprocess_reason=str(exc),
            )
    else:
        content_hash, raw = _stream_source(
            path,
            max_source_bytes=source_limit,
            retain_bytes=True,
        )
        assert raw is not None
    if prep is not None and rule is not None:
        status, output, reason = _document_preprocess_output(
            content_hash=content_hash,
            path=path,
            root_dir=root_dir,
            prep=prep,
            run_control=run_control,
        )
        if status == "ok" and output is not None:
            return DocumentFileChunkResult(
                rel_path,
                content_hash,
                _document_chunks_from_output(
                    output,
                    rel_path=rel_path,
                    content_hash=content_hash,
                ),
                preprocess_status="ok",
            )
        if status == "skipped":
            return DocumentFileChunkResult(
                rel_path,
                content_hash,
                [],
                preprocess_status="skipped",
                preprocess_reason=reason,
            )
        # No extractor or an explicit passthrough continues in document kind.
        try:
            _passthrough_hash, raw = _stream_source(
                path,
                max_source_bytes=source_limit,
                retain_bytes=True,
            )
        except _SourceLimitExceededError as exc:
            return DocumentFileChunkResult(
                rel_path,
                content_hash,
                [],
                preprocess_status="skipped",
                preprocess_reason=str(exc),
            )
        assert raw is not None
    text = _decode_source(raw, path, execution_policy)
    if text is None:
        return DocumentFileChunkResult(rel_path, content_hash, [])
    return DocumentFileChunkResult(
        rel_path,
        content_hash,
        _document_chunks_from_text(
            text,
            rel_path=rel_path,
            content_hash=content_hash,
        ),
    )


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

    The scoped path hashes separately, so (unlike the shared weighted
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
    execution_policy: ChunkExecutionPolicy = _DEFAULT_EXECUTION_POLICY,
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
    rel_path = path.relative_to(root_dir).as_posix()
    rule = prep.config.match(rel_path) if prep is not None else None
    if rule is not None and rule.target is not ContentKind.CODE:
        raise ValueError("code worker received a non-code extraction rule")
    source_limit = _effective_source_limit(prep, rule)
    if rule is not None:
        try:
            content_hash, _raw = _stream_source(
                path,
                max_source_bytes=source_limit,
                retain_bytes=False,
            )
        except _SourceLimitExceededError as exc:
            return ScopedChunkResult([], _limit_disposition(rule, exc), str(exc))
    else:
        content_hash, raw = _stream_source(
            path,
            max_source_bytes=source_limit,
            retain_bytes=True,
        )
        assert raw is not None
    if prep is not None and rule is not None:
        outcome = preprocess_file(content_hash, path, root_dir, prep)
        if outcome.status == "ok":
            return ScopedChunkResult(outcome.chunks, "ok")
        if outcome.status == "skipped":
            return ScopedChunkResult([], "skipped", outcome.reason)
        # "passthrough" / "none" fall through to ordinary chunking below.
        try:
            _passthrough_hash, raw = _stream_source(
                path,
                max_source_bytes=source_limit,
                retain_bytes=True,
            )
        except _SourceLimitExceededError as exc:
            return ScopedChunkResult([], "skipped", str(exc))
        assert raw is not None
    content = _decode_source(raw, path, execution_policy)
    if content is None:
        return ScopedChunkResult([])
    chunks = _chunk_decoded(content, path, root_dir, execution_policy.html_strip)
    return ScopedChunkResult(chunks)


def chunk_file(
    path: pathlib.Path,
    root_dir: pathlib.Path,
    prep: PreprocessContext | None = None,
    execution_policy: ChunkExecutionPolicy = _DEFAULT_EXECUTION_POLICY,
) -> list[CodeChunk]:
    """Chunk one file and return just its chunks (thin wrapper over status form).

    Retained for callers and tests that only need the chunk list; the
    chunk-identity logic lives in :func:`chunk_file_with_status`.
    """
    return chunk_file_with_status(path, root_dir, prep, execution_policy).chunks


def chunk_and_hash_file(
    path: pathlib.Path,
    root_dir: pathlib.Path,
    prep: PreprocessContext | None = None,
    execution_policy: ChunkExecutionPolicy = _DEFAULT_EXECUTION_POLICY,
) -> FileChunkResult:
    """Read a file once, returning both its content hash and its chunks.

    Code indexing uses this so a production pass reads each selected file once
    rather than once for hashing and again for chunking (#155 P03). The blake2b
    hash is computed over the raw bytes, matching ``hashlib.file_digest`` exactly.
    A file that is readable but not valid UTF-8 still yields its hash (with no
    chunks) so it remains tracked in metadata.

    Args:
        path: Absolute path to the source file.
        root_dir: Project root used to compute the relative path.

    Returns:
        A :class:`FileChunkResult` for every successfully read file.

    Raises:
        OSError: If the source file cannot be read.
    """
    rel_path = str(path.relative_to(root_dir)).replace("\\", "/")
    rule = prep.config.match(rel_path) if prep is not None else None
    if rule is not None and rule.target is not ContentKind.CODE:
        raise ValueError("code worker received a non-code extraction rule")
    source_limit = _effective_source_limit(prep, rule)
    if rule is not None:
        try:
            content_hash, _raw = _stream_source(
                path,
                max_source_bytes=source_limit,
                retain_bytes=False,
            )
        except _SourceLimitExceededError as exc:
            return FileChunkResult(
                rel_path,
                "unpublished",
                [],
                preprocess_status=_limit_disposition(rule, exc),
                preprocess_reason=str(exc),
            )
    else:
        content_hash, raw = _stream_source(
            path,
            max_source_bytes=source_limit,
            retain_bytes=True,
        )
        assert raw is not None
    if prep is not None and rule is not None:
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
        try:
            _passthrough_hash, raw = _stream_source(
                path,
                max_source_bytes=source_limit,
                retain_bytes=True,
            )
        except _SourceLimitExceededError as exc:
            return FileChunkResult(
                rel_path,
                content_hash,
                [],
                preprocess_status="skipped",
                preprocess_reason=str(exc),
            )
        assert raw is not None
    return _raw_file_result(
        path,
        root_dir,
        rel_path,
        content_hash,
        raw,
        execution_policy,
    )


def _raw_file_result(
    path: pathlib.Path,
    root_dir: pathlib.Path,
    rel_path: str,
    content_hash: str,
    raw: bytes,
    execution_policy: ChunkExecutionPolicy,
) -> FileChunkResult:
    """Chunk already-read raw bytes into a hash-carrying :class:`FileChunkResult`.

    An unsupported source encoding remains a valid zero-chunk result. Ordinary
    chunking failures propagate so callers cannot publish a hash for vectors
    that were never produced.
    """
    content = _decode_source(raw, path, execution_policy)
    if content is None:
        return FileChunkResult(rel_path, content_hash, [])
    chunks = _chunk_decoded(content, path, root_dir, execution_policy.html_strip)
    return FileChunkResult(rel_path, content_hash, chunks)


@dataclass(slots=True)
class _BatchMember:
    """One file's read-time state carried across the batch's phases."""

    path: pathlib.Path
    rel_path: str
    content_hash: str
    cached: PreprocOutput | None
    source_limit: int | None = None
    limit_reason: str | None = None


def _prepare_batch_member(
    path: pathlib.Path,
    root_dir: pathlib.Path,
    rule: PreprocessRule,
    prep: PreprocessContext,
    source_limit: int | None,
) -> tuple[_BatchMember, bool]:
    """Hash, bound, and consult cache for one batch member."""
    rel_path = str(path.relative_to(root_dir)).replace("\\", "/")
    try:
        content_hash, _raw = _stream_source(
            path,
            max_source_bytes=source_limit,
            retain_bytes=False,
        )
    except _SourceLimitExceededError as exc:
        _limit_disposition(rule, exc)
        return (
            _BatchMember(
                path,
                rel_path,
                "unpublished",
                None,
                source_limit,
                str(exc),
            ),
            False,
        )
    identity = PreprocessCacheIdentity.from_rule(
        source_path=rel_path,
        source_hash=content_hash,
        rule=rule,
        mode="batch",
        max_emitted_bytes=prep.max_emitted_bytes,
    )
    cached = read_cached_output(prep.cache_root, identity)
    if cached is not None and not _cached_output_within_cap(
        cached, prep.max_emitted_bytes
    ):
        cached = None
    if cached is not None and rule.path_independent:
        cached = cached.model_copy(update={"source_path": rel_path})
    return (
        _BatchMember(path, rel_path, content_hash, cached, source_limit),
        cached is None,
    )


def _cache_batch_successes(
    members: list[_BatchMember],
    batch_results: dict[str, PreprocessResult],
    rule: PreprocessRule,
    prep: PreprocessContext,
) -> None:
    """Persist successful cache misses after one bounded batch invocation."""
    for member in members:
        if member.cached is not None or member.limit_reason is not None:
            continue
        result = batch_results.get(str(member.path))
        if result is None or result.status != "ok" or result.output is None:
            continue
        write_cached_output(
            prep.cache_root,
            PreprocessCacheIdentity.from_rule(
                source_path=member.rel_path,
                source_hash=member.content_hash,
                rule=rule,
                mode="batch",
                max_emitted_bytes=prep.max_emitted_bytes,
            ),
            result.output,
        )


def chunk_batch_files(
    paths: list[pathlib.Path],
    root_dir: pathlib.Path,
    rule: PreprocessRule,
    prep: PreprocessContext,
    execution_policy: ChunkExecutionPolicy = _DEFAULT_EXECUTION_POLICY,
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
    if rule.target is not ContentKind.CODE:
        raise ValueError("code batch worker received a non-code extraction rule")
    members: list[_BatchMember] = []
    misses: list[pathlib.Path] = []
    source_limit = _effective_source_limit(prep, rule)
    for path in paths:
        member, needs_run = _prepare_batch_member(
            path, root_dir, rule, prep, source_limit
        )
        members.append(member)
        if needs_run:
            misses.append(path)

    batch_results: dict[str, PreprocessResult] = {}
    if misses:
        batch_results = run_preprocessor_batch(
            misses,
            rule,
            max_emitted_bytes=prep.max_emitted_bytes,
            project_root=prep.project_root,
        )
        _cache_batch_successes(members, batch_results, rule, prep)

    results: list[FileChunkResult] = []
    for member in members:
        results.append(
            _batch_member_result(
                member,
                root_dir,
                batch_results,
                execution_policy,
            )
        )
    return results


def _batch_member_result(
    member: _BatchMember,
    root_dir: pathlib.Path,
    batch_results: dict[str, PreprocessResult],
    execution_policy: ChunkExecutionPolicy,
) -> FileChunkResult:
    """Turn one batch member's disposition into a :class:`FileChunkResult`."""
    if member.limit_reason is not None:
        return FileChunkResult(
            member.rel_path,
            member.content_hash,
            [],
            preprocess_status="skipped",
            preprocess_reason=member.limit_reason,
        )
    output = member.cached
    if output is None:
        result = batch_results.get(str(member.path))
        if result is not None and result.status == "passthrough":
            return _passthrough_batch_member(member, root_dir, execution_policy)
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
    execution_policy: ChunkExecutionPolicy = _DEFAULT_EXECUTION_POLICY,
) -> FileChunkResult:
    """Chunk a passthrough batch member's raw source, mirroring the per-file path.

    Passthrough re-reads the source rather than retaining every batch file's raw
    bytes in memory; it only fires on a hook failure under ``on_error =
    passthrough``. As on the per-file path, the raw chunks carry no preprocess
    status (the file is indexed as ordinary source).
    """
    try:
        content_hash, raw = _stream_source(
            member.path,
            max_source_bytes=member.source_limit,
            retain_bytes=True,
        )
    except _SourceLimitExceededError as exc:
        return FileChunkResult(
            member.rel_path,
            member.content_hash,
            [],
            preprocess_status="skipped",
            preprocess_reason=str(exc),
        )
    assert raw is not None
    return _raw_file_result(
        member.path,
        root_dir,
        member.rel_path,
        content_hash,
        raw,
        execution_policy,
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
