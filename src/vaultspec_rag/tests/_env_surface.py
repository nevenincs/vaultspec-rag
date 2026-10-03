"""The environment-variable surface of this repository, read from its source.

``.env.example`` is held to the code in both directions, and both need the
same fact: which environment variables the code names. This module derives
that from the source instead of from a list somebody maintains, because a
maintained list is a third thing that drifts.

A variable counts as named by a file when any of these holds:

- the file holds a string that is, in full, a name in this project's own
  ``VAULTSPEC_`` namespace - wherever it appears, since a first-party name has
  no other reason to be spelled out;
- the file reads or writes the process environment under a key that can be
  read off the source: a literal, a module-level constant, or a member of the
  settings enum;
- the file binds a string to a module-level constant named as an
  environment-variable name (``*_ENV``, ``ENV_VAR``), which is how the harness
  carries a name to a reader that takes it as a parameter;
- a script names it on ``process.env`` or ``Bun.env``.

An access whose key cannot be read off the source is reported as a dynamic
site rather than guessed at. The guard that consumes this holds those sites to
an exact reviewed set, so a new one cannot name an undeclared variable
unnoticed.

Test modules are outside the surface: a test sets variables to drive the code
under test, and what it sets is evidence about the test.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Final

from dev.init.dotenv import TEMPLATE_ASSIGNMENT

from ..config._schema import ENV_OVERRIDE_MAP

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from ..config._types import EnvVar

# repo-root/src/vaultspec_rag/tests/<this file> -> parents[3] is the repo root.
REPO_ROOT: Final = Path(__file__).resolve().parents[3]
ENV_EXAMPLE: Final = REPO_ROOT / ".env.example"

#: Where the settings enum's members are spelled out. A name appearing here is
#: being declared, which is not evidence that anything reads it.
ENUM_MODULE: Final = "src/vaultspec_rag/config/_types.py"

#: Modules that classify or map enum members without consuming them.
DECLARATION_MODULES: Final = frozenset(
    {
        "src/vaultspec_rag/config/_registry.py",
        "src/vaultspec_rag/config/_schema.py",
    }
)

#: The package whose settings keys are consumed elsewhere. A key spelled as a
#: string inside it is the defaults table, not a consumer.
CONFIG_PACKAGE: Final = "src/vaultspec_rag/config/"

#: Where shipped code lives. A product variable is consumed only by something
#: under here; the harness reading it does not make it configure the product.
PRODUCT_ROOT: Final = "src/"

#: The settings key each override variable feeds.
_SETTING_KEYS: Final = {var: key for key, var in ENV_OVERRIDE_MAP.items()}

_SOURCE_ROOTS: Final = ("src/vaultspec_rag", "src/monitor", "dev", "tools", "scripts")
_ROOT_FILES: Final = ("conftest.py",)
_SCRIPT_SUFFIXES: Final = frozenset({".ts", ".tsx", ".mts", ".js", ".mjs"})
_SKIPPED_PARTS: Final = frozenset(
    {"tests", "guards", "node_modules", "dist", "__pycache__"}
)

_FIRST_PARTY: Final = re.compile(r"_?VAULTSPEC_[A-Z0-9_]*[A-Z0-9]")
_ENV_CONSTANT: Final = re.compile(r"(?:^|_)ENV(?:_VAR)?$")
_ENVIRON_METHODS: Final = frozenset({"get", "pop", "setdefault"})
_ENVIRON_FUNCTIONS: Final = frozenset({"getenv", "putenv", "unsetenv"})

_SCRIPT_MEMBER: Final = re.compile(r"\b(?:process|Bun)\.env\.([A-Za-z_$][\w$]*)")
_SCRIPT_LITERAL_KEY: Final = re.compile(
    r"\b(?:process|Bun)\.env\[\s*[\"'`]([^\"'`]+)[\"'`]\s*\]"
)
_SCRIPT_DYNAMIC_KEY: Final = re.compile(r"\b(?:process|Bun)\.env\[\s*[^\"'`\s\]]")
_SCRIPT_FIRST_PARTY: Final = re.compile(rf"(?<![A-Za-z0-9_]){_FIRST_PARTY.pattern}\b")


@dataclass
class Surface:
    """What the source names, and where.

    Attributes:
        names: Each environment variable mapped to the files that name it.
        reads: Each environment variable mapped to the files that read or
            write the process environment under it.
        carriers: Each environment-variable name mapped to the module-level
            constants that hold it.
        loads: Every identifier the source evaluates.
        dynamic_sites: ``path::function`` for every environment access whose
            key cannot be read off the source.
        members: Each settings-enum member name mapped to the files holding an
            ``EnvVar.<member>`` reference.
        attributes: Each attribute name mapped to the files that access it.
        strings: Each string constant mapped to the files that hold it.
    """

    names: dict[str, set[str]] = field(default_factory=dict)
    reads: dict[str, set[str]] = field(default_factory=dict)
    carriers: dict[str, set[str]] = field(default_factory=dict)
    loads: set[str] = field(default_factory=set)
    dynamic_sites: set[str] = field(default_factory=set)
    members: dict[str, set[str]] = field(default_factory=dict)
    attributes: dict[str, set[str]] = field(default_factory=dict)
    strings: dict[str, set[str]] = field(default_factory=dict)


def template_assignments() -> list[tuple[int, str, str]]:
    """Return ``(line number, name, value)`` for every assignment in the example."""
    found: list[tuple[int, str, str]] = []
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        match = TEMPLATE_ASSIGNMENT.match(line)
        if match is not None:
            found.append((number, match.group(1), match.group(2)))
    return found


def _is_test_module(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT)
    if not _SKIPPED_PARTS.isdisjoint(relative.parts):
        return True
    return path.name.startswith("test_") or ".test." in path.name


def _candidate_files() -> Iterator[Path]:
    for name in _ROOT_FILES:
        yield REPO_ROOT / name
    for root in _SOURCE_ROOTS:
        yield from (REPO_ROOT / root).rglob("*")


def _is_source(path: Path) -> bool:
    return path.suffix == ".py" or path.suffix in _SCRIPT_SUFFIXES


def _is_environ(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == "environ"
    return isinstance(node, ast.Name) and node.id == "environ"


def _mentions_enum(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Name) and child.id == "EnvVar" for child in ast.walk(node)
    )


def _resolve(
    node: ast.expr, bindings: dict[str, tuple[str, ...]]
) -> tuple[str, ...] | None:
    """Return the variables *node* denotes, or ``None`` when it cannot be read.

    A member of the settings enum denotes nothing here: the enum is the
    declaration, and it is held to the example on its own. A collection
    denotes what its elements do, so a key bound by iterating one resolves.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if _mentions_enum(node):
        return ()
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return _resolve_elements(node.elts, bindings)
    bound = node.value if isinstance(node, ast.Attribute) else node
    return bindings.get(bound.id) if isinstance(bound, ast.Name) else None


