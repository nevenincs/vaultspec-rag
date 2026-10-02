"""Deterministic real Python sources and canonical AST chunk workloads."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from vaultspec_rag.indexer._ast_chunker import ASTChunker

from ._profile_tools import digest

if TYPE_CHECKING:
    from pathlib import Path

    from vaultspec_rag.indexer._ast_chunker import ChunkRecord

SOURCE_FILES = (
    "src/vaultspec_rag/embeddings.py",
    "src/vaultspec_rag/_sparse_encoder.py",
    "src/vaultspec_rag/indexer/_ast_chunker.py",
    "src/vaultspec_rag/indexer/_chunk_worker.py",
    "src/vaultspec_rag/indexer/_streaming.py",
    "src/vaultspec_rag/jobs.py",
    "src/vaultspec_rag/config/_registry.py",
    "src/vaultspec_rag/tests/test_encode_bucket_planner.py",
)


def load_sources(root: Path) -> list[tuple[str, str]]:
    return [(name, (root / name).read_text(encoding="utf-8")) for name in SOURCE_FILES]


def chunk_sources(
    sources: list[tuple[str, str]], chunk_size: int
) -> list[tuple[str, ChunkRecord]]:
    chunker = ASTChunker(chunk_size=chunk_size)
    return [
        (name, chunk)
        for name, source in sources
        for chunk in chunker.chunk(source, "python")
    ]


def corpus(chunks: list[tuple[str, ChunkRecord]], items: int) -> dict[str, list[str]]:
    texts = [chunk[0] for _, chunk in chunks if chunk[0].strip()]
    if len(texts) < items:
        raise ValueError("Corpus does not contain enough real chunks")
    ordered = sorted(texts, key=lambda text: (len(text), text))
    short = ordered[:items]
    long = ordered[-items:]
    mixed = [
        ordered[index // 2] if index % 2 == 0 else ordered[-1 - index // 2]
        for index in range(items)
    ]
    dense = sorted(
        texts,
        key=lambda text: (
            -sum(not char.isalnum() and not char.isspace() for char in text)
            / max(1, len(text)),
            text,
        ),
    )[:items]
    return {"short": short, "long": long, "mixed": mixed, "token_dense": dense}


def corpus_manifest(
    root: Path, workloads: dict[str, list[str]], sources: list[tuple[str, str]]
) -> dict[str, object]:
    return {
        "files": {name: digest(root / name) for name in SOURCE_FILES},
        "loaded_source_sha256": {
            name: hashlib.sha256(source.encode("utf-8")).hexdigest()
            for name, source in sources
        },
        "workloads": {
            name: {
                "sha256": hashlib.sha256("\0".join(texts).encode("utf-8")).hexdigest(),
                "items": len(texts),
                "chars": [len(t) for t in texts],
            }
            for name, texts in workloads.items()
        },
    }
