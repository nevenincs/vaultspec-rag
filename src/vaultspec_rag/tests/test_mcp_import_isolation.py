"""Guard: mcp/ package must not import server/, store, service, or registry.

The ``vaultspec_rag.mcp`` package is the pure MCP protocol adapter layer.  It
delegates all work to the running daemon via REST calls and must never import
server internals directly.  This test walks every ``.py`` file under ``mcp/``
and inspects the AST for forbidden imports — no runtime import is performed.

Covered patterns:
  absolute:  ``import vaultspec_rag.server``
             ``from vaultspec_rag[.]server import X``
             ``from vaultspec_rag import store``
  relative:  ``from ..server import X``
             ``from ..registry import X``   (any depth)
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# src/vaultspec_rag/tests/<this file>  ->  parents[2] is src/vaultspec_rag
_PKG_ROOT = Path(__file__).resolve().parents[1]
_MCP_DIR = _PKG_ROOT / "mcp"

# The top-level absolute package name.
_TOP_PKG = "vaultspec_rag"

# Sub-modules that the mcp/ layer must not reach into directly.
_FORBIDDEN_SUBMODULES = {"server", "store", "service", "registry"}


def _absolute_name_is_forbidden(name: str) -> bool:
    """Return True if an absolute dotted name touches a forbidden sub-module.

    Matches both ``vaultspec_rag.server`` and ``vaultspec_rag.server.foo``.
    Also matches ``vaultspec_rag.store``, ``vaultspec_rag.service``, and
    ``vaultspec_rag.registry``.
    """
    parts = name.split(".")
    if parts[0] != _TOP_PKG or len(parts) < 2:
        return False
    return parts[1] in _FORBIDDEN_SUBMODULES


def _relative_name_is_forbidden(node: ast.ImportFrom, file_pkg: str) -> bool:
    """Return True if a relative import from *node* resolves to a forbidden module.

    ``file_pkg`` is the dotted package path of the file being inspected
    (e.g. ``vaultspec_rag.mcp``).  A relative import ``from ..server import X``
    has ``level=2`` and ``module="server"``; we walk up ``level`` segments from
    ``file_pkg`` and then append the first segment of ``module`` to obtain the
    resolved sub-module name.
    """
    if node.level == 0 or node.module is None:
        return False
    pkg_parts = file_pkg.split(".")
    # Walk up `level` segments (each dot climbs one package level).
    climb = node.level
    if climb > len(pkg_parts):
        return False
    resolved_parts = pkg_parts[: len(pkg_parts) - climb]
    # Only the first segment of the relative module path matters for the
    # top-level sub-module check.
    first_segment = node.module.split(".")[0]
    resolved_parts.append(first_segment)
    # After resolving: e.g. ["vaultspec_rag", "server"]
    if len(resolved_parts) >= 2 and resolved_parts[0] == _TOP_PKG:
        return resolved_parts[1] in _FORBIDDEN_SUBMODULES
    return False


def _collect_mcp_py_files() -> list[Path]:
    return sorted(_MCP_DIR.glob("**/*.py"))


@pytest.mark.unit
@pytest.mark.parametrize("src_file", _collect_mcp_py_files(), ids=lambda p: p.name)
def test_mcp_file_does_not_import_server_internals(src_file: Path) -> None:
    """No file in mcp/ may import server/, store, service, or registry."""
    source = src_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(src_file))

    # Dotted package of the file being tested, e.g. "vaultspec_rag.mcp".
    rel = src_file.relative_to(_PKG_ROOT)
    file_pkg = ".".join([_TOP_PKG, *list(rel.parent.parts)])

    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _absolute_name_is_forbidden(alias.name):
                    violations.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            # Absolute import: ``from vaultspec_rag[.]server import X``
            if node.level == 0 and node.module is not None:
                if _absolute_name_is_forbidden(node.module):
                    names = ", ".join(a.name for a in node.names)
                    violations.append(
                        f"line {node.lineno}: from {node.module} import {names}"
                    )
            # Relative import: ``from ..server import X``
            elif node.level > 0 and _relative_name_is_forbidden(node, file_pkg):
                names = ", ".join(a.name for a in node.names)
                dots = "." * node.level
                mod = node.module or ""
                violations.append(
                    f"line {node.lineno}: from {dots}{mod} import {names}"
                )

    assert not violations, (
        f"{src_file.relative_to(_PKG_ROOT)} imports forbidden server internals:\n"
        + "\n".join(f"  {v}" for v in violations)
    )
