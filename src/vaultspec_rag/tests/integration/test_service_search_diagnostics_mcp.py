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
from ._service_search_diagnostics_support import bounded_failure_evidence

if TYPE_CHECKING:
    from collections.abc import Generator
    from concurrent.futures import Future
    from pathlib import Path

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


def _readiness(source: str, *, available: bool) -> dict[str, object]:
    sources = ("vault", "code", "document") if source == "combined" else (source,)
    facts: list[dict[str, object]] = [
        {
            "source": item,
            "availability": "usable" if available else "unavailable",
            "freshness": "current" if available else "unverifiable",
            "absence_authority": (
                "authoritative" if available else "non_authoritative"
            ),
            "generation": {},
            "wait_policy": "immediate",
            "waits": [],
            "evidence": [],
            "reason_code": (
                "published_generation_current" if available else "index_unavailable"
            ),
            "retryable": not available,
            "remediation": None if available else "vaultspec-rag server status",
        }
        for item in sources
    ]
    return {
        "sources": facts,
        "aggregate": {
            "availability": "usable" if available else "unavailable",
            "freshness": "current" if available else "unverifiable",
            "absence_authority": (
                "authoritative" if available else "non_authoritative"
            ),
            "source_count": len(sources),
            "usable_source_count": len(sources) if available else 0,
            "degraded_sources": [] if available else list(sources),
        },
    }


@contextmanager
def _canonical_search_service(
    tmp_path: Path,
    *,
    available: bool,
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
            source = str(body["type"])
            if available:
                payload: dict[str, object] = {
                    "results": [],
                    "request_id": "mcp-success",
                    "readiness": _readiness(source, available=True),
                }
                if source == "combined":
                    payload["ok"] = True
            else:
                payload = {
                    "ok": False,
                    "error": "index_unavailable",
                    "message": "The requested index is unavailable.",
                    "retryable": True,
                    "request_id": "mcp-failure",
                    "remediation": "vaultspec-rag server status",
                    "readiness": _readiness(source, available=False),
                }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200 if available else 503)
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
        stdio_client(server) as (read_stream, write_stream),
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
    ("tool_name", "source"),
    [
        ("search_vault", "vault"),
        ("search_codebase", "code"),
        ("search_documents", "document"),
        ("search_combined", "combined"),
    ],
)
@pytest.mark.parametrize("available", [True, False], ids=["success", "failure"])
def test_official_client_preserves_canonical_search_envelope(
    tmp_path: Path,
    tool_name: str,
    source: str,
    *,
    available: bool,
) -> None:
    root = tmp_path / f"{source}-{available}"
    (root / ".vaultspec").mkdir(parents=True)
    with _canonical_search_service(tmp_path, available=available) as (
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

    assert response.is_error is False
    structured = cast("dict[str, object]", response.structured_content)
    readiness = cast("dict[str, object]", structured["readiness"])
    expected_sources = (
        ["vault", "code", "document"] if source == "combined" else [source]
    )
    source_facts = cast("list[dict[str, object]]", readiness["sources"])
    assert [fact["source"] for fact in source_facts] == expected_sources
    expected_availability = "usable" if available else "unavailable"
    expected_freshness = "current" if available else "unverifiable"
    expected_authority = "authoritative" if available else "non_authoritative"
    for fact, expected_source in zip(source_facts, expected_sources, strict=True):
        expected_fact: dict[str, object] = {
            "source": expected_source,
            "availability": expected_availability,
            "freshness": expected_freshness,
            "absence_authority": expected_authority,
            "generation": {},
            "wait_policy": "immediate",
            "waits": [],
            "evidence": [],
            "reason_code": (
                "published_generation_current" if available else "index_unavailable"
            ),
            "retryable": not available,
        }
        if not available:
            expected_fact["remediation"] = "vaultspec-rag server status"
        assert fact == expected_fact
    aggregate = cast("dict[str, object]", readiness["aggregate"])
    assert aggregate == {
        "availability": expected_availability,
        "freshness": expected_freshness,
        "absence_authority": expected_authority,
        "source_count": len(expected_sources),
        "usable_source_count": len(expected_sources) if available else 0,
        "degraded_sources": [] if available else expected_sources,
    }
    text = " ".join(
        block.text for block in response.content if isinstance(block, TextContent)
    )
    if available:
        expected_keys = {"results", "request_id", "readiness"}
        if source == "combined":
            expected_keys.add("ok")
        assert set(structured) == expected_keys
        assert structured["results"] == []
        assert structured["request_id"] == "mcp-success"
        assert ("ok" in structured) is (source == "combined")
    else:
        assert set(structured) == {
            "ok",
            "error",
            "message",
            "retryable",
            "request_id",
            "remediation",
            "readiness",
        }
        assert structured["ok"] is False
        assert structured["error"] == "index_unavailable"
        assert structured["message"] == "The requested index is unavailable."
        assert structured["retryable"] is True
        assert structured["request_id"] == "mcp-failure"
        assert structured["remediation"] == "vaultspec-rag server status"
        assert "results" not in structured
        assert "index_unavailable" in text
        assert "The requested index is unavailable." in text
        assert "vaultspec-rag server status" in text
    assert len(requests) == 1
    assert requests[0]["type"] == source
