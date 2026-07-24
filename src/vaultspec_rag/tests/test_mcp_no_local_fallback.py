"""Guard: every MCP tool/resource fails clearly when the daemon is down.

The MCP is a thin service client with **no local fallback**: when no
``service.json`` is present (the daemon is not running) every tool, admin tool,
and resource must raise a single clear ``RuntimeError`` whose message contains
"is not running", and must spin up no local engine — no GPU model, no vector
store — in the process.

These tests are mock-free.  They redirect the status directory at a *real*
empty ``tmp_path`` via ``VAULTSPEC_RAG_STATUS_DIR`` (the project's designated
isolation mechanism — see the ``feedback_service_tests_isolate_STATUS_DIR``
memory note), then drive each tool through ``asyncio.run`` and assert the real
status-file read and real client path reach the missing-service guard.  A
subprocess variant additionally proves the heavy ML libraries stay out of
``sys.modules`` after a failed call (in-process ``sys.modules`` is
session-polluted, so the no-load assertion is only meaningful in a fresh
interpreter): the MCP server is a thin service client and never runs a
local fallback in its own interpreter.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from ._import_probe import assert_fresh_import_excludes, import_probe_source

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _tool_invocations() -> list[tuple[str, Callable[[], Coroutine[Any, Any, Any]]]]:
    """Return ``(id, thunk)`` pairs covering every MCP tool and resource.

    Each thunk builds a fresh coroutine when called so it can be driven through
    ``asyncio.run`` exactly once per test.  Imports are local to keep this module
    import-light and to mirror how the MCP package is reached at runtime.
    """
    from ..mcp._resources import get_vault_document
    from ..mcp._tools import (
        get_code_file,
        reindex_codebase,
        reindex_vault,
        search_codebase,
        search_vault,
    )

    return [
        ("search_vault", lambda: search_vault("anything")),
        ("search_codebase", lambda: search_codebase("anything")),
        ("get_code_file", lambda: get_code_file("src/x.py")),
        ("reindex_vault", lambda: reindex_vault()),
        ("reindex_codebase", lambda: reindex_codebase()),
        ("get_vault_document", lambda: get_vault_document("adr/overview")),
    ]


_INVOCATIONS = _tool_invocations()


@pytest.mark.parametrize(
    "make_coro",
    [thunk for _, thunk in _INVOCATIONS],
    ids=[name for name, _ in _INVOCATIONS],
)
def test_tool_raises_service_not_running(
    make_coro: Callable[[], Coroutine[Any, Any, Any]],
    isolated_singleton_dirs: Path,
) -> None:
    """With no service.json, every MCP tool/resource raises the service-down error.

    This exercises the real ``serviceclient`` discovery read against an empty
    status dir and proves the call reaches the single no-local-fallback guard
    rather than constructing a local engine.
    """
    assert not (isolated_singleton_dirs / "service.json").exists()
    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(make_coro())
    # SD6: the failure must be fast and carry the full actionable remediation,
    # not just the "is not running" diagnosis - a regression dropping the
    # start-the-service instruction must fail this test.
    message = str(exc_info.value)
    assert "is not running" in message
    assert "vaultspec-rag server start" in message


def test_failed_call_loads_no_heavy_ml_libs() -> None:
    """A failed (service-down) tool call must not load Torch / models / store.

    Run in a fresh interpreter subprocess so the in-process session pollution
    cannot mask the absence of a local-engine spin-up.  The status dir is
    redirected at a real empty temp dir; the search tool is driven to its
    service-down ``RuntimeError``; then ``sys.modules`` is asserted free of the
    heavy ML libraries.
    """
    drive_a_failed_search = (
        "import os, tempfile, asyncio\n"
        "d = tempfile.mkdtemp()\n"
        "os.environ['VAULTSPEC_RAG_STATUS_DIR'] = d\n"
        "os.environ['VAULTSPEC_RAG_QDRANT_STORAGE_DIR'] = os.path.join(d, 'qdrant')\n"
        "from vaultspec_rag.mcp._tools import search_vault\n"
        "raised = False\n"
        "try:\n"
        "    asyncio.run(search_vault('anything'))\n"
        "except RuntimeError as exc:\n"
        "    raised = 'is not running' in str(exc)\n"
        "assert raised, 'expected service-not-running RuntimeError'\n"
    )
    assert_fresh_import_excludes(
        import_probe_source(
            setup=drive_a_failed_search,
            forbidden=(
                "torch",
                "sentence_transformers",
                "qdrant_client",
                "transformers",
                "onnxruntime",
            ),
        )
    )