def _resolve_elements(
    elements: list[ast.expr], bindings: dict[str, tuple[str, ...]]
) -> tuple[str, ...] | None:
    """Return what every element denotes, or ``None`` when one cannot be read."""
    resolved: list[str] = []
    for element in elements:
        names = _resolve(element, bindings)
        if names is None:
            return None
        resolved.extend(names)
    return tuple(resolved)


def _module_constants(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    """Return the module-level names a key expression may resolve through.

    A name maps to the variables it holds, or to nothing when the settings
    enum - or the module it was imported from - already accounts for it.
    """
    constants: dict[str, tuple[str, ...]] = {}
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                bound = alias.asname or alias.name
                if _ENV_CONSTANT.search(bound):
                    constants[bound] = ()
            continue
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        else:
            continue
        if not isinstance(target, ast.Name):
            continue
        resolved = _resolve(value, constants)
        if resolved is not None:
            constants[target.id] = resolved
    return constants


def _access_key(node: ast.AST) -> ast.expr | None:
    """Return the key of an environment access, or ``None`` for anything else."""
    if isinstance(node, ast.Subscript):
        return node.slice if _is_environ(node.value) else None
    if isinstance(node, ast.Compare):
        membership = any(_is_environ(operand) for operand in node.comparators)
        return node.left if membership else None
    if isinstance(node, ast.Call) and node.args and _reaches_environ(node.func):
        return node.args[0]
    return None


def _reaches_environ(function: ast.expr) -> bool:
    """Return whether a called expression reads or writes the environment."""
    if isinstance(function, ast.Attribute):
        if function.attr in _ENVIRON_METHODS:
            return _is_environ(function.value)
        return function.attr in _ENVIRON_FUNCTIONS
    return isinstance(function, ast.Name) and function.id in _ENVIRON_FUNCTIONS


class _PythonScan(ast.NodeVisitor):
    """Collect one module's contribution to the surface."""

    def __init__(self, relative: str, tree: ast.Module, surface: Surface) -> None:
        self._relative = relative
        self._surface = surface
        self._bindings = _module_constants(tree)
        self._functions: list[str] = []
        for name, values in self._bindings.items():
            if _ENV_CONSTANT.search(name):
                for value in values:
                    self._name(value)
                    surface.carriers.setdefault(value, set()).add(name)

    def _name(self, variable: str) -> None:
        self._surface.names.setdefault(variable, set()).add(self._relative)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._surface.loads.add(node.id)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._functions.append(node.name)
        self.generic_visit(node)
        self._functions.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_iteration(
        self, node: ast.AST, pairs: list[tuple[ast.expr, ast.expr]]
    ) -> None:
        """Visit *node* with each loop variable bound to what it iterates."""
        outer = self._bindings
        self._bindings = dict(outer)
        for target, iterable in pairs:
            names = _resolve(iterable, self._bindings)
            if isinstance(target, ast.Name) and names is not None:
                self._bindings[target.id] = names
        self.generic_visit(node)
        self._bindings = outer

    def visit_For(self, node: ast.For) -> None:
        self._visit_iteration(node, [(node.target, node.iter)])

    def _visit_comprehension(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        pairs = [(generator.target, generator.iter) for generator in node.generators]
        self._visit_iteration(node, pairs)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self._surface.strings.setdefault(node.value, set()).add(self._relative)
            if _FIRST_PARTY.fullmatch(node.value):
                self._name(node.value)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._surface.attributes.setdefault(node.attr, set()).add(self._relative)
        if isinstance(node.value, ast.Name) and node.value.id == "EnvVar":
            self._surface.members.setdefault(node.attr, set()).add(self._relative)
        self.generic_visit(node)

    def generic_visit(self, node: ast.AST) -> None:
        key = _access_key(node)
        if key is not None:
            resolved = _resolve(key, self._bindings)
            if resolved is None:
                function = self._functions[-1] if self._functions else "<module>"
                self._surface.dynamic_sites.add(f"{self._relative}::{function}")
            else:
                for variable in resolved:
                    self._name(variable)
                    self._surface.reads.setdefault(variable, set()).add(self._relative)
        super().generic_visit(node)


def _scan_script(relative: str, text: str, surface: Surface) -> None:
    for pattern in (_SCRIPT_MEMBER, _SCRIPT_LITERAL_KEY):
        for match in pattern.finditer(text):
            surface.names.setdefault(match.group(1), set()).add(relative)
            surface.reads.setdefault(match.group(1), set()).add(relative)
    for match in _SCRIPT_FIRST_PARTY.finditer(text):
        surface.names.setdefault(match.group(0), set()).add(relative)
    if _SCRIPT_DYNAMIC_KEY.search(text):
        surface.dynamic_sites.add(f"{relative}::<script>")


def _scan(*, tests: bool) -> Surface:
    surface = Surface()
    for path in _candidate_files():
        if not path.is_file() or not _is_source(path):
            continue
        if _is_test_module(path) is not tests:
            continue
        if "node_modules" in path.parts or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            tree = ast.parse(text, filename=relative)
            _PythonScan(relative, tree, surface).visit(tree)
        else:
            _scan_script(relative, text, surface)
    return surface


@cache
def source_surface() -> Surface:
    """Return what the non-test source names."""
    return _scan(tests=False)


@cache
def suite_surface() -> Surface:
    """Return what the test modules name."""
    return _scan(tests=True)


def _in_product(files: Iterable[str]) -> bool:
    return any(name.startswith(PRODUCT_ROOT) for name in files)


def product_setting_is_consumed(var: EnvVar) -> bool:
    """Return whether shipped code acts on a variable this project defines.

    Declaring a member, classifying it, or mapping it onto a settings key is
    not consuming it. Something has to read the variable, or read the setting
    it overrides.

    Args:
        var: A member whose name this project owns.

    Returns:
        True when a shipped module references the member outside the modules
        that only declare it, reads the variable by name, or reads the setting
        it feeds.
    """
    source = source_surface()
    if _in_product(source.members.get(var.name, set()) - DECLARATION_MODULES):
        return True
    if _in_product(source.reads.get(var.value, set()) - {ENUM_MODULE}):
        return True
    key = _SETTING_KEYS.get(var)
    if key is None:
        return False
    if _in_product(source.attributes.get(key, ())):
        return True
    return _in_product(
        name
        for name in source.strings.get(key, ())
        if not name.startswith(CONFIG_PACKAGE)
    )


def borrowed_name_is_referenced(var: EnvVar) -> bool:
    """Return whether anything references a variable another project owns.

    Such a member exists to keep a third-party literal in one place, so it is
    earned by being named anywhere, the test harness included: the behaviour
    behind it is the owning library's whether this project reads it or not.

    Args:
        var: A member whose name another project owns.

    Returns:
        True when any module outside the declaring ones references it.
    """
    source = source_surface()
    if source.members.get(var.name, set()) - DECLARATION_MODULES:
        return True
    if source.reads.get(var.value, set()) - {ENUM_MODULE}:
        return True
    return bool(suite_surface().members.get(var.name))


def harness_name_is_read(variable: str) -> bool:
    """Return whether the source reads a variable the settings enum lacks.

    Args:
        variable: An environment variable named outside the settings enum.

    Returns:
        True when an environment access names it, or a constant holding it is
        evaluated somewhere - which is how a name reaches a reader that takes
        it as a parameter. A constant nothing evaluates is a declaration with
        no reader behind it.
    """
    source = source_surface()
    if source.reads.get(variable):
        return True
    return any(
        carrier in source.loads or carrier in source.attributes
        for carrier in source.carriers.get(variable, ())
    )
