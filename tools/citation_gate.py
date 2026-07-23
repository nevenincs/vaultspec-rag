"""Code Stands Alone citation gate for ``src/vaultspec_rag``.

Fails when tracked source or test code cites a development record - a dated
vault stem, a plan container identifier, a decision-enumeration token, a
``.vault/`` document path, or a codification-candidate reference - in a
docstring or comment. The reference direction is one-way: vault documents cite
code by locator, and code cites nothing in the vault.

Why AST plus tokenize, not a text scan. A citation is always prose: it lives in
a docstring or a comment. Legitimate vault-shaped test DATA is always a value -
a string literal in an expression, a path join, a keyword argument, a TOML
value - and the product's own domain vocabulary (indexing ``.vault/`` markdown,
parsing ``adr/`` doc ids, advertising ``type:adr``) is likewise code, not prose.
Inspecting only docstrings and comment tokens is what separates the citation
from the data mechanically, so the gate does not fire on the corpus the indexer
is tested against.

What it cannot do, and why the convention half exists. This gate enforces "no
citation token remains". It cannot enforce "the sentence still parses once the
token is gone" - a citation that is the grammatical head or object of its clause
leaves a broken fragment when deleted, and that is a human or model read, not a
pattern. See the Code Stands Alone rule.

Usage:
    uv run python tools/citation_gate.py [--report-only]

Exits non-zero when any citation is found (the default). ``--report-only``
lists findings and always exits 0, for use while a remediation is in flight.
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "src" / "vaultspec_rag"

#: Subtrees under the package that are excluded entirely. ``tests/quality`` is
#: evaluation ground truth by construction - real project doc ids in a TOML
#: rubric and a generated markdown report - not source, so it is data, not a
#: citation surface.
EXCLUDED_DIRS: tuple[str, ...] = ("tests/quality",)

#: The single sanctioned prose-embedded data case: a docstring that names a
#: synthetic fixture filename to describe the fixture, not to cite a record.
#: Anchored to file and line so it cannot silently widen. If the line moves,
#: this must be re-confirmed rather than nudged.
ALLOWLIST: frozenset[tuple[str, int]] = frozenset(
    {
        ("src/vaultspec_rag/tests/integration/test_robustness.py", 71),
    }
)

#: TEMPORARY deferral, not a permanent exemption. These files still carry
#: citations because the Code Stands Alone remediation deliberately did not
#: touch them: they hold in-flight index and dormant-effort work, so cleaning
#: their citations waits for a follow-up sweep once that work settles, rather
#: than colliding with it now. Each entry is a whole file, listed with the
#: citations it still holds so the deferral is visible, never silent. When the
#: follow-up sweep cleans a file, DELETE its entry here - an emptied deferral
#: that lingers is a hole the gate can no longer see through.
DEFERRED_PENDING_FOLLOWUP: frozenset[str] = frozenset(
    {
        # in-flight index work - carries preprocess D-tokens
        "src/vaultspec_rag/indexer/_codebase_indexer.py",
        # dormant-effort tree - module-split stem + machine-singleton token
        "src/vaultspec_rag/server/_lifespan.py",
        # dormant-effort tree - plan coordinate in the module docstring
        "src/vaultspec_rag/tests/integration/test_service_jobs.py",
    }
)

_VAULT_TYPES = "adr|plan|audit|research|reference|exec"

#: Each pattern is one class of citation. Bare ``.vault/adr/`` and the product's
#: domain use of "ADR"/"vault" are deliberately NOT matched: only a DATED stem
#: under a vault type, a plan coordinate, a parenthesised decision token, a
#: typed ``.vault/<type>/`` path, or the literal codification-candidate phrase.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "dated-vault-stem",
        re.compile(rf"\b\d{{4}}-\d{{2}}-\d{{2}}-[a-z0-9-]+-(?:{_VAULT_TYPES})\b"),
    ),
    (
        "plan-container-id",
        re.compile(
            r"\bW\d{2}\.P\d{2}(?:\.S\d{2})?\b|\bP\d{2}\.S\d{2}\b|\bplan [WP]\d{2}\b"
        ),
    ),
    (
        "decision-token",
        re.compile(
            r"\((?:ADR\s+)?(?:D|Q|QR|C)\d{1,2}"
            r"(?:\s*[,/]\s*(?:D|Q|QR|C|P)\d{1,2})*\)"
        ),
    ),
    (
        # Only a Sphinx ``:doc:`` cross-reference into the vault - the form with
        # a mechanical docs-build consumer. A bare ``.vault/adr/`` mention in
        # prose (e.g. describing what a regression harness guards) is domain
        # vocabulary, not a citation, and a real document path always carries a
        # dated stem the pattern above already catches.
        "vault-doc-role",
        re.compile(r":doc:`[^`]*\.vault/"),
    ),
    ("codification-candidate", re.compile(r"codification candidate")),
)


class Finding(tuple[str, int, str, str]):
    """(rel_path, line, class_slug, matched_text)."""


def _iter_prose(path: Path) -> list[tuple[int, str]]:
    """Return (line, text) for every docstring and comment in *path*.

    Only these two surfaces carry citations; every other string in the file is
    a value and is deliberately ignored.
    """
    source = path.read_text(encoding="utf-8")
    prose: list[tuple[int, str]] = []

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        # A bare string-constant Expr is a docstring wherever it appears
        # (module, class, function) or a string used as a comment; either way
        # it is prose. Its own text is scanned line by line so a reported line
        # number lands on the offending line, not the docstring's opening.
        for offset, text in enumerate(node.value.value.splitlines()):
            prose.append((node.value.lineno + offset, text))

    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            prose.append((tok.start[0], tok.string))

    return prose


def scan_file(path: Path) -> list[Finding]:
    rel = path.relative_to(REPO_ROOT).as_posix()
    findings: list[Finding] = []
    for line, text in _iter_prose(path):
        if (rel, line) in ALLOWLIST:
            continue
        for slug, pattern in PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append(Finding((rel, line, slug, match.group(0))))
    return findings


def _is_excluded(path: Path) -> bool:
    rel = path.relative_to(PACKAGE_DIR).as_posix()
    return any(rel.startswith(f"{d}/") for d in EXCLUDED_DIRS)


def collect_findings(root: Path) -> tuple[list[Finding], list[Finding]]:
    """Return (active, deferred) findings.

    Active findings fail the gate; deferred ones belong to files awaiting the
    follow-up sweep and are reported but do not fail, so the gate is green on
    the cleaned corpus while still surfacing the outstanding work.
    """
    active: list[Finding] = []
    deferred: list[Finding] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or _is_excluded(path):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        target = deferred if rel in DEFERRED_PENDING_FOLLOWUP else active
        target.extend(scan_file(path))
    active.sort(key=lambda f: (f[0], f[1]))
    deferred.sort(key=lambda f: (f[0], f[1]))
    return active, deferred


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="list findings but always exit 0 (for a remediation in flight)",
    )
    args = parser.parse_args()

    active, deferred = collect_findings(PACKAGE_DIR)
    mode = "REPORT-ONLY" if args.report_only else "GATE"
    print(f"[citation-gate] {mode} - scanning docstrings and comments")

    if deferred:
        print(
            f"[citation-gate] {len(deferred)} citation(s) deferred to the "
            "follow-up sweep (not failing):"
        )
        for rel, line, slug, text in deferred:
            print(f"  (deferred) {rel}:{line}: {slug}: {text}")

    if not active:
        print("[citation-gate] clean - no active development-record citations")
        return 0

    for rel, line, slug, text in active:
        print(f"  {rel}:{line}: {slug}: {text}")
    print(f"[citation-gate] {len(active)} active citation(s) found")

    if args.report_only:
        print("[citation-gate] report-only mode never fails")
        return 0
    print(
        "[citation-gate] FAIL - code cites a development record. State the "
        "constraint directly and remove the citation; see the Code Stands "
        "Alone rule."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
