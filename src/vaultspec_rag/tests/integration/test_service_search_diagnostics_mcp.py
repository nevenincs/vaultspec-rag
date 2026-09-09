"""The MCP search probe used against a live service.

An MCP caller reaches search through its own process and its own
transport, so it is the one surface that can disagree with the HTTP route
about whether an index is available. Driving it means standing up a real
stdio server, waiting for a real session handshake, and only then joining
the barrier the other probes are waiting on.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING, cast

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from ...config._paths import SERVICE_STATUS_FILENAME
from ...serviceclient._compat import SERVICE_VERSION_FIELD, local_package_version
from ...serviceclient._discovery import (
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
)
from .._http_stubs import QuietHandler
from .._search_readiness_scenarios import (
    SEARCH_READINESS_SCENARIOS,
    SearchReadinessScenario,
    canonical_service_envelope,
)
from ._service_search_diagnostics_support import bounded_failure_evidence

if TYPE_CHECKING:
    from collections.abc import Generator
    from concurrent.futures import Future
    from pathlib import Path
    from typing import TextIO

    from mcp.types import CallToolResult

pytestmark = [pytest.mark.unit]

__all__ = [
    "McpConcurrentRequest",
    "assert_mcp_unavailable_response",
    "mcp_search_after_concurrent_admission",
    "wait_for_mcp_initialization",
]


@dataclass(frozen=True, slots=True)
class McpConcurrentRequest:
    """One MCP search process attached to a matching rebuild barrier."""

    port: int
    status_dir: Path
    root: Path
    query: str


async def _mcp_search_after_concurrent_admission_async(
    admission: threading.Barrier,
    initialized: threading.Event,
    request: McpConcurrentRequest,
) -> CallToolResult:
    env = dict(os.environ)
    env.update(
        {
            "VAULTSPEC_RAG_PORT": str(request.port),
            "VAULTSPEC_RAG_ROOT": str(request.root),
            "VAULTSPEC_RAG_STATUS_DIR": str(request.status_dir),
        }
    )
    server = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from vaultspec_rag.server import main; main()"],
        env=env,
    )
    async with (
        stdio_client(server, errlog=cast("TextIO", sys.__stderr__)) as (
            read_stream,
            write_stream,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await asyncio.wait_for(session.initialize(), timeout=60)
        initialized.set()
        await asyncio.wait_for(
            asyncio.to_thread(admission.wait, 10),
            timeout=15,
        )
        return await asyncio.wait_for(
            session.call_tool(
                "search_vault",
                arguments={
                    "query": request.query,
                    "top_k": 5,
                    "project_root": str(request.root),
                },
                read_timeout_seconds=300,
            ),
            timeout=310,
        )


def mcp_search_after_concurrent_admission(
    admission: threading.Barrier,
    initialized: threading.Event,
    request: McpConcurrentRequest,
) -> CallToolResult:
    return asyncio.run(
        _mcp_search_after_concurrent_admission_async(
            admission,
            initialized,
            request,
        )
    )


def wait_for_mcp_initialization(
    initialized: threading.Event,
    mcp_future: Future[CallToolResult],
    port: int,
    token: str,
) -> None:
    if initialized.wait(timeout=65):
        return
    failure = "session initialization did not complete"
    if mcp_future.done():
        try:
            mcp_future.result()
        except Exception as exc:
            failure = f"session initialization failed: {exc}"
    pytest.fail(
        f"MCP {failure}\n"
        + bounded_failure_evidence(
            port,
            token,
            "not-submitted",
        )
    )


def assert_mcp_unavailable_response(
    response: CallToolResult,
    *,
    evidence: str,
) -> None:
    assert response.is_error is False, evidence
    text = " ".join(
        block.text for block in response.content if isinstance(block, TextContent)
    )
    assert "index_unavailable" in text, evidence
    assert "vaultspec-rag server jobs" in text, evidence
    structured = cast("dict[str, object]", response.structured_content)
    assert structured["ok"] is False, evidence
    assert structured["error"] == "index_unavailable", evidence
    assert "results" not in structured, evidence


@contextmanager
def _canonical_search_service(
    tmp_path: Path,
    *,
    scenario: SearchReadinessScenario,
) -> Generator[tuple[int, Path, list[dict[str, object]]]]:
    requests: list[dict[str, object]] = []

    class _SearchHandler(QuietHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = cast(
                "dict[str, object]",
                json.loads(self.rfile.read(length).decode("utf-8")),
            )
            requests.append(body)
            payload = canonical_service_envelope(scenario)
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(scenario.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            with contextlib.suppress(OSError):
                self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _SearchHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    (status_dir / SERVICE_STATUS_FILENAME).write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "port": server.server_port,
                "schema": SERVICE_DISCOVERY_SCHEMA,
                "version": SERVICE_DISCOVERY_VERSION,
                SERVICE_VERSION_FIELD: local_package_version(),
                "service_token": "mcp-contract-token",
            }
        ),
        encoding="utf-8",
    )
    try:
        yield server.server_port, status_dir, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def _official_search_call(
    *,
    port: int,
    status_dir: Path,
    root: Path,
    tool_name: str,
) -> CallToolResult:
    env = dict(os.environ)
    env.update(
        {
            "VAULTSPEC_RAG_PORT": str(port),
            "VAULTSPEC_RAG_ROOT": str(root),
            "VAULTSPEC_RAG_STATUS_DIR": str(status_dir),
        }
    )
    server = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from vaultspec_rag.server import main; main()"],
        env=env,
    )
    async with (
        stdio_client(server, errlog=cast("TextIO", sys.__stderr__)) as (
            read_stream,
            write_stream,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await asyncio.wait_for(session.initialize(), timeout=60)
        return await asyncio.wait_for(
            session.call_tool(
                tool_name,
                arguments={"query": "readiness contract", "project_root": str(root)},
                read_timeout_seconds=60,
            ),
            timeout=70,
        )


@pytest.mark.parametrize(
    "scenario", SEARCH_READINESS_SCENARIOS.values(), ids=lambda item: item.name
)
def test_official_client_preserves_canonical_search_envelope(
    tmp_path: Path,
    scenario: SearchReadinessScenario,
) -> None:
    source = (
        "combined"
        if len(scenario.source_facts) > 1
        else next(iter(scenario.source_facts)).source
    )
    tool_name = {
        "vault": "search_vault",
        "code": "search_codebase",
        "document": "search_documents",
        "combined": "search_combined",
    }[source]
    root = tmp_path / scenario.name
    (root / ".vaultspec").mkdir(parents=True)
    with _canonical_search_service(tmp_path, scenario=scenario) as (
        port,
        status_dir,
        requests,
    ):
        response = asyncio.run(
            _official_search_call(
                port=port,
                status_dir=status_dir,
                root=root,
                tool_name=tool_name,
            )
        )

    # Mutation proof (exact matrix case ``unavailable``): temporarily
    # restoring the legacy recoverable-failure RuntimeError reducer made this
    # exact assertion fail with ``is_error=True`` and ``structured_content=None``
    # (RED exit 1); in the same uninterrupted sequence, immediately removing the
    # reducer restored the identical case to a structured result (GREEN exit 0).
    assert response.is_error is False
    structured = cast("dict[str, object]", response.structured_content)
    expected = canonical_service_envelope(scenario)
    assert structured == expected
    readiness = cast("dict[str, object]", structured["readiness"])
    expected_sources = [fact.source for fact in scenario.source_facts]
    source_facts = cast("list[dict[str, object]]", readiness["sources"])
    assert [fact["source"] for fact in source_facts] == expected_sources
    assert source_facts == [fact.as_dict() for fact in scenario.source_facts]
    assert readiness["aggregate"] == scenario.aggregate.as_dict()
    text = " ".join(
        block.text for block in response.content if isinstance(block, TextContent)
    )
    if scenario.failure is None:
        assert structured["results"] == scenario.result_payloads()
        assert structured["request_id"] == scenario.request_id
        assert ("ok" in structured) is (source == "combined")
        # FastMCP's text companion must remain useful without requiring callers to
        # decode the already-exact structured payload asserted above.
        assert "readiness" in text
        for expected_source in expected_sources:
            assert expected_source in text
        if scenario.results:
            for result in scenario.results:
                assert result.text in text
        else:
            assert "results" in text
            assert "[]" in text
            assert "authoritative" in text
    else:
        assert structured["ok"] is False
        assert structured["error"] == scenario.failure.code
        assert structured["message"] == scenario.failure.message
        assert structured["retryable"] is scenario.failure.retryable
        assert structured["request_id"] == scenario.request_id
        assert structured["remediation"] == scenario.failure.remediation
        assert "results" not in structured
        assert scenario.failure.code in text
        assert scenario.failure.message in text
        assert scenario.failure.remediation in text
    assert len(requests) == 1
    assert requests[0]["type"] == source
