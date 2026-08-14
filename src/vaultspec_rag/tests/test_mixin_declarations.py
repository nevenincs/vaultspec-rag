"""Guard: a mixin declares the host's state; it never becomes a dataclass.

A mixin in this package exists to carry one lifecycle off a large class, and
it declares the host attributes it reads so it type-checks on its own terms.
Those declarations are annotations describing state the HOST owns and assigns.

Putting ``@dataclass`` on such a class reinterprets every one of them as a
field of the mixin, and ``frozen=True`` turns them into read-only properties -
so the host's own ``__init__`` can no longer assign its own attributes. Nothing
about that failure names a decorator: it surfaces as a pile of "property is
read-only" errors at each assignment, a long way from the class that caused it.

This is not hypothetical. Splitting a large module by line range carried a
``@dataclass(frozen=True, slots=True)`` from the copied header onto the new
mixin, and that is exactly what happened.

The related trap - a decorator left behind by a line-range cut, landing on
whatever definition followed it - is not guarded here. The type checker
already reports it, because the decorators that matter change a callable's
type: ``@work`` makes a method return a ``Worker``, and calling it for the
underlying value stops type-checking. A second mechanism asserting the same
thing would drift from the one that actually runs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def _decorator_names(node: ast.ClassDef) -> list[str]:
    """Return the bare name of every decorator applied to *node*."""
    names: list[str] = []
    for decorator in node.decorator_list:
        base = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = getattr(base, "attr", None) or getattr(base, "id", None)
        if name is not None:
            names.append(name)
    return names


def _mixin_classes() -> list[tuple[str, ast.ClassDef]]:
    """Return every production class whose name declares it a mixin."""
    found: list[tuple[str, ast.ClassDef]] = []
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Mixin"):
                found.append((f"{path.name}:{node.lineno}", node))
    return found


class TestAMixinIsNotADataclass:
    """The decorator that silently disowns a host's own attributes."""

    def test_the_package_still_has_mixins_to_check(self) -> None:
        """A guard over an empty set passes without proving anything.

        Mutation it catches: narrowing the collector - a renamed suffix, a
        changed root - until it matches nothing. The assertion below would
        then pass on every run while checking no class at all.
        """
        assert len(_mixin_classes()) >= 10

    def test_no_mixin_carries_a_dataclass_decorator(self) -> None:
        """Mutation it catches: dropping the decorator check.

        A ``@dataclass`` here reinterprets the host-state annotations as this
        class's own fields, and ``frozen=True`` makes them read-only, so the
        host cannot assign its own attributes. The failure surfaces at every
        assignment rather than at the decorator.
        """
        offenders = {
            where: names
            for where, node in _mixin_classes()
            if "dataclass" in (names := _decorator_names(node))
        }

        assert not offenders, (
            f"mixin(s) declared as a dataclass: {offenders}. A mixin's "
            "annotations describe state the host owns and assigns; a "
            "dataclass turns them into its own fields, and a frozen one into "
            "read-only properties the host can no longer set."
        )
