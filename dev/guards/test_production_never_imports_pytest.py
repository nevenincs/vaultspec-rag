"""The shipped package never learns that it is under test.

WHAT THIS CONFINES. The root ``conftest.py`` substitutes ``os.fsync`` for the
whole session: atomicity comes from the exclusively-created temp file and the
rename, durability across power loss is asserted by no test in this suite, and
an fsync serialises at the device - so paying for it is the single biggest
reason a suite stops getting faster as workers are added.

That substitution is only safe while it stays on ONE side of the boundary. The
moment production can tell it is running under pytest, the pressure is to make
it behave differently there - a shorter timeout here, a skipped flush there -
and every such branch is a path the suite proves and the shipped wheel never
takes. The suppression is a property of the TEST HARNESS. It must never become
a property of the product.

TWO ASSERTIONS, BECAUSE ONE IS NOT ENOUGH. A source scan reads every module
including the ones no test imports, so a lazily-imported branch cannot hide
from it; a fresh interpreter proves the real import graph, so a re-export
reached through a chain of modules cannot hide either. Neither subsumes the
other: the scan cannot follow an alias, and the import proves nothing about a
module it never loads.
"""

from __future__ import annotations

import ast
import subprocess
import sys

import pytest

from dev.guards import _workflows as workflows

pytestmark = [pytest.mark.unit, pytest.mark.repo]

#: The shipped package.
PACKAGE = "src/vaultspec_rag"

#: The suite lives inside the package and is stripped from the wheel; it is
#: the one subtree that may import the test framework.
TESTS = "tests"

#: The name production may not reach.
FORBIDDEN = "pytest"


def _production_modules() -> list[str]:
    """Return every shipped module path, excluding the suite."""
    root = workflows.repository_root() / PACKAGE
    return [
        path.relative_to(workflows.repository_root()).as_posix()
        for path in sorted(root.rglob("*.py"))
        if TESTS not in path.relative_to(root).parts
    ]


def test_no_shipped_module_imports_the_test_framework() -> None:
    """No module in the wheel names ``pytest`` in an import, at any depth.

    Guard assertion: parsed as a syntax tree rather than grepped, so a
    function-local import on a cold branch - the shape that passes every
    linter and only surfaces when that branch runs - is caught too.
    """
    root = workflows.repository_root()
    findings: list[str] = []
    for relative in _production_modules():
        tree = ast.parse((root / relative).read_text(encoding="utf-8"), relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(
                name == FORBIDDEN or name.startswith(f"{FORBIDDEN}.") for name in names
            ):
                findings.append(f"{relative}:{node.lineno}")
    assert not findings, (
        f"A shipped module imports `{FORBIDDEN}`.\n"
        "The root conftest suppresses `os.fsync` for the whole session; that "
        "is a property of the harness and must never become one of the "
        "product. A module that can tell it is under test is a module that "
        "will eventually behave differently there, and the suite would then "
        "be proving a path the wheel never takes.\n\n" + "\n".join(findings)
    )


def test_importing_the_package_does_not_load_the_test_framework() -> None:
    """A fresh interpreter importing the package leaves ``pytest`` unloaded.

    Guard assertion: the source scan cannot follow a re-export chain, and an
    in-process check cannot either - this session already has the framework
    loaded, so ``sys.modules`` here proves nothing. Only a new interpreter
    can answer it.
    """
    probe = f"import sys; import vaultspec_rag; print({FORBIDDEN!r} in sys.modules)"
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        check=False,
        cwd=workflows.repository_root(),
        # Stated, for the reason the guard beside this one exists.
        encoding="utf-8",
        errors="replace",
    )
    assert completed.returncode == 0, (
        f"the probe interpreter failed: {completed.stderr.strip()[-500:]}"
    )
    assert completed.stdout.strip() == "False", (
        f"importing `vaultspec_rag` loads `{FORBIDDEN}`. Something in the "
        "shipped import graph reaches the test framework, so production can "
        "tell it is under test."
    )
