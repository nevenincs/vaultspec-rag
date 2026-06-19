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
interpreter).  See the ``mcp-service-client`` ADR (D7).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

from ..config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    """Point the service status dir at an empty *tmp_path* with no service.json.

    Sets ``VAULTSPEC_RAG_STATUS_DIR`` to a fresh empty directory and calls
    ``reset_config()`` on enter and exit so the cached config picks up (and then
    forgets) the redirect.  No ``service.json`` is written, so service discovery
    must conclude the daemon is down.
    """
    prev = os.environ.get(EnvVar.STATUS_DIR.value)
    status_dir = tmp_path / "vaultspec-rag"
    status_dir.mkdir()
    os.environ[EnvVar.STATUS_DIR.value] = str(status_dir)
    reset_config()
    try:
        yield status_dir
    finally:
        if prev is None:
            os.environ.pop(EnvVar.STATUS_DIR.value, None)
        else:
            os.environ[EnvVar.STATUS_DIR.value] = prev
        reset_config()


def _tool_invocations() -> list[tuple[str, Callable[[], Coroutine[Any, Any, Any]]]]:
    """Return ``(id, thunk)`` pairs covering every MCP tool and resource.

    Each thunk builds a fresh coroutine when called so it can be driven through
    ``asyncio.run`` exactly once per test.  Imports are local to keep this module
    import-light and to mirror how the MCP package is reached at runtime.
    """
    from ..mcp._admin_tools import (
        benchmark,
        evict_project,
        get_jobs,
        get_logs,
        get_service_state,
        get_watcher_state,
        list_projects,
        quality,
        reconfigure_watcher,
        start_watcher,
        stop_watcher,
    )
    from ..mcp._resources import get_vault_document
    from ..mcp._tools import (
        get_code_file,
        get_index_status,
        reindex_codebase,
        reindex_vault,
        search_codebase,
        search_vault,
    )

    return [
        ("search_vault", lambda: search_vault("anything")),
        ("search_codebase", lambda: search_codebase("anything")),
        ("get_index_status", lambda: get_index_status()),
        ("get_code_file", lambda: get_code_file("src/x.py")),
        ("reindex_vault", lambda: reindex_vault()),
        ("reindex_codebase", lambda: reindex_codebase()),
        ("list_projects", lambda: list_projects()),
        ("evict_project", lambda: evict_project("/some/root")),
        ("get_watcher_state", lambda: get_watcher_state()),
        ("start_watcher", lambda: start_watcher("/some/root")),
        ("stop_watcher", lambda: stop_watcher("/some/root")),
        ("get_service_state", lambda: get_service_state()),
        ("get_logs", lambda: get_logs()),
        ("get_jobs", lambda: get_jobs()),
        ("reconfigure_watcher", lambda: reconfigure_watcher("/some/root")),
        ("benchmark", lambda: benchmark()),
        ("quality", lambda: quality()),
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
    isolated_status_dir: Path,
) -> None:
    """With no service.json, every MCP tool/resource raises the service-down error.

    This exercises the real ``serviceclient`` discovery read against an empty
    status dir and proves the call reaches the single no-local-fallback guard
    rather than constructing a local engine.
    """
    assert not (isolated_status_dir / "service.json").exists()
    with pytest.raises(RuntimeError, match="is not running"):
        asyncio.run(make_coro())


def test_failed_call_loads_no_heavy_ml_libs() -> None:
    """A failed (service-down) tool call must not load Torch / models / store.

    Run in a fresh interpreter subprocess so the in-process session pollution
    cannot mask the absence of a local-engine spin-up.  The status dir is
    redirected at a real empty temp dir; the search tool is driven to its
    service-down ``RuntimeError``; then ``sys.modules`` is asserted free of the
    heavy ML libraries.
    """
    code = (
        "import os, sys, tempfile, asyncio\n"
        "d = tempfile.mkdtemp()\n"
        "os.environ['VAULTSPEC_RAG_STATUS_DIR'] = d\n"
        "from vaultspec_rag.mcp._tools import search_vault\n"
        "raised = False\n"
        "try:\n"
        "    asyncio.run(search_vault('anything'))\n"
        "except RuntimeError as exc:\n"
        "    raised = 'is not running' in str(exc)\n"
        "assert raised, 'expected service-not-running RuntimeError'\n"
        "forbidden = ('torch', 'sentence_transformers', 'qdrant_client', "
        "'transformers', 'onnxruntime')\n"
        "heavy = sorted(\n"
        "    m\n"
        "    for m in sys.modules\n"
        "    if any(m == f or m.startswith(f + '.') for f in forbidden)\n"
        ")\n"
        "assert not heavy, heavy\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
