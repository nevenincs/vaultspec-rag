"""``quality`` command: needle-based precision probes on a synthetic vault."""

from __future__ import annotations

import typer

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
        msg = "Running quality probes on synthetic corpus..."
        with _cli.console.status(msg):
            results = run_quality_probe()
    except (ImportError, RuntimeError) as e:
        _handle_gpu_error(e)
        return

    _cli.console.print("Quality probes: synthetic corpus")
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
