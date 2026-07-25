"""Real MCP-session coverage for document-domain adapters."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import textwrap
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ...serviceclient._transport import (
    _do_http_call,
    _try_http_get_job,
    _try_http_reindex,
    _try_http_search,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration, pytest.mark.timeout(900)]


def _command(script: Path) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{path}}"


def _write_indexed_document_fixture(root: Path) -> tuple[str, str]:
    source_path = "records/selected.blob"
    phrase = "bounded transport retrieval evidence"
    records = root / "records"
    records.mkdir(exist_ok=True)
    (root / source_path).write_bytes(b"\x00\xff independently extracted input")
    extractor = root / "extract.py"
    extractor.write_text(
        textwrap.dedent(f"""
            import json, sys
            print(json.dumps({{
                "schema_version": 1,
                "preprocessor_id": "transport-extractor",
                "preprocessor_version": "1",
                "source_path": sys.argv[1],
                "text": {f"{phrase}. Real daemon and MCP retrieval. " * 20!r},
            }}))
        """),
        encoding="utf-8",
    )
    (root / ".vaultragpreprocess.toml").write_text(
        "version = 2\n\n"
        '[[rule]]\npattern = "*.blob"\n'
        f"command = '''{_command(extractor)}'''\n"
        'target = "document"\nextractor_version = "1"\n'
        'on_error = "fail"\n',
        encoding="utf-8",
    )
    return source_path, phrase


def _wait_for_succeeded_job(port: int, job_id: str) -> None:
    deadline = time.monotonic() + 300.0
    last_job: dict[str, object] | None = None
    while time.monotonic() < deadline:
        response = _try_http_get_job(job_id, port, timeout=5.0)
        if response is not None and isinstance(response.get("job"), dict):
            last_job = cast("dict[str, object]", response["job"])
            state = last_job.get("state")
            if state == "succeeded":
                return
            if state in {"cancelled", "failed", "interrupted"}:
                pytest.fail(f"document index job terminated as {state}: {last_job}")
        time.sleep(0.1)
    pytest.fail(f"document index job did not succeed: {last_job}")


async def _exercise_document_tools(
    port: int,
    root: Path,
    source_path: str,
    phrase: str,
) -> None:
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

        tools_by_name = {tool.name: tool for tool in tools.tools}
        for tool_name in ("search_documents", "search_combined"):
            properties = tools_by_name[tool_name].inputSchema["properties"]
            assert "like_ids" not in properties
            assert "unlike_ids" not in properties
            assert "source_path" in properties

        for name in ("search_documents", "search_combined"):
            result = await asyncio.wait_for(
                session.call_tool(
                    name,
                    arguments={
                        "query": phrase,
                        "project_root": str(root),
                        "source_path": source_path,
                    },
                    read_timeout_seconds=timedelta(seconds=60),
                ),
                timeout=70,
            )
            assert result.isError is not True, (name, result)
            payload = cast("dict[str, Any]", result.structuredContent)
            results = cast("list[dict[str, Any]]", payload["results"])
            assert results, (name, payload)
            assert {item["path"] for item in results} == {source_path}

        for name, arguments in (
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
    (root / ".vault").mkdir(exist_ok=True)
    (root / ".vaultspec").mkdir(exist_ok=True)
    (root / ".vaultragpreprocess.toml").write_text(
        'version = 2\n[[rule]]\npattern = "*.blob"\ncommand = [\n',
        encoding="utf-8",
    )
    partial = _try_http_reindex(
        "combined",
        False,
        port,
        str(root),
        initiator_kind="mcp",
    )
    assert partial is not None
    assert partial["ok"] is False
    assert partial["partial"] is True, partial
    domains = cast("dict[str, dict[str, Any]]", partial["domains"])
    assert domains["vault"]["ok"] is True
    assert any(not domain["ok"] for domain in domains.values())
    _wait_for_succeeded_job(port, cast("str", domains["vault"]["job_id"]))

    source_path, phrase = _write_indexed_document_fixture(root)
    created = _try_http_reindex(
        "document",
        False,
        port,
        str(root),
        initiator_kind="mcp",
    )
    assert created is not None
    assert created["ok"] is True, created
    job_id = cast("str", created["job_id"])
    _wait_for_succeeded_job(port, job_id)

    for search_type in ("document", "combined"):
        response = _try_http_search(
            phrase,
            search_type,
            5,
            port,
            str(root),
            timeout=600.0,
            document_filters={"source_path": source_path},
        )
        assert response is not None
        assert response.get("ok", True) is True, response
        assert "error" not in response, response
        results = cast("list[dict[str, Any]]", response["results"])
        assert results
        assert {item["path"] for item in results} == {source_path}

    rejected_feedback = _try_http_search(
        phrase,
        "combined",
        5,
        port,
        str(root),
        like_ids=["unsupported-point"],
    )
    assert rejected_feedback is not None
    assert rejected_feedback["ok"] is False
    assert rejected_feedback["error"] == "unsupported_feedback_for_search_type"

    direct_rejection = _do_http_call(
        port,
        "/search",
        {
            "query": phrase,
            "type": "combined",
            "top_k": 5,
            "project_root": str(root),
            "like_ids": ["unsupported-point"],
        },
        timeout=30.0,
    )
    assert direct_rejection is not None
    assert direct_rejection["ok"] is False
    assert direct_rejection["error"] == "unsupported_feedback_for_search_type"

    asyncio.run(_exercise_document_tools(port, root, source_path, phrase))
