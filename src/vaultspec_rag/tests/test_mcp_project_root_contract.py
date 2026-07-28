"""Guard: the MCP tool schema and the daemon's routes agree on ``project_root``.

Every search, retrieval, index-refresh and clean tool advertises
``project_root`` as optional. The daemon's routes require it and always will -
the service is machine-global and multi-root, so a server-side default would
resolve one root's query against another root's index. The optionality is
therefore a promise the *adapter* keeps, and the only way to keep it is to
resolve a real root before dispatch.

Both halves of that contract are exercised against real code here: the
adapter's resolver runs against real directories, and its output is handed to
the server's own validator (``_resolve_root`` in HTTP mode) - the exact function
that produced the 400. A resolver that regresses to the empty string fails on
``ProjectRootRequiredError``, which is what the bug was.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ..config._types import EnvVar
from ..mcp._roots import _resolve_project_root

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

#: The tools and resources whose advertised schema makes ``project_root``
#: optional. Named explicitly so a tool added without a resolved root is a
#: visible omission here rather than a silently uncovered 400.
_OPTIONAL_ROOT_TOOLS = (
    "search_vault",
    "search_codebase",
    "search_documents",
    "search_combined",
    "get_code_file",
    "reindex_vault",
    "reindex_codebase",
    "reindex_documents",
    "reindex_all",
    "get_index_status",
    "clean_documents",
    "clean_all",
)


def _make_workspace(base: Path) -> Path:
    """Create a minimal enrolled workspace the resolver accepts."""
    (base / ".vault").mkdir(parents=True, exist_ok=True)
    (base / ".vaultspec").mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture
def unset_root_env() -> Iterator[None]:
    """Run with ``VAULTSPEC_RAG_ROOT`` absent, restoring it afterwards."""
    previous = os.environ.pop(EnvVar.RAG_ROOT, None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ[EnvVar.RAG_ROOT] = previous


@pytest.fixture
def http_mode_server() -> Iterator[None]:
    """Put the server module in HTTP mode, the mode that rejects a blank root."""
    import vaultspec_rag.server as server_module

    previous = server_module._http_mode
    server_module._http_mode = True
    try:
        yield
    finally:
        server_module._http_mode = previous


@pytest.mark.usefixtures("http_mode_server")
def test_resolved_root_satisfies_the_route_that_returned_the_400(
    tmp_path: Path,
) -> None:
    """The adapter's resolved root is accepted by the server's own validator.

    This is the contract in one assertion: what the MCP now sends when the
    caller omits ``project_root`` is what the route requires. The empty string
    the adapter used to send raises ``ProjectRootRequiredError`` here, so a
    regression lands on that exception rather than on a vague failure.
    """
    from ..server._utils import _resolve_root

    root = _make_workspace(tmp_path / "project")
    resolved = _resolve_project_root(str(root))

    assert resolved
    assert Path(resolved).is_absolute()
    assert _resolve_root(resolved) == root.resolve()


@pytest.mark.usefixtures("http_mode_server")
def test_blank_root_is_what_the_route_rejects() -> None:
    """Pin the rejected value, so the test above is known to be load-bearing.

    Without this, a resolver returning the empty string could only be caught by
    reading the other test's failure mode. Here the rejection is asserted
    directly, on the exact exception type the route maps to its 400.
    """
    from ..server._utils import ProjectRootRequiredError, _resolve_root

    with pytest.raises(ProjectRootRequiredError):
        _resolve_root("")


@pytest.mark.usefixtures("unset_root_env")
def test_omitted_root_resolves_the_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no argument and no env var, the process's own project is addressed."""
    root = _make_workspace(tmp_path / "cwd-project")
    monkeypatch.chdir(root)

    assert Path(_resolve_project_root(None)) == root.resolve()


