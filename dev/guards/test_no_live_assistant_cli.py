"""No test launches an installed coding-assistant CLI.

A test that shells out to ``claude``, ``codex`` or ``gemini`` asserts whatever
happens to be installed, logged in and on PATH for the account running it.
That is a property of a workstation, not of this package: the same commit
passes on one host and fails on a runner whose service account cannot see the
user's profile. What this package owns is the configuration it writes for
those tools, and that is asserted by reading the written files.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from dev.guards import _workflows as workflows

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: Executables whose behaviour belongs to another vendor's release.
ASSISTANT_CLIS = frozenset({"claude", "codex", "gemini"})

#: Calls that start a process or resolve an executable to start.
_LAUNCHERS = frozenset(
    {
        "run",
        "Popen",
        "call",
        "check_call",
        "check_output",
        "create_subprocess_exec",
        "which",
    }
)


def _launched_name(call: ast.Call) -> str | None:
    """Return the literal executable name *call* launches, if it names one."""
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name not in _LAUNCHERS or not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.List | ast.Tuple) and first.elts:
        first = first.elts[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _findings(source: str, label: str) -> list[str]:
    """Name every call in *source* that launches an assistant CLI."""
    return [
        f"{label}:{node.lineno}: launches {name!r}"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and (name := _launched_name(node)) in ASSISTANT_CLIS
    ]


def _test_modules() -> list[Path]:
    root = workflows.repository_root()
    return sorted(
        path
        for tree in ("src", "tools", "dev")
        for path in (root / tree).rglob("test_*.py")
        if "__pycache__" not in path.parts
    )


def test_no_test_launches_an_assistant_cli() -> None:
    """Every test module asserts written configuration, never a live CLI."""
    root = workflows.repository_root()
    modules = _test_modules()
    assert modules, "no test modules found; this guard is vacuous"
    findings = [
        finding
        for path in modules
        for finding in _findings(
            path.read_text(encoding="utf-8"), path.relative_to(root).as_posix()
        )
    ]
    assert findings == []


def test_a_live_assistant_call_is_named() -> None:
    """Mutation proof: the shapes the deleted host-CLI test used are caught.

    Restoring that test's ``subprocess.run(["claude", "mcp", "get", ...])``
    made ``test_no_test_launches_an_assistant_cli`` fail naming the call;
    deleting it again made it pass.
    """
    source = (
        "import shutil, subprocess\n"
        "subprocess.run(['claude', 'mcp', 'get', 'x'])\n"
        "shutil.which('codex')\n"
        "subprocess.run(['git', 'init'])\n"
        "providers = {'claude': 1}\n"
    )
    assert _findings(source, "t.py") == [
        "t.py:2: launches 'claude'",
        "t.py:3: launches 'codex'",
    ]
