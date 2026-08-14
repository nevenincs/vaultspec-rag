"""Real MCP-session coverage for document-domain adapters."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import textwrap
import time
from typing import TYPE_CHECKING, Any, cast

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ...serviceclient._search_transport import try_http_search
from ...serviceclient._transport import (
    _do_http_call,
    _try_http_get_job,
    _try_http_reindex,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.types import CallToolResult, Tool

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
        _assert_document_tool_catalog(tools.tools)
        await _assert_mcp_searches(session, root, source_path, phrase)
        await _assert_mcp_read_tools(session, root)
        await _assert_empty_document_status(session, root)
        await _request_mcp_reindexes(session, root)


def _assert_document_tool_catalog(tools: list[Tool]) -> None:
    names = {tool.name for tool in tools}
    assert {
        "search_documents",
        "search_combined",
        "reindex_documents",
        "reindex_all",
        "clean_documents",
        "clean_all",
        "get_index_status",
    } <= names
    tools_by_name = {tool.name: tool for tool in tools}
    for tool_name in ("search_documents", "search_combined"):
        properties = tools_by_name[tool_name].input_schema["properties"]
        assert "like_ids" not in properties
        assert "unlike_ids" not in properties
        assert "source_path" in properties


async def _call_mcp_tool(
    session: ClientSession, name: str, arguments: dict[str, Any]
) -> CallToolResult:
    result = await asyncio.wait_for(
        session.call_tool(name, arguments=arguments, read_timeout_seconds=60),
        timeout=70,
    )
    assert result.is_error is not True, (name, result)
    return result


async def _assert_mcp_searches(
    session: ClientSession, root: Path, source_path: str, phrase: str
) -> None:
    for name in ("search_documents", "search_combined"):
        result = await _call_mcp_tool(
            session,
            name,
            {
                "query": phrase,
                "project_root": str(root),
                "source_path": source_path,
            },
        )
        payload = cast("dict[str, object]", result.structured_content)
        results = cast("list[dict[str, object]]", payload["results"])
        assert results, (name, payload)
        assert {item["path"] for item in results} == {source_path}


async def _assert_mcp_read_tools(session: ClientSession, root: Path) -> None:
    for name in ("clean_documents", "clean_all", "get_index_status"):
        result = await _call_mcp_tool(session, name, {"project_root": str(root)})
        assert isinstance(result.structured_content, dict), (name, result)


async def _assert_empty_document_status(session: ClientSession, root: Path) -> None:
    result = await _call_mcp_tool(
        session, "get_index_status", {"project_root": str(root)}
    )
    index = cast(
        "dict[str, object]",
        cast("dict[str, object]", result.structured_content)["index"],
    )
    assert index["document_chunks"] == 0
    support_profile = cast("dict[str, object]", index["support_profile"])
    assert set(cast("list[object]", support_profile["domains"])) == {
        "code",
        "document",
    }


async def _request_mcp_reindexes(session: ClientSession, root: Path) -> None:
    for name in ("reindex_documents", "reindex_all"):
        result = await _call_mcp_tool(session, name, {"project_root": str(root)})
        assert isinstance(result.structured_content, dict), (name, result)


def _assert_partial_reindex(partial: dict[str, object], port: int) -> None:
    assert partial["ok"] is False
    assert partial["partial"] is True, partial
    domains = cast("dict[str, dict[str, object]]", partial["domains"])
    assert domains["vault"]["ok"] is True
    assert any(not domain["ok"] for domain in domains.values())
    _wait_for_succeeded_job(port, cast("str", domains["vault"]["job_id"]))


def _assert_service_searches(
    port: int, root: Path, source_path: str, phrase: str
) -> None:
    for search_type in ("document", "combined"):
        response = try_http_search(
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
        results = cast("list[dict[str, object]]", response["results"])
        assert results
        assert {item["path"] for item in results} == {source_path}


def _assert_unsupported_feedback_is_rejected(
    port: int, root: Path, phrase: str
) -> None:
    rejected_feedback = try_http_search(
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
    _assert_partial_reindex(partial, port)

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

    _assert_service_searches(port, root, source_path, phrase)
    _assert_unsupported_feedback_is_rejected(port, root, phrase)

    asyncio.run(_exercise_document_tools(port, root, source_path, phrase))