def test_env_named_root_wins_over_the_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host that sets ``VAULTSPEC_RAG_ROOT`` has named the root deliberately."""
    named = _make_workspace(tmp_path / "named")
    elsewhere = _make_workspace(tmp_path / "elsewhere")
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv(EnvVar.RAG_ROOT, str(named))

    assert Path(_resolve_project_root(None)) == named.resolve()


def test_explicit_argument_wins_over_the_env_named_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An argument is the caller's own choice and outranks the launch env."""
    named = _make_workspace(tmp_path / "named")
    asked = _make_workspace(tmp_path / "asked")
    monkeypatch.setenv(EnvVar.RAG_ROOT, str(named))

    assert Path(_resolve_project_root(str(asked))) == asked.resolve()


@pytest.mark.usefixtures("unset_root_env")
def test_blank_argument_falls_through_rather_than_reaching_the_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A whitespace argument is treated as absent, never forwarded verbatim.

    A caller that sends ``""`` - which the advertised schema permits, since the
    parameter is a nullable string - must get the same resolution as one that
    omits the field, not the 400.
    """
    root = _make_workspace(tmp_path / "cwd-project")
    monkeypatch.chdir(root)

    assert Path(_resolve_project_root("")) == root.resolve()
    assert Path(_resolve_project_root("   ")) == root.resolve()


def test_unresolvable_root_names_itself_and_the_remediation(tmp_path: Path) -> None:
    """A directory that is not a workspace fails on the named error, with a fix.

    The assertion is on the structured error code, not on prose shared with the
    daemon's own failures: an unenrolled directory and a stopped service must
    not be diagnosed by the same string.
    """
    bare = tmp_path / "not-a-project"
    bare.mkdir()

    with pytest.raises(RuntimeError) as exc_info:
        _resolve_project_root(str(bare))

    message = str(exc_info.value)
    assert message.startswith("project_root_unresolved:")
    assert "vaultspec-rag install" in message


def test_no_mcp_call_site_forwards_a_blank_project_root() -> None:
    """No module on the MCP surface may hand the daemon an unfillable root.

    The bug was a literal ``project_root or ""`` at every call site: an
    optionality advertised to clients and refused by the service. A source scan
    is the assertion that fits, because the regression is textual - one call
    site reverting reintroduces exactly one 400 that no aggregate behavioural
    test would attribute.
    """
    package = Path(__file__).resolve().parent.parent / "mcp"
    offenders = [
        f"{module.name}:{number}: {line.strip()}"
        for module in sorted(package.glob("*.py"))
        for number, line in enumerate(
            module.read_text(encoding="utf-8").splitlines(), start=1
        )
        if 'project_root or ""' in line or "project_root or ''" in line
    ]

    assert offenders == []


def test_every_optional_root_tool_is_registered_under_that_name() -> None:
    """The named tool set matches the surface, so the list cannot go stale.

    ``_OPTIONAL_ROOT_TOOLS`` is the inventory the coverage claim rests on. If a
    tool is renamed or removed and the list is not updated, the claim silently
    narrows; asserting the set membership keeps the inventory honest.
    """
    from ..mcp import _tools

    for name in _OPTIONAL_ROOT_TOOLS:
        tool = getattr(_tools, name, None)
        assert tool is not None, f"{name} is not exported by vaultspec_rag.mcp._tools"


@pytest.mark.parametrize("name", _OPTIONAL_ROOT_TOOLS)
def test_optional_root_tool_still_declares_the_parameter(name: str) -> None:
    """Each tool keeps ``project_root`` optional - the advertised half.

    Read off the real function signature, so removing the parameter (or making
    it required) is caught here rather than by a client discovering the schema
    changed under it.
    """
    import inspect

    from ..mcp import _tools

    tool = getattr(_tools, name)
    # The @mcp.tool() decorator returns the function unchanged, so the module
    # attribute is the coroutine function that carries the schema.
    signature = inspect.signature(tool)

    assert "project_root" in signature.parameters, name
    assert signature.parameters["project_root"].default is None, name
