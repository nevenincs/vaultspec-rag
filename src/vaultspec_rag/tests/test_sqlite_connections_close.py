"""A ``with`` over a SQLite connection commits it and leaves it open.

``with sqlite3.connect(path) as connection:`` reads as "open, use, close" and
is not: the connection's context manager ends the transaction and nothing
more. The connection is closed when the object is collected, which the
interpreter reports as a ``ResourceWarning``.

Where it is collected is the trouble. Usually that is the line the name goes
out of scope. When a traceback or a fixture keeps the frame alive it is some
later garbage collection instead, in whichever test happens to be running, and
a test that records every warning raised inside a scope then records this one.
That failed an unrelated refused-endpoint test on one runner twice running.

``contextlib.closing`` closes the connection; ``with closing(...) as c, c:``
keeps the commit as well.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from .. import _process_probe

pytestmark = [pytest.mark.unit]

_PACKAGE_ROOT = Path(_process_probe.__file__).parent


def _bare_connection_scopes(tree: ast.AST) -> list[int]:
    """Return the line of every ``with`` whose manager is ``sqlite3.connect``."""
    return [
        item.context_expr.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.With | ast.AsyncWith)
        for item in node.items
        if isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Attribute)
        and item.context_expr.func.attr == "connect"
        and isinstance(item.context_expr.func.value, ast.Name)
        and item.context_expr.func.value.id == "sqlite3"
    ]


def test_no_scope_takes_a_connection_as_its_own_context_manager() -> None:
    """Every SQLite connection opened in a ``with`` is closed by that ``with``.

    Mutation proof: dropping ``closing`` from the one site in
    ``test_vault_run_liveness.py`` made this fail naming that file and line;
    restoring it made this pass.
    """
    sources = sorted(_PACKAGE_ROOT.rglob("*.py"))
    assert sources, f"no source under {_PACKAGE_ROOT}; this guard checks nothing"
    findings = [
        f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{line}"
        for path in sources
        for line in _bare_connection_scopes(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not findings, (
        "these scopes commit a SQLite connection and never close it; wrap the "
        "connection in contextlib.closing:\n" + "\n".join(findings)
    )
