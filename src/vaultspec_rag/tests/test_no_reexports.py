"""Concrete production seams must have one direct import path.

An explicit ``__all__`` re-export is one way to leave a forwarding seam, but
Python also exposes every module-level import to ``from module import Name``.
The latter is the more dangerous form after a module split: it lets a consumer
keep importing a moved name from a concrete owner that merely needs it
internally. The direct-owner guard therefore follows every real import of the
split owners and requires the requested binding to be defined by that owner.

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

_LEGACY_SEAMS = frozenset(
    {
        "vaultspec_rag.storage_ops",
        "vaultspec_rag.store",
        "vaultspec_rag.watcher",
        "vaultspec_rag.indexer._run_ledger",
    }
)
_MOVED_OWNER_PREFIXES = (
    # ``job_manager`` is the canonical owner directory. Its concrete modules,
    # not the removed single-file seam, are what consumers must import.
    "vaultspec_rag.job_manager.",
    "vaultspec_rag.storage_",
    "vaultspec_rag.store_",
    "vaultspec_rag.watcher_",
    "vaultspec_rag.indexer._run_ledger_",
    # Config is split by ownership too: each consumer must request a symbol
    # from the direct module that defines it, never an incidental import.
    "vaultspec_rag.config.",
)


def _defined_names(node: ast.AST) -> set[str]:
    """Return names a single top-level AST node defines."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return {node.name}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    if isinstance(node, ast.Assign):
        return {target.id for target in node.targets if isinstance(target, ast.Name)}
    if isinstance(node, ast.TypeAlias):
        return {node.name.id}
    return set()


def _imported_names(node: ast.AST) -> set[str]:
    """Return bindings a single import node introduces."""
    if isinstance(node, ast.ImportFrom):
        return {alias.asname or alias.name for alias in node.names}
    if isinstance(node, ast.Import):
        return {alias.asname or alias.name.split(".")[0] for alias in node.names}
    return set()


def _explicit_exports(node: ast.AST) -> list[str]:
    """Return string literals from one ``__all__`` assignment."""
    if not (
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
        and isinstance(node.value, ast.List | ast.Tuple)
    ):
        return []
    return [
        element.value
        for element in node.value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]


def _reexported_names(path: Path) -> list[str]:
    """Return names in this module's ``__all__`` that it imports but never defines."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = tree.body
    defined: set[str] = set()
    imported: set[str] = set()
    exported: list[str] = []
    for node in nodes:
        defined.update(_defined_names(node))
        imported.update(_imported_names(node))
        exported.extend(_explicit_exports(node))
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


def _module_name(path: Path) -> str:
    """Return the importable package name for one source path."""
    parts = list(path.relative_to(_PACKAGE_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("vaultspec_rag", *parts))


def _source_modules() -> dict[str, Path]:
    """Return every package source, including tests that import split owners."""
    return {
        _module_name(path): path
        for path in sorted(_PACKAGE_ROOT.rglob("*.py"))
    }


def _module_bound_names(nodes: list[ast.stmt]) -> set[str]:
    """Return bindings made at module scope, including conditional type aliases."""
    bound: set[str] = set()
    for node in nodes:
        bound.update(_defined_names(node))
        if isinstance(node, ast.If):
            bound.update(_module_bound_names(node.body))
            bound.update(_module_bound_names(node.orelse))
        elif isinstance(node, ast.Try):
            bound.update(_module_bound_names(node.body))
            bound.update(_module_bound_names(node.orelse))
            bound.update(_module_bound_names(node.finalbody))
            for handler in node.handlers:
                bound.update(_module_bound_names(handler.body))
    return bound


def _owner_bound_names(path: Path) -> set[str]:
    """Return names defined by a canonical owner, never its imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return _module_bound_names(tree.body)


def _relative_import_base(path: Path, level: int) -> tuple[str, ...] | None:
    """Resolve the package anchor used by one relative import."""
    package = list(path.relative_to(_PACKAGE_ROOT).parent.parts)
    if level - 1 > len(package):
        return None
    return "vaultspec_rag", *package[: len(package) - level + 1]


