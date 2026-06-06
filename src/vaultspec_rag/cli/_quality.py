"""``quality`` command: needle-based precision probes on a synthetic vault."""

from __future__ import annotations

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ._app import app
from ._gpu_errors import _handle_gpu_error


@app.command("quality")
def handle_quality() -> None:
    """Run quality-scoring probes against a synthetic test corpus.

    Generates a temporary synthetic vault, indexes it, runs
    needle-based precision probes, and reports results. Exits 1
    if fewer than 75% of probes pass.

    This is a developer regression tool -- not tied to a specific
    user vault.

    Raises:
        typer.Exit: On GPU errors or when precision drops below 75%.
    """
    from ..api import run_quality_probe

    try:
        msg = "[bold green]Running quality probes on synthetic corpus..."
        with _cli.console.status(msg):
            results = run_quality_probe()
    except (ImportError, RuntimeError) as e:
        _handle_gpu_error(e)

    table = Table(
        title="Quality Probes - Synthetic Corpus",
        show_header=True,
    )
    table.add_column("#", style="bold", justify="right")
    table.add_column("Label")
    table.add_column("Query", style="italic")
    table.add_column("Result", justify="center")

    for i, probe in enumerate(results["probes"], 1):
        status = "[green]PASS[/]" if probe["passed"] else "[red]FAIL[/]"
        table.add_row(str(i), probe["label"], probe["query"], status)

    _cli.console.print(table)
    _cli.console.print(
        f"\nPassed [bold]{results['passed']}/{results['total']}[/] probes "
        f"([cyan]{results['precision']:.0%}[/] precision)",
    )

    threshold = results["threshold"]
    if results["precision"] < threshold:
        _cli.console.print(
            f"[bold red]FAILED[/] - precision {results['precision']:.0%} "
            f"below {threshold:.0%} threshold.",
        )
        raise typer.Exit(code=1)
    _cli.console.print("[bold green]PASSED[/]")
