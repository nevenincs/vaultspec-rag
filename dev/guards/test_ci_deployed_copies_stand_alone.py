"""The two deployed CI checkers import nothing this repository owns.

``dev/ci_contract.py`` and ``dev/actionlint.py`` are copies. Their source is
another repository, which writes them here and compares what this repository's
default branch carries against it; a copy that differs is reported as a fork.

Pointing one of them at a module of this repository is such a difference, and
the likeliest one: a constant they define is defined here too, and replacing
the copy's definition with an import reads as removing a duplicate. It is not.
The copy has to mean the same in every repository that carries it, so it
states what it needs itself and reaches for nothing this repository owns.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: Repository root: this file is `<root>/dev/guards/<name>.py`.
ROOT = Path(__file__).resolve().parents[2]

#: The files another repository writes here.
DEPLOYED = ("dev/ci_contract.py", "dev/actionlint.py")


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
    that line and module, and a ``from . import exit_codes`` in
    ``dev/ci_contract.py`` made it fail naming that line; restoring each file
    made it pass.
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
        "a deployed copy must mean the same in every repository that carries "
        "it, so it imports nothing this repository owns:\n" + "\n".join(foreign)
    )
