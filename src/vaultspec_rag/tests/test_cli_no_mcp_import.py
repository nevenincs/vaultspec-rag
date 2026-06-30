"""The CLI/daemon import path must not load the optional ``mcp`` extra.

``mcp`` is an opt-in extra (the ``mcp-optional-dependency`` ADR), because the CLI
and the HTTP search daemon never import it - so a base install must not drag it
or, on Windows, its ``pywin32`` transitive. This guard runs in a fresh
interpreter subprocess: the in-process ``sys.modules`` is polluted by other
tests that import ``mcp``, so the no-import assertion is only meaningful in a
clean interpreter.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = [pytest.mark.unit]

_CHECK = """
import sys

import vaultspec_rag  # noqa: F401
from vaultspec_rag.cli import app  # noqa: F401

forbidden_prefixes = ("win32", "pywintypes", "pythoncom")
loaded = sorted(
    m
    for m in sys.modules
    if m == "mcp"
    or m.startswith("mcp.")
    or m.startswith(forbidden_prefixes)
)
assert not loaded, loaded
"""


def test_cli_import_loads_no_mcp_or_pywin32() -> None:
    """Importing the package and the CLI app must pull in no mcp / pywin32."""
    proc = subprocess.run(
        [sys.executable, "-c", _CHECK],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
