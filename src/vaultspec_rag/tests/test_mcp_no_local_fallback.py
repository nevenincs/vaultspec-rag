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

A second subprocess variant proves the same for the branch that *succeeds*.
The failed-call probe can only report on code reached before the daemon
answers, so on its own it leaves the path an agent session actually spends its
life on unasserted - and a function-local import there is invisible to the
module-scope scans too, because nothing about it happens at import time.
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

#: The libraries a thin client must never load, shared by both probes so the
#: success path and the failure path cannot come to police different sets.
_HEAVY_ML_LIBS = (
    "torch",
    "sentence_transformers",
    "qdrant_client",
    "transformers",
    "onnxruntime",
)


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
            forbidden=_HEAVY_ML_LIBS,
        )
    )


#: Drive every registered tool to a successful answer and prove each one
#: crossed the wire.
#:
#: The service is a stub returning one permissive envelope, deliberately not
#: the production route table: the subject is what the *client* interpreter
#: loads, and hosting real routes here would import the service half into the
#: very process under inspection, which is where the heavy libraries
#: legitimately live. Nothing is patched - discovery reads a real file whose
#: every schema-bearing value comes from the production constants, and each
#: call crosses a real loopback socket to a real listener.
#:
#: The child's own imports are kept to the narrowest set that can arrange this,
#: for the same reason: an import made by the arrangement is indistinguishable
#: in ``sys.modules`` from one made by the code under test, so a convenient
#: helper that reached the CLI or the server would quietly decide the result.
_DRIVE_EVERY_TOOL_TO_SUCCESS = """
import asyncio
import json
import os
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from vaultspec_rag._test_isolation import PYTEST_MANAGED_SINGLETON_ROOT_ENV
from vaultspec_rag.config._paths import SERVICE_STATUS_FILENAME
from vaultspec_rag.config._types import EnvVar
from vaultspec_rag.tests._http_stubs import QuietHandler

# Every managed path this child writes must sit beneath the session root it
# inherited, so its temp tree is created there rather than in the system
# temp dir. Both singleton anchors move: the status dir carries the
# discovery file, and the storage dir decides which machine lock is
# consulted - left at the ambient value, a lock another test holds would
# read as a live daemon whose address this file does not describe.
base = Path(tempfile.mkdtemp(dir=os.environ[PYTEST_MANAGED_SINGLETON_ROOT_ENV]))
status_dir = base / 'status'
status_dir.mkdir()
os.environ[EnvVar.STATUS_DIR.value] = str(status_dir)
os.environ[EnvVar.QDRANT_STORAGE_DIR.value] = str(base / 'qdrant')
workspace = base / 'workspace'
(workspace / '.vault').mkdir(parents=True)
(workspace / '.vaultspec').mkdir()

from vaultspec_rag.config._settings import reset_config

reset_config()

from vaultspec_rag.serviceclient._compat import (
    SERVICE_VERSION_FIELD,
    local_package_version,
)
from vaultspec_rag.serviceclient._discovery import (
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
)

seen = []
envelope = json.dumps(
    {'ok': True, 'results': [], 'summary': 'stub', 'content': 'stub source\\n'}
).encode('utf-8')


class _Stub(QuietHandler):
    def _answer(self):
        seen.append(self.path)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(envelope)))
        self.end_headers()
        self.wfile.write(envelope)

    def do_GET(self):
        self._answer()

    def do_POST(self):
        self._answer()


# Bound before it is advertised, and the port is read back off the bound
# socket: an ephemeral port cannot collide with a neighbour's, and a
# listener that is already accepting needs no readiness wait to guess at.
server = ThreadingHTTPServer(('127.0.0.1', 0), _Stub)
port = int(server.server_address[1])
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

(status_dir / SERVICE_STATUS_FILENAME).write_text(
    json.dumps(
        {
            'pid': os.getpid(),
            'port': port,
            'schema': SERVICE_DISCOVERY_SCHEMA,
            'version': SERVICE_DISCOVERY_VERSION,
            SERVICE_VERSION_FIELD: local_package_version(),
            'service_token': 'stub-service-token',
        }
    ),
    encoding='utf-8',
)

from vaultspec_rag.mcp import _tools
from vaultspec_rag.mcp._mcp import mcp

root = str(workspace)
calls = {
    'search_vault': lambda: _tools.search_vault('anything', project_root=root),
    'search_codebase': lambda: _tools.search_codebase('anything', project_root=root),
    'search_documents': lambda: _tools.search_documents('anything', project_root=root),
    'search_combined': lambda: _tools.search_combined('anything', project_root=root),
    'get_code_file': lambda: _tools.get_code_file('src/x.py', project_root=root),
    'get_index_status': lambda: _tools.get_index_status(project_root=root),
    'reindex_vault': lambda: _tools.reindex_vault(project_root=root),
    'reindex_codebase': lambda: _tools.reindex_codebase(project_root=root),
    'reindex_documents': lambda: _tools.reindex_documents(project_root=root),
    'reindex_all': lambda: _tools.reindex_all(project_root=root),
    'clean_documents': lambda: _tools.clean_documents(project_root=root),
    'clean_all': lambda: _tools.clean_all(project_root=root),
}
try:
    # Taken from the live registry, so a tool added to the surface without
    # being driven here fails rather than silently going unasserted.
    registered = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert registered == set(calls), sorted(registered ^ set(calls))
    for name, call in calls.items():
        before = len(seen)
        result = asyncio.run(call())
        assert result is not None, name
        # The positive control: a torch-freedom assertion over calls that
        # never reached the wire would pass on any arrangement at all.
        assert len(seen) > before, name
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
"""


def test_successful_calls_load_no_heavy_ml_libs() -> None:
    """A tool call that forwards and succeeds must not load Torch / models / store.

    The service-down probe above cannot see this: it stops at the guard that
    refuses, so nothing it asserts covers the code that runs once a daemon
    answers - which is every call in an ordinary session. Driven in a fresh
    interpreter for the same reason the sibling is, against a real listener so
    the success is the transport's and not an arrangement's.
    """
    assert_fresh_import_excludes(
        import_probe_source(
            setup=_DRIVE_EVERY_TOOL_TO_SUCCESS,
            forbidden=_HEAVY_ML_LIBS,
        )
    )
