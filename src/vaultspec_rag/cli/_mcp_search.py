"""MCP HTTP client helpers for the CLI fast path.

Each ``_try_mcp_*`` helper talks to a running RAG service over the
streamable-HTTP MCP transport and discriminates "service unreachable"
(connection refused → ``None``) from "live but broken" (structured
error dict). :func:`_is_connection_refused` walks the exception chain
to make that call.
"""

from __future__ import annotations

from typing import Literal, cast

from ._core import logger


def _try_mcp_reindex(
    tool_name: str,
    clean: bool,
    port: int,
    project_root: str,
) -> dict[str, object] | None:
    """Reindex via a running MCP server over HTTP.

    Args:
        tool_name: MCP tool to call (``reindex_vault`` or
            ``reindex_codebase``).
        clean: Whether to drop and recreate the collection.
        port: TCP port of the running MCP server.
        project_root: Absolute path to the target project. The
            HTTP service is multi-tenant and has no default
            project, so every tool call must carry this value.

    Returns:
        Parsed JSON response dict on success, or None if the
        server is unavailable or an error occurs.

    """
    import asyncio

    async def _call() -> dict[str, object] | None:
        import json

        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import (
            streamable_http_client,
        )
        from mcp.types import TextContent

        # Trailing slash avoids a 307 redirect from the Starlette
        # Mount("/mcp") wrapping the inner app at "/".
        url = f"http://127.0.0.1:{port}/mcp/"
        async with (
            streamable_http_client(url) as (
                read,
                write,
                _,
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                tool_name,
                {"clean": clean, "project_root": project_root},
            )
            if result.content:
                first = result.content[0]
                if isinstance(first, TextContent):
                    return json.loads(first.text)
            return {}

    try:
        return asyncio.run(_call())
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug(
                "MCP reindex %s on port %s: connection refused (%s)",
                tool_name,
                port,
                exc,
            )
            return None
        return {
            "ok": False,
            "error": "mcp_call_failed",
            "message": (
                f"MCP reindex tool {tool_name!r} on port {port} failed: "
                f"{exc.__class__.__name__}: {exc}"
            ),
        }


def _is_connection_refused(exc: BaseException) -> bool:
    """Walk an exception chain looking for a connect-refused signal.

    Used by every ``_try_mcp_*`` helper to discriminate "service
    unreachable" (connection refused → caller treats as fast-path
    unavailable) from "tool error" (live service, broken tool → caller
    surfaces the structured error instead of silently relaning).
    """
    import errno

    refused_errnos = {
        errno.ECONNREFUSED,
        getattr(errno, "WSAECONNREFUSED", 10061),
    }
    httpx_refused_types: tuple[type[BaseException], ...]
    try:
        from httpx import ConnectError, ConnectTimeout, ReadError

        httpx_refused_types = (ConnectError, ConnectTimeout, ReadError)
    except ImportError:  # pragma: no cover - httpx is a hard dep but stay defensive
        httpx_refused_types = ()

    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ConnectionRefusedError):
            return True
        if (
            isinstance(current, OSError)
            and getattr(current, "errno", None) in refused_errnos
        ):
            return True
        if httpx_refused_types and isinstance(current, httpx_refused_types):
            return True
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None:
            stack.append(current.__context__)
        if isinstance(current, BaseExceptionGroup):
            stack.extend(current.exceptions)
    return False


