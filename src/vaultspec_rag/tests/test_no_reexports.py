"""A module must not export a name it does not define.

The re-export signature is a name in ``__all__`` that the module IMPORTS but
never DEFINES. It reads as an abstraction and is dead weight: it hides the real
owner, gives one symbol two import paths that drift apart, and survives every
later refactor because nothing points at it as the thing to delete.

``cli/_service_lifecycle.py`` was the worst of them - 24 pass-through names
whose own comment admitted they existed so "tests and ``cli.__init__`` continue
to import from" it. A symbol kept alive for tests proves nothing about
production, and two paths to one function is how a caller ends up patching the
copy the code no longer resolves.

Package ``__init__.py`` files are exempt: a package's public surface is a
deliberate facade, and re-exporting through it is the language's own idiom
rather than a hidden second path.

``_KNOWN_FACADES`` is a RATCHET, not a permission list. It is now EMPTY: every
non-``__init__`` module exports only what it defines. It stays in place as the
mechanism rather than the exemption - if a cleanup ever has to land in stages,
an entry records the interim count and the test fails when that count grows.
Adding an entry to make this test pass, rather than to stage a cleanup already
underway, defeats its only purpose.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from .. import _process_probe

pytestmark = [pytest.mark.unit]

_PACKAGE_ROOT = Path(_process_probe.__file__).parent

#: Modules permitted an interim pass-through count while a staged cleanup is in
#: flight. Empty, and meant to stay that way: shrink entries, never grow them.
_KNOWN_FACADES: dict[str, int] = {}


def _reexported_names(path: Path) -> list[str]:
    """Return names in this module's ``__all__`` that it imports but never defines."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined: set[str] = set()
    imported: set[str] = set()
    exported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                defined.add(target.id)
                if target.id == "__all__" and isinstance(
                    node.value, ast.List | ast.Tuple
                ):
                    exported = [
                        element.value
                        for element in node.value.elts
                        if isinstance(element, ast.Constant)
                        and isinstance(element.value, str)
                    ]
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(
                alias.asname or alias.name.split(".")[0] for alias in node.names
            )
    return sorted(set(exported) & imported - defined)


def _audited_modules() -> list[Path]:
    """Production modules that are not package facades."""
    return [
        path
        for path in sorted(_PACKAGE_ROOT.rglob("*.py"))
        if "tests" not in path.parts and path.name != "__init__.py"
    ]


def _key(path: Path) -> str:
    return path.relative_to(_PACKAGE_ROOT).as_posix()


def test_no_new_module_re_exports() -> None:
    offenders = {
        _key(path): names
        for path in _audited_modules()
        if (names := _reexported_names(path)) and _key(path) not in _KNOWN_FACADES
    }
    assert not offenders, (
        f"new re-export(s): {offenders}. "
        "Export only what the module defines; point callers at the owning "
        "module instead of adding a pass-through."
    )


@pytest.mark.parametrize("module", sorted(_KNOWN_FACADES))
def test_known_facade_only_shrinks(module: str) -> None:
    # The ratchet's teeth. If a listed module gained pass-throughs the campaign
    # is going backwards; if it lost some, the entry is stale and the next
    # cleanup would silently have room to regress.
    path = _PACKAGE_ROOT / module
    actual = len(_reexported_names(path))
    expected = _KNOWN_FACADES[module]
    assert actual <= expected, (
        f"{module} re-exports {actual} names, up from {expected}: the "
        "de-duplication campaign must not go backwards"
    )
    assert actual == expected, (
        f"{module} now re-exports {actual}, down from {expected}. Good - "
        f"update _KNOWN_FACADES to {actual} (or drop the entry at 0) so the "
        "ratchet holds the new ground."
    )


def test_ratchet_names_only_modules_that_exist() -> None:
    known = {_key(path) for path in _audited_modules()}
    stale = sorted(set(_KNOWN_FACADES) - known)
    assert not stale, f"ratchet names modules that no longer exist: {stale}"
