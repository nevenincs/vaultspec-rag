"""Report intra-package imports written absolutely instead of relatively.

The rule is that a module inside ``vaultspec_rag`` reaches its siblings by
relative import, so the package can be vendored or renamed without editing
every call site.

This reads the syntax tree rather than the file's text. The text is where the
previous check went wrong: this package embeds child scripts as string
literals, and those scripts run in a SEPARATE interpreter where an absolute
import is the only thing that works. A line-based scan cannot tell a real
import from a line inside one of those strings, so it reported them all -
seventy-four false positives against seven real findings, which is a gate
nobody can satisfy and therefore a gate everyone learns to ignore.

Scope is deliberately what the previous check covered - ``from vaultspec_rag.x
import y`` - so that repairing the false positives does not silently widen the
rule at the same time. Two forms remain uncovered and are left for a separate
decision: ``import vaultspec_rag.x`` (74 deliberate uses in the CLI, where the
module aliases itself) and the dotless ``from vaultspec_rag import x``.

A statement may opt out with an ``absolute-import-ok`` comment on its first
line, which is how the embedded-script imports that ARE real statements in a
test module already declare themselves.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_PACKAGE = "vaultspec_rag"
_OPT_OUT = "absolute-import-ok"


def _violations(path: Path) -> list[tuple[int, str]]:
    """Return the (line, source) of each absolute intra-package from-import."""
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # Parsed and reported by the type and lint lanes; not this gate's job.
        return []
    lines = text.split("\n")
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level:
            continue
        if not (node.module or "").startswith(f"{_PACKAGE}."):
            continue
        source = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
        if _OPT_OUT in source:
            continue
        found.append((node.lineno, source.strip()))
    return found


def main() -> int:
    """Print every violation and return a process exit code."""
    root = Path(__file__).resolve().parent.parent / "src" / _PACKAGE
    if not root.is_dir():
        print(f"package tree not found: {root}", file=sys.stderr)
        return 2
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for lineno, source in _violations(path):
            rel = path.relative_to(root.parent.parent).as_posix()
            offenders.append(f"{rel}:{lineno}: {source}")
    if offenders:
        print("ABSOLUTE IMPORTS FOUND!")
        for offender in offenders:
            print(f"  {offender}")
        print(
            f"\n{len(offenders)} intra-package import(s) written absolutely. "
            "Use a relative import, or mark the line 'absolute-import-ok' when "
            "the import is for a child interpreter."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
