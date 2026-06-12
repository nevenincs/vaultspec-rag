"""``quality`` command: needle-based precision probes on a synthetic vault."""

from __future__ import annotations

import typer

import vaultspec_rag.cli as _cli

from ._app import app
from ._gpu_errors import _handle_gpu_error


@app.command(
    "quality",
    help=(
        "Run built-in search quality checks on a temporary test project. "
        "This is a developer regression check, not a report on your current project."
    ),
)
def handle_quality() -> None:
    """Run built-in search quality checks on a temporary test project."""
    from ..api import run_quality_probe

    try:
        msg = "Running built-in search quality checks..."
        with _cli.console.status(msg):
            results = run_quality_probe()
    except (ImportError, RuntimeError) as e:
        _handle_gpu_error(e)
        return

    _cli.console.print("Quality checks: built-in temporary project")
    for i, probe in enumerate(results["probes"], 1):
        status = "PASS" if probe["passed"] else "FAIL"
        _cli.console.print(
            f"{i}. {status} label={probe['label']} query={probe['query']}",
            markup=False,
            highlight=False,
        )

    _cli.console.print(
        f"Result: {results['passed']}/{results['total']} probes passed "
        f"({results['precision']:.0%} precision)",
        markup=False,
        highlight=False,
    )

    threshold = results["threshold"]
    if results["precision"] < threshold:
        _cli.console.print(
            f"FAILED: precision {results['precision']:.0%} "
            f"below {threshold:.0%} threshold.",
            markup=False,
            highlight=False,
        )
        raise typer.Exit(code=1)
    _cli.console.print("PASSED")
