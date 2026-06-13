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

    _cli._suppress_hf_progress()
    try:
        msg = "Running built-in search quality checks..."
        with _cli.console.status(msg):
            results = run_quality_probe()
    except (ImportError, RuntimeError) as e:
        _handle_gpu_error(e)
        return

    _cli.console.print("Quality checks: built-in temporary project")
    for i, probe in enumerate(results["probes"], 1):
        status = "passed" if probe["passed"] else "failed"
        _cli.console.print(
            f"{i}. {status}: {probe['label']} - {probe['query']}",
            markup=False,
            highlight=False,
        )

    _cli.console.print(
        f"Result: {results['passed']} of {results['total']} probes passed "
        f"({results['precision']:.0%}).",
        markup=False,
        highlight=False,
    )

    threshold = results["threshold"]
    if results["precision"] < threshold:
        _cli.console.print(
            f"Failed: {results['precision']:.0%} passed; required {threshold:.0%}.",
            markup=False,
            highlight=False,
        )
        raise typer.Exit(code=1)
    _cli.console.print("Passed.")
