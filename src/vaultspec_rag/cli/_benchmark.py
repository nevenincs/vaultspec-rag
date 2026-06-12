"""``benchmark`` command: search-latency percentiles over the vault."""

from __future__ import annotations

from typing import Annotated

import typer

import vaultspec_rag.cli as _cli

from ._app import CLIState, app
from ._gpu_errors import _handle_gpu_error


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
    state: CLIState = ctx.obj
    target = state.target

    from ..api import run_benchmark

    try:
        results = run_benchmark(target, n_queries=n_queries)
    except ValueError as e:
        if "No vault documents" in str(e):
            _cli.console.print(
                "[yellow]Warning:[/] No vault documents indexed. "
                "Run [cyan]vaultspec-rag index[/] first.",
            )
            raise typer.Exit(code=1) from e
        raise
    except (ImportError, RuntimeError) as e:
        _handle_gpu_error(e)
        return

    _cli.console.print(f"Search latency: {n_queries} queries")
    _cli.console.print(
        "Latency: "
        f"p50={results['p50']:.1f}ms "
        f"p95={results['p95']:.1f}ms "
        f"p99={results['p99']:.1f}ms "
        f"mean={results['mean']:.1f}ms "
        f"stdev={results['stdev']:.1f}ms",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"Index: vault_docs={results['vault_count']} "
        f"code_chunks={results['code_count']}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"GPU: {results['gpu']} vram_allocated={results['vram_mb']:.1f} MB",
        markup=False,
        highlight=False,
    )
