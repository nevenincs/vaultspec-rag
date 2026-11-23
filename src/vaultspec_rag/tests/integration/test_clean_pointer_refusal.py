"""An unverifiable served pointer refuses a clean with one typed outcome.

A real server answers ``/clean`` over loopback against real local storage,
and the CLI runs ``clean`` in process exactly as an operator does. Each root
holds a served-collection pointer naming a collection the root does not own,
so which code collection it serves is not established and nothing may be
deleted.

MUTATION PROOF, each run in one uninterrupted sequence:

- Projecting the refusal in the clean route as the exception class name
  again (``type(exc).__name__``) fails
  ``test_the_clean_route_reports_the_typed_refusal`` on its ``error_kind``
  assertion.
- Removing the ``JobError`` branch from the CLI ``clean`` command lets the
  refusal escape with no envelope and fails
  ``test_cli_clean_projects_the_refusal_as_one_envelope`` on its one-line
  assertion (zero lines), and the human variant on its escaped-exception
  assertion.
- Restoring the MCP clean tool's collapse of a clean that failed in every
  domain into one ``clean_failed`` exception string fails
  ``test_the_mcp_clean_tool_returns_a_full_failure_unchanged`` on its
  ``is_error`` assertion.

Restoring each returns the module to green.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import TYPE_CHECKING, TextIO, cast

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typer.testing import CliRunner

from ..._store_models import served_code_pointer_path
from ...cli import app
from ...config._types import EnvVar
from ...service import ServiceRegistry
from ...serviceclient._transport import _try_http_clean
from .._scaffold import make_workspace
from .._state_fixtures import reset_registry
from ..conftest import managed_env
from ._service_jobs_support import _canonical_resilience_server

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from mcp.types import CallToolResult

runner = CliRunner()

pytestmark = [pytest.mark.unit]

_KIND = "served_pointer_unverifiable"


def _poisoned_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    make_workspace(root)
    pointer = served_code_pointer_path(root)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    # A vault collection name is never a code collection this root owns,
    # under either backend.
    pointer.write_text(json.dumps({"collection": "vault_docs"}), encoding="utf-8")
    return root


def _one_envelope(stdout: str) -> dict[str, object]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert len(lines) == 1, stdout
    envelope = json.loads(lines[0])
    assert isinstance(envelope, dict)
    return cast("dict[str, object]", envelope)


@pytest.fixture(name="local_backend")
def _local_backend() -> Iterator[None]:
    with managed_env(**{EnvVar.QDRANT_URL.value: ""}):
        reset_registry()
        try:
            yield
        finally:
            reset_registry()


@pytest.mark.usefixtures("local_backend")
def test_the_clean_route_reports_the_typed_refusal(tmp_path: Path) -> None:
    root = _poisoned_root(tmp_path)
    with _canonical_resilience_server(tmp_path) as (port, _token):
        result = _try_http_clean("code", port, str(root))

    assert result is not None
    assert result["ok"] is False, result
    assert result["partial"] is False
    domains = cast("dict[str, dict[str, object]]", result["domains"])
    code = domains["code"]
    assert code["ok"] is False
    assert code["cleared"] == []
    assert code["error_kind"] == _KIND, code
    assert str(served_code_pointer_path(root)) in str(code["detail"])
    assert "nothing was deleted" in str(code["remediation"])
    assert served_code_pointer_path(root).exists()


@pytest.mark.usefixtures("local_backend")
def test_cli_clean_projects_the_refusal_as_one_envelope(tmp_path: Path) -> None:
    root = _poisoned_root(tmp_path)
    result = runner.invoke(
        app, ["--target", str(root), "clean", "code", "--yes", "--json"]
    )

    assert result.exit_code == 1, result.output
    envelope = _one_envelope(result.stdout)
    assert envelope["ok"] is False
    assert envelope["command"] == "clean"
    assert envelope["error"] == _KIND
    assert str(served_code_pointer_path(root)) in str(envelope["message"])
    assert envelope["clean_type"] == "code"
    remediation = cast("list[str]", envelope["remediation"])
    assert len(remediation) == 1
    assert "nothing was deleted" in remediation[0]
    assert served_code_pointer_path(root).exists()


@pytest.mark.usefixtures("local_backend")
def test_cli_clean_projects_the_refusal_in_human_mode(tmp_path: Path) -> None:
    root = _poisoned_root(tmp_path)
    result = runner.invoke(app, ["--target", str(root), "clean", "code", "--yes"])

    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert f"Code: {_KIND}" in result.output
    assert "Next actions:" in result.output
    assert "nothing was deleted" in result.output
    assert "Traceback" not in result.output
    assert served_code_pointer_path(root).exists()


async def _mcp_clean(
    *, port: int, status_dir: Path, root: Path, tool_name: str
) -> CallToolResult:
    """Call one clean tool through an MCP process started as a host starts it."""
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
                arguments={"project_root": str(root)},
                read_timeout_seconds=60,
            ),
            timeout=70,
        )


@pytest.mark.usefixtures("local_backend")
def test_the_mcp_clean_tool_returns_a_full_failure_unchanged(tmp_path: Path) -> None:
    """Every domain's typed outcome reaches the agent, not one opaque string.

    The test holds a lease on the service's own registry, so the clean route
    refuses every domain and deletes nothing. The MCP tool must answer with
    the service's envelope, each domain keeping its kind, detail and
    remediation, exactly as the route returned them.
    """
    root = _poisoned_root(tmp_path)
    registry = ServiceRegistry()
    with (
        _canonical_resilience_server(tmp_path, registry=registry) as (port, _token),
        registry.lease(root),
    ):
        expected = _try_http_clean("combined", port, str(root))
        result = asyncio.run(
            _mcp_clean(
                port=port,
                status_dir=tmp_path / "resilience-status",
                root=root,
                tool_name="clean_all",
            )
        )

    assert expected is not None
    assert expected["ok"] is False
    assert expected["partial"] is False
    assert result.is_error is False, result
    structured = cast("dict[str, object]", result.structured_content)
    assert structured == expected
    domains = cast("dict[str, dict[str, object]]", structured["domains"])
    assert set(domains) == {"vault", "code", "document"}
    for outcome in domains.values():
        assert outcome["ok"] is False
        assert outcome["cleared"] == []
        assert outcome["error_kind"] == "ProjectBusyError"
        assert str(root) in str(outcome["detail"])
    assert served_code_pointer_path(root).exists()


@pytest.mark.usefixtures("local_backend")
def test_the_mcp_clean_tool_carries_the_typed_pointer_refusal(
    tmp_path: Path,
) -> None:
    """The unverifiable pointer reaches the agent with its kind and remedy."""
    root = _poisoned_root(tmp_path)
    with _canonical_resilience_server(tmp_path) as (port, _token):
        result = asyncio.run(
            _mcp_clean(
                port=port,
                status_dir=tmp_path / "resilience-status",
                root=root,
                tool_name="clean_all",
            )
        )

    assert result.is_error is False, result
    structured = cast("dict[str, object]", result.structured_content)
    code = cast("dict[str, dict[str, object]]", structured["domains"])["code"]
    assert code["ok"] is False
    assert code["error_kind"] == _KIND, code
    assert str(served_code_pointer_path(root)) in str(code["detail"])
    assert "nothing was deleted" in str(code["remediation"])
    assert served_code_pointer_path(root).exists()
