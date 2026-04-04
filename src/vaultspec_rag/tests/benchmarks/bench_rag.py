"""RAG stack benchmarks: embedding, indexing, search, and resource usage.

Run via CLI:
    vaultspec-rag benchmark          # rich latency/resource report
    vaultspec-rag test -m performance  # full pytest suite
"""

from __future__ import annotations

import statistics
import time

import pytest


@pytest.mark.performance
def test_bench_embedding_throughput(model, n_docs: int = 50) -> dict:
    """Time embedding N synthetic documents."""
    texts = [
        f"Document {i}: Architecture decision about component {i} "
        f"with detailed analysis of trade-offs and implementation strategy."
        for i in range(n_docs)
    ]

    start = time.perf_counter()
    model.encode_documents(texts)
    elapsed = time.perf_counter() - start

    return {
        "n_docs": n_docs,
        "elapsed_s": elapsed,
        "docs_per_sec": n_docs / elapsed,
    }


@pytest.mark.performance
def test_bench_full_index(root, model, store, indexer) -> dict:
    """Time full_index() on the entire vault corpus."""
    start = time.perf_counter()
    result = indexer.full_index()
    elapsed = time.perf_counter() - start

    return {
        "total_docs": result.total,
        "elapsed_s": elapsed,
        "docs_per_sec": result.total / elapsed if elapsed > 0 else 0,
        "device": result.device,
    }


@pytest.mark.performance
def test_bench_incremental_noop(indexer) -> dict:
    """Time incremental_index() when nothing has changed."""
    start = time.perf_counter()
    result = indexer.incremental_index()
    elapsed = time.perf_counter() - start

    return {
        "elapsed_s": elapsed,
        "added": result.added,
        "removed": result.removed,
    }


@pytest.mark.performance
def test_bench_search_latency(searcher, n_queries: int = 20) -> dict:
    """Measure search latency distribution over N queries."""
    queries = [
        "architecture decision",
        "pipeline execution model",
        "connector protocol design",
        "security audit vulnerability",
        "implementation plan phase",
        "type:adr architecture",
        "feature:pipeline-engine execution",
        "scheduler algorithm selection",
        "pipeline executor implementation",
        "dag execution research",
        "data transformation pipeline",
        "worker pool thread",
        "type:plan implementation",
        "tree-sitter parser",
        "vault graph re-ranking",
        "semantic search embedding",
        "Qdrant vector store",
        "date:2026-01 decisions",
        "checkpoint storage performance",
        "connector grpc streaming",
    ]

    # Warmup
    searcher.search("warmup", top_k=1)

    latencies = []
    for i in range(n_queries):
        q = queries[i % len(queries)]
        start = time.perf_counter()
        searcher.search(q, top_k=5)
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies.append(elapsed_ms)

    latencies.sort()
    return {
        "n_queries": n_queries,
        "p50_ms": latencies[n_queries // 2],
        "p95_ms": latencies[int(n_queries * 0.95)],
        "p99_ms": latencies[int(n_queries * 0.99)],
        "mean_ms": statistics.mean(latencies),
        "stdev_ms": statistics.stdev(latencies) if len(latencies) > 1 else 0,
    }


@pytest.mark.performance
def test_bench_memory(root) -> dict:
    """Measure GPU VRAM and Qdrant disk size. Requires CUDA GPU."""
    import torch

    result = {}
    result["gpu_name"] = torch.cuda.get_device_name(0)
    result["vram_allocated_mb"] = torch.cuda.memory_allocated(0) / (1024 * 1024)
    result["vram_reserved_mb"] = torch.cuda.memory_reserved(0) / (1024 * 1024)

    # Qdrant disk size
    from vaultspec_rag.config import get_config

    cfg = get_config()
    qdrant_dir = root / cfg.data_dir / cfg.qdrant_dir
    if qdrant_dir.exists():
        total_bytes = sum(
            f.stat().st_size for f in qdrant_dir.rglob("*") if f.is_file()
        )
        result["qdrant_disk_mb"] = total_bytes / (1024 * 1024)
    else:
        result["qdrant_disk_mb"] = 0

    return result
