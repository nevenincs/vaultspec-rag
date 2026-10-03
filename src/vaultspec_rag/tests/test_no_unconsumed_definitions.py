"""Guard test: production defines nothing that only tests, or nothing, uses.

A definition with no consumer outside the test tree is a claim the code does
not back. If nothing references it, it is dead. If only tests reference it,
the tests are exercising a path production does not run, and their passing
says nothing about the product - the definition belongs beside the tests, as
a fixture, or it and its tests go together.

The check is structural. A definition is consumed when non-test source loads
its name, reads it as an attribute, imports it, passes it as a keyword, or
spells it whole inside a string: a ``cast("...")``, a child-process script, a
dispatch or lazy-export table. Two things deliberately do not count. A name
in ``__all__`` is exported, not used. A name a package ``__init__`` imports
is re-exported, not used.

What the check cannot see is dispatch by a framework that never spells the
name: a decorated command or validator, a visitor or handler method named by
convention. Those are skipped by shape rather than waived by name, so the
skip cannot be used to shelter an ordinary function.

Both directions were exercised. A function nothing calls was appended to a
production module and this test, run alone, failed naming it; it was removed
and the test passed. One sequence, nothing left mutated.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from functools import cache
from typing import TYPE_CHECKING, Final

import pytest

from ._env_surface import REPO_ROOT, is_test_module

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_ROOTS: Final = ("src/vaultspec_rag", "dev", "tools", "scripts")
_WORD: Final = re.compile(r"[A-Za-z_]\w*")

#: Method-name shapes a framework calls without naming: terminal-interface
#: actions, watchers and event handlers, parser callbacks, syntax-tree
#: visitors, request handlers.
_DISPATCHED_PREFIXES: Final = ("action_", "watch_", "on_", "handle_", "visit_", "do_")
_DISPATCHED_NAMES: Final = frozenset({"compose", "render"})

#: Decorators that leave a method an ordinary attribute a caller must name.
_PLAIN_DECORATORS: Final = frozenset(
    {"property", "cached_property", "staticmethod", "classmethod"}
)

#: Module-level names every entry point or logger carries.
_CONVENTIONAL: Final = frozenset({"main", "app", "logger", "pytestmark"})

#: Definitions whose consumer is code the user writes, named with the
#: document that tells them to call it. The guard checks the document still
#: does, so an entry cannot outlive the contract it stands on.
_DOCUMENTED_EXTENSION_POINTS: Final[dict[str, str]] = {
    "src/vaultspec_rag/indexer/_preprocess_schema.py:load_preprocess_invocation": (
        "docs/preprocessing-hooks.md"
    ),
}

#: Definitions already known to have no production consumer and not yet
#: removed. Not a waiver: the set is held exact, so it can only shrink - a
#: new entry fails as unconsumed, and one that gains a consumer or is deleted
#: fails as stale until it is taken off this list.
_STILL_TO_REMOVE: Final = frozenset(
    {
        "src/vaultspec_rag/_machine_lock.py:acquire_machine_lock",
        "src/vaultspec_rag/_machine_lock.py:release_machine_lock",
        "src/vaultspec_rag/_test_isolation.py:reclaim_singleton_paths",
        "src/vaultspec_rag/_test_isolation.py:sweep_orphaned_singleton_roots",
        "src/vaultspec_rag/cli/_gpu_lease.py:capture_borrower_service_target",
        "src/vaultspec_rag/embeddings.py:encode_documents",
        "src/vaultspec_rag/indexer/_chunk_worker.py:chunk_file_with_status",
        "src/vaultspec_rag/indexer/_file_state.py:iter_publishable_states",
        "src/vaultspec_rag/indexer/_resolved_policy.py:compile_content_policy",
        "src/vaultspec_rag/serviceclient/_transport.py:_try_http_create_job",
    }
)


def _is_test(path: Path) -> bool:
    return is_test_module(path) or path.name == "conftest.py"


def _source_files() -> list[Path]:
    files = [REPO_ROOT / "conftest.py"]
    for root in _ROOTS:
        files.extend(sorted((REPO_ROOT / root).rglob("*.py")))
    return [path for path in files if "__pycache__" not in path.parts]


def _unreferenced_strings(tree: ast.Module) -> set[int]:
    """Return the ids of string nodes that export or document, not reference."""
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                skipped.add(id(first.value))
    for statement in tree.body:
        targets: list[str] = []
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign):
            targets = [t.id for t in statement.targets if isinstance(t, ast.Name)]
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            targets = [statement.target.id]
            value = statement.value
        if "__all__" in targets and value is not None:
            skipped.update(id(node) for node in ast.walk(value))
    return skipped


def _references(path: Path, tree: ast.Module) -> Counter[str]:
    """Count every way *tree* names something it consumes."""
    found: Counter[str] = Counter()
    skipped = _unreferenced_strings(tree)
    reexporting = path.name == "__init__.py"
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            found[node.id] += 1
        elif isinstance(node, ast.Attribute):
            found[node.attr] += 1
        elif isinstance(node, ast.ImportFrom) and not reexporting:
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.keyword) and node.arg:
            found[node.arg] += 1
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skipped
        ):
            found.update(set(_WORD.findall(node.value)))
    return found


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [ast.unparse(decorator) for decorator in node.decorator_list]


def _method_names(node: ast.ClassDef) -> list[str]:
    """Return the methods of *node* a caller has to name to reach."""
    names: list[str] = []
    for member in node.body:
        if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = member.name
        if name.startswith("__") or name in _DISPATCHED_NAMES:
            continue
        if name.startswith(_DISPATCHED_PREFIXES):
            continue
        if all(decorator in _PLAIN_DECORATORS for decorator in _decorators(member)):
            names.append(name)
    return names


def _definitions(tree: ast.Module) -> list[str]:
    """Return the names *tree* defines that a consumer has to spell."""
    names: list[str] = []
    for statement in tree.body:
        if isinstance(statement, ast.ClassDef):
            names.append(statement.name)
            names.extend(_method_names(statement))
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not statement.decorator_list:
                names.append(statement.name)
        elif isinstance(statement, ast.Assign):
            names.extend(t.id for t in statement.targets if isinstance(t, ast.Name))
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            names.append(statement.target.id)
    return [
        name
        for name in names
        if not name.startswith("__") and name not in _CONVENTIONAL
    ]


@cache
def _unconsumed() -> frozenset[str]:
    """Return ``path:name`` for every definition non-test source never names."""
    consumed: Counter[str] = Counter()
    defined: list[tuple[str, str]] = []
    for path in _source_files():
        if _is_test(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consumed.update(_references(path, tree))
        relative = path.relative_to(REPO_ROOT).as_posix()
        defined.extend((relative, name) for name in _definitions(tree))
    return frozenset(
        f"{relative}:{name}" for relative, name in defined if not consumed[name]
    )


def test_production_defines_nothing_without_a_production_consumer() -> None:
    """Every definition in non-test source is named by non-test source.

    Mutation: appended ``def nothing_calls_this() -> None: ...`` to a
    production module. Observed this assertion fail naming that function.
    """
    unconsumed = _unconsumed() - _STILL_TO_REMOVE - set(_DOCUMENTED_EXTENSION_POINTS)
    assert not unconsumed, (
        "these definitions have no consumer outside the tests. Delete each "
        "with the tests that exist for it, or, where tests use it to reach "
        f"other behaviour, move it beside them as a fixture: {sorted(unconsumed)}"
    )


def test_the_removal_backlog_only_shrinks() -> None:
    """A backlog entry that is gone, or now consumed, comes off the list.

    Mutation: added a name the source does not define to the backlog. Observed
    this assertion fail naming it.
    """
    stale = sorted(_STILL_TO_REMOVE - _unconsumed())
    assert not stale, f"no longer unconsumed; remove from the backlog: {stale}"


def test_documented_extension_points_are_still_documented() -> None:
    """The document that makes a definition an extension point still names it.

    Mutation: pointed the entry at a document that does not mention the
    function. Observed this assertion fail naming both.
    """
    undocumented = {
        entry: document
        for entry, document in _DOCUMENTED_EXTENSION_POINTS.items()
        if entry.rsplit(":", 1)[1]
        not in (REPO_ROOT / document).read_text(encoding="utf-8")
    }
    assert not undocumented, (
        "these are exempt as documented extension points, and the document "
        f"named no longer mentions them: {undocumented}"
    )
    unneeded = sorted(set(_DOCUMENTED_EXTENSION_POINTS) - _unconsumed())
    assert not unneeded, f"consumed in the source now; drop the entry: {unneeded}"
