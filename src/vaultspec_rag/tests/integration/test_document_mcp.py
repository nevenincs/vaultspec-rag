"""Real MCP-session coverage for document-domain adapters."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


async def _exercise_document_tools(port: int, root: Path) -> None:
    env = dict(os.environ)
    env.update(
        {
            "VAULTSPEC_RAG_PORT": str(port),
            "VAULTSPEC_RAG_ROOT": str(root),
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
        tools = await asyncio.wait_for(session.list_tools(), timeout=60)
        names = {tool.name for tool in tools.tools}
        assert {
            "search_documents",
            "search_combined",
            "reindex_documents",
            "reindex_all",
            "clean_documents",
            "clean_all",
            "get_index_status",
        } <= names

        for name, arguments in (
            ("search_documents", {"query": "empty", "project_root": str(root)}),
            ("search_combined", {"query": "empty", "project_root": str(root)}),
            ("clean_documents", {"project_root": str(root)}),
            ("clean_all", {"project_root": str(root)}),
            ("get_index_status", {"project_root": str(root)}),
        ):
            result = await asyncio.wait_for(
                session.call_tool(
                    name,
                    arguments=arguments,
                    read_timeout_seconds=timedelta(seconds=60),
                ),
                timeout=70,
            )
            assert result.isError is not True, (name, result)
            assert isinstance(result.structuredContent, dict), (name, result)

        status = await session.call_tool(
            "get_index_status",
            arguments={"project_root": str(root)},
            read_timeout_seconds=timedelta(seconds=60),
        )
        status_payload = cast("dict[str, Any]", status.structuredContent)
        index = cast("dict[str, Any]", status_payload["index"])
        assert index["document_chunks"] == 0
        assert set(index["support_profile"]["domains"]) == {"code", "document"}

        for name in ("reindex_documents", "reindex_all"):
            result = await asyncio.wait_for(
                session.call_tool(
                    name,
                    arguments={"project_root": str(root)},
                    read_timeout_seconds=timedelta(seconds=60),
                ),
                timeout=70,
            )
            assert result.isError is not True, (name, result)
            assert isinstance(result.structuredContent, dict), (name, result)


def test_document_tools_through_real_mcp_session(
    live_service: tuple[int, Path],
) -> None:
    port, root = live_service
    asyncio.run(_exercise_document_tools(port, root))
