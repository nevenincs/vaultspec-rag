"""Guard: cli/ and server/ must not use the phrase "MCP server" (case-insensitive).

Background
----------
The phrase "MCP server" inside ``cli/`` and ``server/`` conflates two distinct
concepts:

* The **MCP stdio protocol server** — the ``vaultspec-search-mcp`` entry-point
  that speaks the Model Context Protocol over stdio.  Managed by
  ``cli/_mcp_admin.py``.

* The **daemon / HTTP service** — the long-running ``vaultspec-rag server
  service`` process that serves REST endpoints and embeds GPU models.

When code outside of the designated MCP control module uses "MCP server" it
usually means the HTTP daemon, which creates confusion and naming drift.
Strings like "Start the MCP server" in a daemon lifecycle module are
the exact conflation this guard exists to prevent.

Exemptions
----------
``cli/_mcp_admin.py``
    This file *is* the CLI control surface for the genuine MCP stdio protocol
    server (start / stop / status for ``vaultspec-search-mcp``).  The phrase
    "MCP server" there is semantically correct and must not be silenced.

``mcp/`` package
    The entire ``mcp/`` package speaks MCP natively; "MCP server" is on-topic.

Status
------
Enforced invariant. The conflated strings in cli/ and server/ were corrected in
the P06 deconflation; this guard keeps them from regressing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# src/vaultspec_rag/tests/<this file>  ->  parents[1] is src/vaultspec_rag
_PKG_ROOT = Path(__file__).resolve().parents[1]
_CLI_DIR = _PKG_ROOT / "cli"
_SERVER_DIR = _PKG_ROOT / "server"

# Exempt: the genuine MCP stdio server control surface.
_EXEMPT_FILES = {
    _CLI_DIR / "_mcp_admin.py",
}

_PHRASE = "mcp server"


def _collect_target_files() -> list[Path]:
    files: list[Path] = []
    for directory in (_CLI_DIR, _SERVER_DIR):
        files.extend(sorted(directory.glob("**/*.py")))
    return [f for f in files if f not in _EXEMPT_FILES]


@pytest.mark.unit
@pytest.mark.parametrize("src_file", _collect_target_files(), ids=lambda p: p.name)
def test_no_mcp_server_conflation(src_file: Path) -> None:
    """cli/ and server/ files must not contain the phrase 'MCP server'.

    The exemption for ``cli/_mcp_admin.py`` is intentional: that module is the
    legitimate control surface for the real MCP stdio protocol server
    (start/stop/status for ``vaultspec-search-mcp``), so the phrase is correct
    there.  Every other file in cli/ and server/ that uses "MCP server" is
    conflating the stdio server with the HTTP daemon.
    """
    text = src_file.read_text(encoding="utf-8")
    hits: list[int] = [
        i + 1 for i, line in enumerate(text.splitlines()) if _PHRASE in line.lower()
    ]
    assert not hits, (
        f"{src_file.relative_to(_PKG_ROOT)} contains 'MCP server' "
        f"(conflation — see module docstring) on line(s): {hits}"
    )
