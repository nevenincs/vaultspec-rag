"""Code Stands Alone citation gate for ``src/vaultspec_rag`` and ``tools``.

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
# The scrub cleared every previously-deferred file, so the follow-up set is
# empty: every tracked file now gates on citations with no exceptions. A new
# entry here would re-open a tolerated hole, so it stays empty.
DEFERRED_PENDING_FOLLOWUP: frozenset[str] = frozenset()

#: Each pattern is one class of citation. Bare ``.vault/adr/`` and the product's
#: domain use of "ADR"/"vault" are deliberately NOT matched: only a DATED stem,
#: a plan coordinate, a parenthesised decision token, a typed ``.vault/<type>/``
#: path, or the literal codification-candidate phrase.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        # A dated kebab stem in ANY form. The trailing document-type segment
        # (``-adr``, ``-plan``, ...) is NOT required: a feature is cited far
        # more often by its bare dated stem - the exec-folder form, and the way
        # a document is abbreviated in prose - than by its full filename, and
        # requiring the type suffix let every such citation through while the
        # gate reported clean. The tail must contain a letter, so a numeric date
        # range does not read as a stem.
        "dated-vault-stem",
        re.compile(r"\b\d{4}-\d{2}-\d{2}-[a-z0-9-]*[a-z][a-z0-9-]*"),
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
    # Bare decision token. An ADR enumerates its decisions D1, D2, ...; a lone
    # ``D7``/``ADR D6``/``D1-D3`` in prose cites that enumeration. No product
    # vocabulary uses ``D`` + digits, so the bare form is unambiguous (the
    # parenthesised ``(D7)`` form is already caught by ``decision-token``).
    ("bare-decision-token", re.compile(r"\bD\d{1,2}\b")),
    # Audit finding reference. The rolling audit numbers findings
    # ``F<section>.<n>`` (F6.6, F9.1); the dotted form is distinctive and no
    # product vocabulary uses it.
    ("audit-finding-ref", re.compile(r"\bF\d+\.\d+\b")),
    # Review finding tag. ``H#``/``C#`` ALSO name markdown headings (an ADR's H1
    # title, an H2 subsection) which are core product vocabulary, so a bare
    # ``H1`` is NOT a citation. Only the unambiguous review shapes match: an
    # R-round prefix (``R36-C1``), a slash-run of tags (``C1/H1/H2``, ``H3/H4``),
    # an explicit ``review C1``, or a CWE/security-tagged finding.
    (
        "review-finding-tag",
        re.compile(
            r"\bR\d+-[HCD]\d+\b"
            r"|\b[HC]\d+(?:/[HC]\d+)+\b"
            r"|\breview\s+[HC]\d+\b"
            r"|\bH\d+\s*\((?:CWE|security)"
        ),
    ),
    # Research finding reference. Research documents label findings by a letter
    # and number (``research O3``, ``research A1``); matched only behind the
    # ``research`` lead word so a bare ``A1``/``O3`` value elsewhere is untouched.
    ("research-finding-ref", re.compile(r"\bresearch\s+[A-Z]\d+\b")),
    # Quality-review token ``QR#``. No product vocabulary uses it; kept so a
    # reintroduced ``QR4`` cannot slip in even though none remain today.
    ("quality-review-token", re.compile(r"\bQR\d{1,2}\b")),
    # Feature-named ADR / review reference. A kebab-case feature name immediately
    # before ``ADR`` or ``review`` points at a specific record
    # (``index-gpu-pipeline review``, ``service-graph ADR``). Domain phrases that
    # describe a KIND of ADR rather than name one - a ``no-marker ADR``, a
    # ``0-based ADR ordinal`` - are excluded by the leading lookahead.
    (
        "feature-named-adr",
        re.compile(
            r"\b(?!no-marker\b|0-based\b)[a-z0-9]+(?:-[a-z0-9]+)+\s+(?:ADR|review)\b"
        ),
    ),
    # Bare plan coordinates the dotted ``plan-container-id`` pattern misses: a
    # lone ``P03``/``S07``/``W04`` in a comment (e.g. ``# ... (#155 P03)`` or
    # ``S10: token persistence``) is a plan reference, not domain vocabulary -
    # the product has no bare ``P``/``S``/``W`` + two-digit concept. Two digits
    # keeps it off single-digit noise (a ``P0`` priority, an ``S3`` bucket).
    ("bare-plan-coordinate", re.compile(r"\b[PSW]\d{2}\b")),
    # Numbered wave/phase references in prose. ``wave N`` and ``phase N`` name a
    # plan container (service phases are named - warming/running - never
    # numbered, so ``phase 2`` is a plan Phase). ``step N`` is included; an
    # instructional "step 2" in prose is the one tuning point, allowlisted if it
    # is genuinely an ordinal rather than a plan Step.
    ("numbered-plan-container", re.compile(r"\b(?:[Ww]ave|[Pp]hase)\s+\d+\b")),
)

#: Workstation / absolute-path leaks. Unlike a citation, a machine path leaks in
#: a string VALUE just as much as in a comment, so these are matched on the
#: unescaped string value and on comments - NOT restricted to prose. Matching
#: the value is also what kills the ``"errors:\n"`` -> ``s:\n`` false positive a
#: raw-text drive-letter scan drowns in: the value is a newline, not a path.
# HARD path leaks - identity-revealing, they FAIL the gate. A user home names
# the developer; the worktree-root marker is this exact checkout's path.
PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("worktree-root", re.compile(r"vaultspec-rag-worktrees")),
    ("user-home-path", re.compile(r"[\\/](?:Users|home)[\\/][A-Za-z0-9_.-]+")),
)

# SOFT path smells - a hardcoded absolute drive path that reveals no identity
# (a generic ``C:\projects\proj-a`` synthetic value). Reported, not failed:
# like the synthetic fixture filenames the Code Stands Alone rule permits, a
# generic synthetic path is test data, not a machine leak. Surfaced so a
# tmp_path conversion can be scoped, without blocking on non-leaking values.
# The two-char tail rejects a lone regex escape (``r"x:\n"`` -> ``:\n``).
PATH_SMELL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("absolute-drive-path", re.compile(r"\b[A-Za-z]:[\\/][A-Za-z0-9_]{2,}")),
)

#: Confirmed-legitimate absolute paths kept by exact (file, line, text) anchor,
#: so a genuine need (a documented example, a platform-specific system path) is
#: allowed without widening the pattern. Empty until a real case is confirmed.
PATH_ALLOWLIST: frozenset[tuple[str, int, str]] = frozenset()


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


def scan_file(path: Path, *, repo_root: Path = REPO_ROOT) -> list[Finding]:
    """Return every citation in the prose of *path*, reported relative to a root.

    *repo_root* is a parameter rather than the module constant so the scan can
    be exercised against a throwaway tree. A gate whose detection can only be
    run against the live checkout can only be confirmed green, never proven
    able to go red.
    """
    rel = path.relative_to(repo_root).as_posix()
    findings: list[Finding] = []
    for line, text in _iter_prose(path):
        if (rel, line) in ALLOWLIST:
            continue
        for slug, pattern in PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append(Finding((rel, line, slug, match.group(0))))
    return findings


def _iter_values_and_comments(path: Path) -> list[tuple[int, str]]:
    """Return (line, text) for every string-literal VALUE and comment in *path*.

    A workstation path is illegitimate whether it sits in a comment or a data
    value, so - unlike the prose-only citation scan - this inspects string
    values too. The value is the DECODED string (``"a:\\n"`` yields ``a:`` then
    a newline), which is what distinguishes a real ``Y:\\code`` path from a
    ``word:\\n`` escape sequence a raw-text scan cannot tell apart.
    """
    source = path.read_text(encoding="utf-8")
    out: list[tuple[int, str]] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lines = node.value.splitlines() or [node.value]
            for offset, text in enumerate(lines):
                out.append((node.lineno + offset, text))
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            out.append((tok.start[0], tok.string))
    return out


def _match_patterns(
    items: list[tuple[int, str]],
    rel: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> list[Finding]:
    findings: list[Finding] = []
    for line, text in items:
        for slug, pattern in patterns:
            match = pattern.search(text)
            if match and (rel, line, match.group(0)) not in PATH_ALLOWLIST:
                findings.append(Finding((rel, line, slug, match.group(0))))
    return findings


def scan_file_paths(
    path: Path, *, repo_root: Path = REPO_ROOT
) -> tuple[list[Finding], list[Finding]]:
    """Return (hard identity leaks, soft absolute-path smells) for a Python file."""
    rel = path.relative_to(repo_root).as_posix()
    items = _iter_values_and_comments(path)
    return _match_patterns(items, rel, PATH_PATTERNS), _match_patterns(
        items, rel, PATH_SMELL_PATTERNS
    )


def scan_text_paths(
    path: Path, *, repo_root: Path = REPO_ROOT
) -> tuple[list[Finding], list[Finding]]:
    """Return (hard leaks, soft smells) for a non-Python tracked file (TOML)."""
    rel = path.relative_to(repo_root).as_posix()
    items = list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))
    return _match_patterns(items, rel, PATH_PATTERNS), _match_patterns(
        items, rel, PATH_SMELL_PATTERNS
    )


def _is_excluded(path: Path, package_dir: Path) -> bool:
    rel = path.relative_to(package_dir).as_posix()
    return any(rel.startswith(f"{d}/") for d in EXCLUDED_DIRS)


def collect_findings(
    root: Path,
    *,
    repo_root: Path = REPO_ROOT,
    tools_root: Path | None = None,
) -> tuple[list[Finding], list[Finding], list[Finding], list[Finding]]:
    """Return (active citations, deferred citations, path leaks, path smells).

    Active citations and hard path leaks (identity-revealing) FAIL the gate.
    Deferred citations and soft path smells (generic absolute paths) are
    reported but do not fail - the smell surfaces a tmp_path-conversion backlog
    without blocking on non-leaking synthetic values.

    *repo_root* and *tools_root* default to the live checkout and exist so the
    walk itself can be pointed at a throwaway tree: which surfaces are reached
    is as much a part of the gate as which patterns match, and an unreachable
    surface is invisible from a green run.
    """
    tools_root = repo_root / "tools" if tools_root is None else tools_root
    active: list[Finding] = []
    deferred: list[Finding] = []
    leaks: list[Finding] = []
    smells: list[Finding] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or _is_excluded(path, root):
            continue
        rel = path.relative_to(repo_root).as_posix()
        target = deferred if rel in DEFERRED_PENDING_FOLLOWUP else active
        target.extend(scan_file(path, repo_root=repo_root))
        f_leaks, f_smells = scan_file_paths(path, repo_root=repo_root)
        leaks.extend(f_leaks)
        smells.extend(f_smells)
    # The build/tooling surface is tracked source and gates on citations on the
    # same terms as the package. This gate's own file is the sole exemption: it
    # spells every citation shape out as a pattern literal and again in prose to
    # explain it, so scanning itself reports its own definitions as findings.
    for extra in sorted(tools_root.rglob("*.py")):
        if "__pycache__" in extra.parts or extra.resolve() == Path(__file__).resolve():
            continue
        active.extend(scan_file(extra, repo_root=repo_root))
        e_leaks, e_smells = scan_file_paths(extra, repo_root=repo_root)
        leaks.extend(e_leaks)
        smells.extend(e_smells)
    for cfg in ("pyproject.toml",):
        cfg_path = repo_root / cfg
        if cfg_path.is_file():
            c_leaks, c_smells = scan_text_paths(cfg_path, repo_root=repo_root)
            leaks.extend(c_leaks)
            smells.extend(c_smells)
    for bucket in (active, deferred, leaks, smells):
        bucket.sort(key=lambda f: (f[0], f[1]))
    return active, deferred, leaks, smells


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="list findings but always exit 0 (for a remediation in flight)",
    )
    args = parser.parse_args()

    active, deferred, leaks, smells = collect_findings(PACKAGE_DIR)
    mode = "REPORT-ONLY" if args.report_only else "GATE"
    print(
        f"[citation-gate] {mode} - scanning docstrings, comments, "
        "string values (paths), and config"
    )

    if deferred:
        print(
            f"[citation-gate] {len(deferred)} citation(s) deferred to the "
            "follow-up sweep (not failing):"
        )
        for rel, line, slug, text in deferred:
            print(f"  (deferred) {rel}:{line}: {slug}: {text}")

    if smells:
        print(
            f"[citation-gate] {len(smells)} generic absolute-path smell(s) "
            "(not failing; tmp_path-conversion backlog):"
        )
        for rel, line, slug, text in smells:
            print(f"  (smell) {rel}:{line}: {slug}: {text}")

    if leaks:
        print(f"[citation-gate] {len(leaks)} workstation-identity path leak(s):")
        for rel, line, slug, text in leaks:
            print(f"  {rel}:{line}: {slug}: {text}")

    if active:
        print(f"[citation-gate] {len(active)} active development-record citation(s):")
        for rel, line, slug, text in active:
            print(f"  {rel}:{line}: {slug}: {text}")

    if not active and not leaks:
        print(
            "[citation-gate] clean - no active development-record citations "
            "or workstation-identity path leaks"
        )
        return 0

    if args.report_only:
        print("[citation-gate] report-only mode never fails")
        return 0
    print(
        "[citation-gate] FAIL - state the constraint directly and remove the "
        "citation; remove the workstation-identity path (worktree root or user "
        "home). See the Code Stands Alone rule."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