def _import_target(path: Path, node: ast.ImportFrom) -> str | None:
    """Resolve the absolute target module for an import with a module part."""
    if node.module is None:
        return None
    if node.level == 0:
        return node.module
    base = _relative_import_base(path, node.level)
    if base is None:
        return None
    return ".".join((*base, *node.module.split(".")))


def _is_moved_owner(module: str) -> bool:
    return module.startswith(_MOVED_OWNER_PREFIXES)


def _legacy_imports(path: Path, importer: str) -> list[str]:
    """Return direct imports that name a removed production seam."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(_legacy_module_imports(importer, node))
        elif isinstance(node, ast.ImportFrom):
            offenders.extend(_legacy_from_imports(path, importer, node))
    return offenders


def _legacy_seam_paths(module: str) -> tuple[Path, Path]:
    """Return both importable filesystem shapes for a removed module seam."""
    base = _PACKAGE_ROOT.joinpath(*module.split(".")[1:])
    return base.with_suffix(".py"), base


def _legacy_module_imports(importer: str, node: ast.Import) -> list[str]:
    return [
        f"{importer}:{node.lineno} -> {alias.name}"
        for alias in node.names
        if alias.name in _LEGACY_SEAMS
    ]


def _legacy_from_imports(
    path: Path,
    importer: str,
    node: ast.ImportFrom,
) -> list[str]:
    """Return removed seams imported directly or through their parent package."""
    target = _import_target(path, node)
    if target in _LEGACY_SEAMS:
        return [f"{importer}:{node.lineno} -> {target}"]
    if node.module is not None:
        assert target is not None
        candidates = (f"{target}.{alias.name}" for alias in node.names)
    else:
        base = _relative_import_base(path, node.level)
        if base is None:
            return []
        candidates = (".".join((*base, alias.name)) for alias in node.names)
    return [
        f"{importer}:{node.lineno} -> {candidate}"
        for candidate in candidates
        if candidate in _LEGACY_SEAMS
    ]


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


def test_known_facade_only_shrinks() -> None:
    # The ratchet's teeth. If a listed module gained pass-throughs the campaign
    # is going backwards; if it lost some, the entry is stale and the next
    # cleanup would silently have room to regress.
    for module, expected in _KNOWN_FACADES.items():
        path = _PACKAGE_ROOT / module
        actual = len(_reexported_names(path))
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


def test_moved_seams_are_deleted_and_have_no_direct_importers() -> None:
    """A split is complete only when no source still names its old module."""
    modules = _source_modules()
    retained = sorted(
        f"{module} ({path})"
        for module in _LEGACY_SEAMS
        for path in _legacy_seam_paths(module)
        if path.exists()
    )
    assert not retained, f"removed seam(s) still exist: {retained}"

    offenders = [
        offender
        for importer, path in modules.items()
        for offender in _legacy_imports(path, importer)
    ]
    assert not offenders, (
        f"direct imports of removed split seam(s): {offenders}. "
        "Import the concrete owner instead of restoring a forwarding module."
    )


def test_moved_owner_imports_request_owner_defined_bindings() -> None:
    """Consumers cannot reach an owner's incidental default-import surface."""
    modules = _source_modules()
    owner_names = {
        module: _owner_bound_names(path)
        for module, path in modules.items()
        if _is_moved_owner(module)
    }
    offenders: list[str] = []
    for importer, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            target = _import_target(path, node)
            if target not in owner_names:
                continue
            for alias in node.names:
                if alias.name == "*" or alias.name not in owner_names[target]:
                    offenders.append(
                        f"{importer}:{node.lineno} imports {alias.name!r} "
                        f"from {target}"
                    )
    assert not offenders, (
        f"default-import re-export(s) from moved owner(s): {offenders}. "
        "Import each name from the module that defines it."
    )
