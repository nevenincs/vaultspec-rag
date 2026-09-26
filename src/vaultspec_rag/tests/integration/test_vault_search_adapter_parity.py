"""The CLI and the MCP tool return the same vault hits, located the same way.

Both entry points answer a vault query through the service's one search
route, so for one query against one index they must hand back identical
hits: the same records, the same chosen passage, the same line span and the
same section. Driven against a real service and a real index, so the
passage is chosen by the real reranker and the span is read back from the
file the index was built from.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast

import pytest

from ...mcp import _tools as tools
from .._cli_helpers import app, runner
from ._helpers import seed_vault_publication

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.subprocess_gpu]

_RECORD = "adr/2026-07-16-stdio-lifetime-adr"

_BODY = """---
tags:
  - '#adr'
  - '#stdio-lifetime'
date: '2026-07-16'
---

# `stdio-lifetime` adr: `reap orphaned stdio servers` | (**status:** `accepted`)

## Problem Statement

Editor sessions start a stdio server per window and do not always stop it.
When the editor dies, the server keeps its pipes and its memory, and nothing
in the service notices, so orphaned servers accumulate across a working day
until a machine restart clears them.

## Considered options

- **Client watchdog (chosen).** Resolve the process that created the stdin
  pipe, hold a handle to it, and exit as soon as that process is gone.
- **Idle timeout.** Rejected: it kills long-lived quiet sessions that are
  still attached, or waits so long that orphans pile up anyway.

## Consequences

Servers now exit within a second of their client, and no quiet session is
ever stopped while its editor is alive.
"""

_QUERY = "why was an idle timeout rejected as the way to reap orphaned servers"


def _vault_root(tmp_path: Path) -> Path:
    record = tmp_path / ".vault" / f"{_RECORD}.md"
    record.parent.mkdir(parents=True)
    (tmp_path / ".vaultspec").mkdir()
    record.write_text(_BODY, encoding="utf-8", newline="\n")
    return tmp_path


def _without_scores(hits: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {key: value for key, value in hit.items() if key != "score"} for hit in hits
    ]


def test_cli_and_mcp_return_the_same_located_vault_hits(
    tmp_path: Path,
    live_service: tuple[int, Path],
) -> None:
    port, _status_dir = live_service
    root = _vault_root(tmp_path)
    asyncio.run(seed_vault_publication(port, root))

    via_mcp = asyncio.run(tools.search_vault(_QUERY, top_k=3, project_root=str(root)))
    mcp_hits = via_mcp.results
    assert mcp_hits, via_mcp
    cli = runner.invoke(
        app,
        [
            "--target",
            str(root),
            "search",
            _QUERY,
            "--type",
            "vault",
            "--max-results",
            "3",
            "--port",
            str(port),
            "--json",
        ],
    )
    assert cli.exit_code == 0, cli.output
    cli_hits = cast(
        "list[dict[str, object]]", json.loads(cli.output)["data"]["results"]
    )

    assert _without_scores(cli_hits) == _without_scores(mcp_hits)
    for cli_hit, mcp_hit in zip(cli_hits, mcp_hits, strict=True):
        assert cli_hit["score"] == pytest.approx(mcp_hit["score"], abs=1e-4)

    top = cli_hits[0]
    assert top["id"] == _RECORD
    assert top["section"] == "Considered options"
    snippet = cast("str", top["snippet"])
    assert "kills long-lived quiet sessions" in snippet
    assert "rerank_text" not in top
    assert "passages" not in top
    line_start, line_end = cast("int", top["line_start"]), cast("int", top["line_end"])
    lines = _BODY.split("\n")
    assert "\n".join(lines[line_start - 1 : line_end]).strip() == snippet
