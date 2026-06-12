"""``test`` command: forward extra args to pytest over the test tree."""

import subprocess
import sys
from pathlib import Path

import typer

from ._app import app


@app.command(
    "test",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Run the test suite. Extra arguments are passed to pytest.",
)
def handle_test(ctx: typer.Context) -> None:
    """Run the test suite, forwarding extra arguments to pytest."""
    test_dir = str(Path(__file__).resolve().parent.parent / "tests")
    cmd = [sys.executable, "-m", "pytest", test_dir, *ctx.args]
    raise SystemExit(subprocess.call(cmd))
