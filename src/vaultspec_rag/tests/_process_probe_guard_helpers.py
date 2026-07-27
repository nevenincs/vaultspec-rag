"""Concrete source-scanning helpers for canonical ownership guard tests."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

from .. import _process_probe

if TYPE_CHECKING:
    from collections.abc import Callable

_PACKAGE_ROOT = Path(_process_probe.__file__).parent
_CANONICAL = Path(_process_probe.__file__).name

#: Modules allowed to call a raw process primitive, each for a reason the
#: canonical module does not serve. Anything not listed here must import from
#: ``_process_probe`` instead of re-deriving the primitive.
_ALLOWED: dict[str, str] = {
    # Self-memory sampling. `psutil.Process(os.getpid()).memory_info()` asks
    # about THIS process's RSS, which is a memory concern, not process
    # identity: no pid to confuse, no liveness to get wrong.
    "memory_probe.py": "samples this process's own RSS",
    "jobs.py": "samples this process's own RSS",
    # Holds SYNCHRONIZE handles open to WAIT on ancestor death, and walks a
    # toolhelp snapshot to find them. That is handle lifetime management, not
    # a point-in-time probe, and it needs its own `use_last_error` WinDLL.
    "_stdio_lifetime.py": "holds waitable ancestor handles",
    # Windows Job Object management for the managed child; kernel32 here is
    # about job assignment, not about inspecting a pid.
    "_supervise.py": "manages a Job Object",
}


def _production_sources() -> list[Path]:
    """Every production module: the package minus tests and the canonical home."""
    return [
        path
        for path in _PACKAGE_ROOT.rglob("*.py")
        if "tests" not in path.parts and path.name != _CANONICAL
    ]


def every_production_file() -> list[Path]:
    """Every production module, including the canonical home.

    ``_production_sources`` omits the canonical home, which is right for a
    "does anyone else do this" scan and wrong for building an index of who
    reads what: a file left out of that index reads as nobody.
    """
    return [path for path in _PACKAGE_ROOT.rglob("*.py") if "tests" not in path.parts]


def _parsed_source(path: Path) -> ast.Module | None:
    """Parse *path*, leaving syntax failures to the dedicated parse checks."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - parsed elsewhere
        return None


def parsed_production_sources(
    paths: list[Path], excluded_names: set[str]
) -> list[tuple[Path, ast.Module]]:
    """Return parsed production files outside one or more canonical owners."""
    parsed: list[tuple[Path, ast.Module]] = []
    for path in paths:
        if path.name in excluded_names:
            continue
        tree = _parsed_source(path)
        if tree is not None:
            parsed.append((path, tree))
    return parsed


def function_nodes(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return every function node in a module."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def string_literals(node: ast.Tuple | ast.List | ast.Set) -> set[str]:
    """Return the string members of one collection literal."""
    return {
        element.value
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }


def module_name(path: Path) -> str:
    """Return the dotted module name for *path*, dropping a trailing package part."""
    parts = list(path.relative_to(_PACKAGE_ROOT).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([_PACKAGE_ROOT.name, *parts])


def absolute_import(node: ast.ImportFrom, module: str, is_package: bool) -> str:
    """Resolve a possibly-relative ``ImportFrom`` to an absolute module name."""
    base = node.module or ""
    if not node.level:
        return base
    parts = module.split(".")
    if not is_package:
        parts = parts[:-1]
    above = node.level - 1
    if above:
        parts = parts[:-above] if above <= len(parts) else []
    return ".".join([*parts, base]) if base else ".".join(parts)


def find_offenders(predicate: Callable[[ast.Call], bool]) -> list[str]:
    found: list[str] = []
    for path in _production_sources():
        if path.name in _ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and predicate(node):
                rel = path.relative_to(_PACKAGE_ROOT).as_posix()
                found.append(f"{rel}:{node.lineno}")
    return found


def is_attr_call(node: ast.Call, owner: str, attr: str) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == attr
        and isinstance(func.value, ast.Name)
        and func.value.id == owner
    )
