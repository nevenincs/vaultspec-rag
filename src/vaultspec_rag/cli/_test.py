"""``test`` command: forward extra args to pytest over the test tree."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer  # noqa: TC002 - Typer resolves annotations at runtime

from ._app import app


@app.command(
    "test",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def handle_test(ctx: typer.Context) -> None:
    """Run the test suite via pytest.

    All extra arguments are forwarded to pytest.

    Args:
        ctx: Typer context whose ``args`` are passed through
            to pytest.

    Raises:
        SystemExit: Propagates pytest's exit code.

    Examples::

        vaultspec-rag test
        vaultspec-rag test -m unit
        vaultspec-rag test -m integration -v --timeout=120

    """
    test_dir = str(Path(__file__).resolve().parent.parent / "tests")
    cmd = [sys.executable, "-m", "pytest", test_dir, *ctx.args]
    raise SystemExit(subprocess.call(cmd))
