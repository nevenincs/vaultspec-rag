"""``benchmark`` command: search-latency percentiles over the vault."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ..embeddings import EmbeddingModel
from ..search import VaultSearcher
from ._app import CLIState, app
from ._core import logger
from ._gpu_errors import _handle_gpu_error
from ._store import _open_vault_store


@app.command("benchmark")
def handle_benchmark(
    ctx: typer.Context,
    n_queries: Annotated[
        int,
        typer.Option("--n-queries", help="Number of search queries to time."),
    ] = 20,
) -> None:
    """Run search latency benchmarks against the indexed vault.

    Requires an indexed vault (run ``vaultspec-rag index``
    first). Reports p50/p95/p99 latency, store counts, and
    GPU VRAM usage.

    Args:
        ctx: Typer context carrying ``CLIState``.
        n_queries: Number of search queries to time.

    Raises:
        typer.Exit: When vault is empty (code 1) or on GPU
            errors.

    """
    import statistics
    import time

    state: CLIState = ctx.obj
    target = state.target

    store = _open_vault_store(target)
    try:
        vault_count = store.count()
        if vault_count == 0:
            _cli.console.print(
                "[yellow]Warning:[/] No vault documents indexed. "
                "Run [cyan]vaultspec-rag index[/] first.",
            )
            raise typer.Exit(code=1)

        try:
            model = EmbeddingModel()
        except (ImportError, RuntimeError) as e:
            _handle_gpu_error(e)

        searcher = VaultSearcher(target, model, store)

        _bench_queries = [
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
            "semantic search embedding",
            "Qdrant vector store",
            "date:2026-01 decisions",
            "checkpoint storage performance",
            "connector grpc streaming",
            "execution graph dependency",
            "incremental indexing hash",
        ]

        with _cli.console.status("[bold green]Warming up..."):
            searcher.search_vault("warmup", top_k=1)

        latencies: list[float] = []
        with _cli.console.status(
            f"[bold green]Running {n_queries} benchmark queries...",
        ):
            for i in range(n_queries):
                q = _bench_queries[i % len(_bench_queries)]
                t0 = time.perf_counter()
                searcher.search_vault(q, top_k=5)
                latencies.append((time.perf_counter() - t0) * 1000)

        latencies.sort()
        p50 = latencies[n_queries // 2]
        p95 = latencies[int(n_queries * 0.95)]
        p99 = latencies[int(n_queries * 0.99)]
        mean = statistics.mean(latencies)
        stdev = statistics.stdev(latencies) if len(latencies) > 1 else 0.0

        try:
            import torch

            gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A"
            vram_mb = (
                torch.cuda.memory_allocated(0) / (1024 * 1024)
                if torch.cuda.is_available()
                else 0.0
            )
        except ImportError as exc:
            logger.debug("torch unavailable for GPU report: %s", exc)
            gpu = "N/A"
            vram_mb = 0.0

        table = Table(
            title=f"Search Latency - {n_queries} queries",
            show_header=True,
        )
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right", style="cyan")
        table.add_row("p50", f"{p50:.1f} ms")
        table.add_row("p95", f"{p95:.1f} ms")
        table.add_row("p99", f"{p99:.1f} ms")
        table.add_row("mean", f"{mean:.1f} ms")
        table.add_row("stdev", f"{stdev:.1f} ms")
        table.add_row("vault docs", str(vault_count))
        table.add_row("code chunks", str(store.count_code()))
        table.add_row("GPU", gpu)
        table.add_row("VRAM allocated", f"{vram_mb:.1f} MB")
        _cli.console.print(table)
    finally:
        store.close()
