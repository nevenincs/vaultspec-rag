"""Guard: cli/ and server/ must not use the phrase "MCP server" (case-insensitive).

Background
----------
The phrase "MCP server" inside ``cli/`` and ``server/`` conflates two distinct
concepts:

* The **MCP stdio transport** — the ``vaultspec-search-mcp`` entry-point that
  speaks the Model Context Protocol over stdio.  It lives in the ``mcp/``
  package and is served by the stdio branch of ``server/_main.py`` as a thin
  forwarder to the daemon.

* The **daemon / HTTP service** — the long-running ``vaultspec-rag server
  service`` process that serves REST endpoints and embeds GPU models.

When code in ``cli/`` or ``server/`` uses "MCP server" it usually means the
HTTP daemon, which creates confusion and naming drift.  Strings like "Start the
MCP server" in a daemon lifecycle module are the exact conflation this guard
exists to prevent.

Scope
-----
``mcp/`` package
    The entire ``mcp/`` package speaks MCP natively; "MCP server" is on-topic
    there, so the guard scans only ``cli/`` and ``server/``.

There are no per-file exemptions: every file under ``cli/`` and ``server/``
must avoid the conflated phrase.  The stdio transport is described in precise
terms ("MCP stdio transport", "stdio forwarder") rather than the ambiguous
"MCP server".

Status
------
Enforced invariant. The conflated strings in cli/ and server/ were corrected in
the deconflation and thin-client reworks; this guard keeps them from
regressing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# src/vaultspec_rag/tests/<this file>  ->  parents[1] is src/vaultspec_rag
_PKG_ROOT = Path(__file__).resolve().parents[1]
_CLI_DIR = _PKG_ROOT / "cli"
_SERVER_DIR = _PKG_ROOT / "server"

_PHRASE = "mcp server"


def _collect_target_files() -> list[Path]:
    files: list[Path] = []
    for directory in (_CLI_DIR, _SERVER_DIR):
        files.extend(sorted(directory.glob("**/*.py")))
    return files


@pytest.mark.unit
@pytest.mark.parametrize("src_file", _collect_target_files(), ids=lambda p: p.name)
def test_no_mcp_server_conflation(src_file: Path) -> None:
    """cli/ and server/ files must not contain the phrase 'MCP server'.

    The genuine stdio transport lives in the ``mcp/`` package (not scanned) and
    is described in precise terms where the ``server/`` entry point references
    it.  Every file in cli/ and server/ that uses "MCP server" is conflating
    the stdio transport with the HTTP daemon.
    """
    text = src_file.read_text(encoding="utf-8")
    hits: list[int] = [
        i + 1 for i, line in enumerate(text.splitlines()) if _PHRASE in line.lower()
    ]
    assert not hits, (
        f"{src_file.relative_to(_PKG_ROOT)} contains 'MCP server' "
        f"(conflation — see module docstring) on line(s): {hits}"
    )
