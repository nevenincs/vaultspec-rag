"""The actionlint provisioner imports nothing this repository owns.

``dev/actionlint.py`` runs before the project environment exists, so it states
what it needs itself: a constant it defines is defined here too, and replacing
its definition with an import reads as removing a duplicate. It is not.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: Repository root: this file is `<root>/dev/guards/<name>.py`.
ROOT = Path(__file__).resolve().parents[2]

#: The files that must stand alone.
DEPLOYED = ("dev/actionlint.py",)


def _owned_here(module: str) -> bool:
    """Whether *module* is a relative import or a package of this repository."""
    top = module.split(".")[0]
    return not top or any(
        candidate.exists()
        for candidate in (ROOT / top, ROOT / f"{top}.py", ROOT / "src" / top)
    )


def _imported(tree: ast.AST) -> list[tuple[int, str]]:
    """Return ``(line, module)`` for every module *tree* imports, anywhere."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append((node.lineno, "." * node.level + (node.module or "")))
    return found


@pytest.mark.parametrize("relative", DEPLOYED)
def test_a_deployed_copy_imports_nothing_this_repository_owns(relative: str) -> None:
    """No import in a deployed copy is relative or names a package kept here.

    Mutation proof: replacing the exit codes ``dev/actionlint.py`` defines
    with ``from dev.exit_codes import OK, TOOL_MISSING`` made this fail naming
    that line and module; restoring the file made it pass.
    """
    path = ROOT / relative
    imported = _imported(ast.parse(path.read_text(encoding="utf-8")))
    assert imported, f"{relative} imports nothing; this guard checks nothing"
    foreign = [
        f"{relative}:{line} imports {module}"
        for line, module in imported
        if _owned_here(module)
    ]
    assert not foreign, (
        "this file runs before the project environment exists, so it imports "
        "nothing this repository owns:\n" + "\n".join(foreign)
    )
