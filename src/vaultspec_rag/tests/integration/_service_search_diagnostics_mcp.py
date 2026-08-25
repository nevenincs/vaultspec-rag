"""The MCP search probe used against a live service.

An MCP caller reaches search through its own process and its own
transport, so it is the one surface that can disagree with the HTTP route
about whether an index is available. Driving it means standing up a real
stdio server, waiting for a real session handshake, and only then joining
the barrier the other probes are waiting on.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from ._service_search_diagnostics_support import bounded_failure_evidence

if TYPE_CHECKING:
    import threading
    from concurrent.futures import Future
    from pathlib import Path

    from mcp.types import CallToolResult

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
        stdio_client(server) as (read_stream, write_stream),
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
    assert response.is_error is True, evidence
    text = " ".join(
        block.text for block in response.content if isinstance(block, TextContent)
    )
    assert "index_unavailable" in text, evidence
    assert "vaultspec-rag server jobs" in text, evidence
    structured = cast("dict[str, object] | None", response.structured_content)
    assert structured is None or "results" not in structured, evidence