def _try_mcp_admin(
    tool_name: str,
    args: dict[str, object],
    port: int | None,
) -> dict[str, object] | None:
    """Call an admin MCP tool on a running RAG service.

    Distinguishes "service unreachable" (connection refused → returns
    ``None``) from "tool error" (bad response, missing tool → returns
    the raw dict so the caller can render the structured error).

    Args:
        tool_name: Name of the admin/observability MCP tool to call
            (e.g. ``list_projects``, ``get_service_state``, ``get_logs``,
            ``get_jobs``, or a watcher-control tool).
        args: Keyword arguments forwarded to the tool.
        port: TCP port of the running MCP server.  If ``None``, the
            helper returns ``None`` immediately.

    Returns:
        Parsed response dict on success, the error dict if the tool
        returned one, or ``None`` when the service is unreachable.
    """
    if port is None:
        return None

    import asyncio

    async def _call() -> dict[str, object] | None:
        import json

        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from mcp.types import TextContent

        # Trailing slash avoids a 307 redirect from the Starlette
        # Mount("/mcp") wrapping the inner app at "/".
        url = f"http://127.0.0.1:{port}/mcp/"
        async with (
            streamable_http_client(url) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(tool_name, args)
            if result.content:
                first = result.content[0]
                if isinstance(first, TextContent):
                    return json.loads(first.text)
            return {}

    try:
        return asyncio.run(_call())
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug(
                "MCP admin call on port %s: connection refused (%s)",
                port,
                exc,
            )
            return None
        # Any other failure is a live-service-but-broken-tool case.
        logger.debug(
            "MCP admin call on port %s raised non-refused exception",
            port,
            exc_info=True,
        )
        return {}


def _try_mcp_search(
    query: str,
    search_type: str,
    top_k: int,
    port: int,
    project_root: str,
    *,
    timeout: float | None = None,
    language: str | None = None,
    path: str | None = None,
    node_type: str | None = None,
    function_name: str | None = None,
    class_name: str | None = None,
    doc_type: str | None = None,
    feature: str | None = None,
    date: str | None = None,
    tag: str | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    dedup_locales: bool = False,
    prefer: str | None = None,
) -> list[dict[str, object]] | dict[str, object] | None:
    """Search via a running MCP server over HTTP.

    Uses ``asyncio.run()`` which is safe here because Typer
    command handlers are always synchronous - there is no outer
    event loop to conflict with.

    Args:
        query: The search query text.
        search_type: One of ``vault``, ``code``, or ``all``.
        top_k: Maximum number of results to return.
        port: TCP port of the running MCP server.
        project_root: Absolute path to the target project. The
            HTTP service is multi-tenant and has no default
            project, so every tool call must carry this value.
        language: Code-search filter - programming language.
        path: Code-search filter - exact project-relative path.
        node_type: Code-search filter - AST node type.
        function_name: Code-search filter - function/method name.
        class_name: Code-search filter - class/struct name.
        doc_type: Vault-search filter - vault doc type.
        feature: Vault-search filter - feature tag.
        date: Vault-search filter - exact ISO date.
        tag: Vault-search filter - free-form tag.

    Returns:
        List of result dicts on success, a structured MCP error
        dict if the service rejected the call, or None if the
        server is unavailable or an unstructured transport error
        occurs.

    """
    import asyncio

    tool_map = {"vault": "search_vault", "code": "search_codebase"}
    tool_name = tool_map.get(search_type, "search_vault")

    from vaultspec_rag.search import (
        InvalidFilterForSearchTypeError,
        InvalidPreferValueError,
        validate_search_filters,
    )

    try:
        validate_search_filters(
            cast("Literal['vault', 'code']", search_type),
            language=language,
            path=path,
            node_type=node_type,
            function_name=function_name,
            class_name=class_name,
            doc_type=doc_type,
            feature=feature,
            date=date,
            tag=tag,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            dedup_locales=dedup_locales,
            prefer=prefer,
        )
    except InvalidFilterForSearchTypeError as exc:
        return {
            "ok": False,
            "error": "invalid_filter_for_search_type",
            "message": str(exc),
        }
    except InvalidPreferValueError as exc:
        return {
            "ok": False,
            "error": "invalid_prefer_value",
            "message": str(exc),
        }

    import os

    if timeout is None:
        env_timeout = os.environ.get("VAULTSPEC_RAG_SEARCH_TIMEOUT")
        if env_timeout:
            try:
                timeout = float(env_timeout)
            except ValueError:
                timeout = 10.0
        else:
            timeout = 10.0

    async def _call() -> list[dict[str, object]] | dict[str, object] | None:
        import asyncio
        import json

        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from mcp.types import TextContent

        # Trailing slash avoids a 307 redirect from the Starlette
        # Mount("/mcp") wrapping the inner app at "/".
        url = f"http://127.0.0.1:{port}/mcp/"
        payload: dict[str, object] = {
            "query": query,
            "top_k": top_k,
            "project_root": project_root,
        }
        if search_type == "code":
            code_filters = {
                "language": language,
                "path": path,
                "node_type": node_type,
                "function_name": function_name,
                "class_name": class_name,
            }
            for key, value in code_filters.items():
                if value is not None:
                    payload[key] = value
            if include_paths:
                payload["include_paths"] = list(include_paths)
            if exclude_paths:
                payload["exclude_paths"] = list(exclude_paths)
            if dedup_locales:
                payload["dedup_locales"] = True
            if prefer is not None:
                payload["prefer"] = prefer
        elif search_type == "vault":
            vault_filters = {
                "doc_type": doc_type,
                "feature": feature,
                "date": date,
                "tag": tag,
            }
            for key, value in vault_filters.items():
                if value is not None:
                    payload[key] = value

        async def _do_search():
            async with (
                streamable_http_client(url) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(
                    tool_name,
                    payload,
                )
                if result.content:
                    first = result.content[0]
                    if isinstance(first, TextContent):
                        data = json.loads(first.text)
                        if data.get("ok") is False:
                            return data
                        return data.get("results", [])
                return []

        return await asyncio.wait_for(_do_search(), timeout=timeout)

    try:
        return asyncio.run(_call())
    except TimeoutError:
        logger.debug(
            "MCP search %s on port %s timed out after %ss",
            tool_name,
            port,
            timeout,
        )
        return {
            "ok": False,
            "error": "mcp_search_timeout",
            "message": (
                f"MCP search tool {tool_name!r} on port {port} timed out after "
                f"the configured budget ({timeout}s)."
            ),
        }
    except Exception as exc:
        if _is_connection_refused(exc):
            logger.debug(
                "MCP search %s on port %s: connection refused (%s)",
                tool_name,
                port,
                exc,
            )
            return None
        # Live-but-broken: surface a structured error so the caller
        # does not silently relane to the unsafe in-process path.
        return {
            "ok": False,
            "error": "mcp_call_failed",
            "message": (
                f"MCP search tool {tool_name!r} on port {port} failed: "
                f"{exc.__class__.__name__}: {exc}"
            ),
        }
