"""Code Stands Alone citation gate for every tracked product surface.

Fails when tracked source, test code, tooling, product documentation or product
config cites a development record - a dated vault stem, a plan container
identifier, a decision-enumeration token, a ``.vault/`` document path, a
codified rule name, or a codification-candidate reference. The reference
direction is one-way: development records cite code by locator, and code cites
nothing that lives outside itself.

Why AST plus tokenize, not a text scan. A citation is always PROSE: a docstring,
a comment, an operator-facing message, or documentation. Legitimate vault-shaped
test DATA is always a VALUE - a string literal in an expression, a path join, a
data keyword argument, a TOML value - and the product's own domain vocabulary
(indexing ``.vault/`` markdown, parsing ``adr/`` doc ids, advertising
``type:adr``) is likewise code, not prose. Separating prose from values
structurally is what lets the gate fire on a citation without firing on the
corpus the indexer is tested against.

Which prose surfaces are inspected, and why each. Every one of these was reached
only after a coverage probe showed the gate blind to it, so none is speculative:

* docstrings at every position - module (including the very first statement),
  class, function, async function, nested function and method;
* docstrings that are not a plain literal - an f-string docstring, and adjacent
  or ``+``-concatenated string statements, all of which parse to something other
  than a bare ``Constant`` and so escaped an ``isinstance`` check;
* every comment form, including a trailing comment and a Sphinx ``#:`` comment;
* documentary keyword arguments (``help``, ``description``, ``epilog``,
  ``short_help``) - these render to an operator as documentation, so a citation
  there escapes the codebase entirely;
* exception messages raised from source, for the same reason;
* product documentation and product config as raw text - ``README.md``,
  ``docs/``, ``pyproject.toml``, the justfile, CI workflows.

What is deliberately NOT inspected. A plain string VALUE is not scanned for
citations, because vault-shaped fixture data is legitimate and indistinguishable
from a citation once its structural position is discarded. Harness-owned trees
are skipped whole: the harness IS the development record, so naming a rule or a
``.vault/`` path there is its subject matter, not a leak.

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
import subprocess
import sys
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Repo-relative subtrees excluded entirely, each for a stated reason - never
#: because cleaning it was inconvenient. ``tests/quality`` is evaluation ground
#: truth by construction (real project doc ids in a TOML rubric and a generated
#: report), so it is data. The rest is harness: a development-record tree, or a
#: generated provider directory, whose whole subject matter IS the development
#: process, so a rule name or a ``.vault/`` path there is content, not a leak.
#: ``src/vaultspec_rag/builtins`` ships the product's own rule text, which
#: advertises the vault vocabulary the product indexes.
EXCLUDED_DIRS: tuple[str, ...] = (
    "src/vaultspec_rag/tests/quality",
    "src/vaultspec_rag/builtins",
    ".vault",
    ".vaultspec",
    ".claude",
    ".codex",
    ".gemini",
    ".agents",
)

#: Files excluded whole. ``CLAUDE.md``, ``AGENTS.md`` and ``GEMINI.md`` are
#: generated agent-instruction files: each names the rules and the vault layout
#: because instructing an agent about them is its entire job. ``CHANGELOG.md`` is
#: generated from commit subjects, so a citation reaching it cannot be fixed in
#: the file - the fix belongs at commit-message time, and a gate failure there
#: would only be un-actionable noise.
EXCLUDED_FILES: frozenset[str] = frozenset(
    {"CLAUDE.md", "AGENTS.md", "GEMINI.md", "CHANGELOG.md"}
)

#: Non-Python product surfaces scanned as raw text. Prose and value are not
#: separable in markdown or TOML, so the whole line is scanned; these files hold
#: no vault-shaped fixture data, which is what makes that safe. Matched by suffix
#: or by exact filename.
TEXT_SUFFIXES: tuple[str, ...] = (".md", ".toml", ".yaml", ".yml")
TEXT_FILENAMES: tuple[str, ...] = ("justfile",)

#: The single sanctioned prose-embedded data case: a docstring that names a
#: synthetic fixture filename to describe the fixture, not to cite a record.
#: Anchored to file and line so it cannot silently widen. If the line moves,
#: this must be re-confirmed rather than nudged.
ALLOWLIST: frozenset[tuple[str, int]] = frozenset(
    {
        ("src/vaultspec_rag/tests/integration/test_robustness.py", 71),
    }
)

#: TEMPORARY deferral, not a permanent exemption. Each entry is a whole file
#: holding a citation that this change surfaced but could not repair, because
#: another effort is editing that file right now and a prose edit landing under
#: someone mid-refactor costs more than the citation does. Every one is still
#: REPORTED on every run, so the deferral is visible and never silent. When a
#: file is cleaned, DELETE its entry - an emptied deferral that lingers is a hole
#: the gate can no longer see through.
#:
#: The cost is stated plainly: deferral is per FILE, so a new citation added to
#: one of these is also unreported until the entry goes. That is why the set is
#: a handoff list with an owner, not a parking space.
DEFERRED_PENDING_FOLLOWUP: frozenset[str] = frozenset(
    {
        # ``is_temp_rooted`` - points at a rule for the report-only guarantee.
        # Owned by the consolidation effort, whose repair also has to correct the
        # claim itself: the flag now does feed a destructive path.
        "src/vaultspec_rag/storage_survey.py",
        # ``_resolve_binary`` region - debug-logging pointer. Directory actively
        # being split.
        "src/vaultspec_rag/qdrant_runtime/_resolve.py",
        # GPU error rendering - debug-logging pointer. Uncommitted work present.
        "src/vaultspec_rag/cli/_gpu_errors.py",
        # Service-reachability tool docstring - parenthesised rule pointer.
        # Uncommitted work present, staged and unstaged both.
        "src/vaultspec_rag/mcp/_tools.py",
        # Install integration test - points at the no-mocks convention.
        "src/vaultspec_rag/tests/integration/test_install.py",
        # Install-mode test - points at the managed-singleton convention.
        "src/vaultspec_rag/tests/test_install_mode.py",
    }
)

#: The project's own codified rule stems. A rule name is an artefact of how the
#: project is governed, not of how the code works, and the tree carrying it is
#: removable - so the pointer dangles exactly like a dated stem does. Spelled out
#: here rather than read from the rules directory so the gate keeps working when
#: that directory is gone; a guard test asserts this set still matches what is on
#: disk, so the list cannot silently fall behind. The ``.builtin`` rules are
#: excluded on purpose: their stems ARE product names (``vaultspec-rag``), so
#: matching them would fire on the product's own vocabulary.
RULE_STEMS: tuple[str, ...] = (
    "canonical-code",
    "gpu-discipline",
    "guard-tests-prove-they-can-fail",
    "no-dev-metadata-in-code",
    "pinned-binaries-verify-before-execute",
    "rerankers-score-real-content",
    "service-surface",
    "storage-discipline",
)

#: Each pattern is one class of citation. Bare ``.vault/adr/`` and the product's
#: domain use of "ADR"/"vault" are deliberately NOT matched: only a DATED stem, a
#: plan coordinate, a parenthesised decision token, a Sphinx role pointing into
#: the vault, a codified rule name, or the literal codification-candidate phrase.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        # A dated kebab stem in ANY form. A trailing document-type segment
        # (``-adr``, ``-plan``, ...) is NOT required, and requiring it was the
        # hole that let the gate report clean on a live citation: prose
        # abbreviates a record by its bare dated stem far more often than it
        # writes the full filename, and the exec-folder form has no type suffix
        # at all. The tail must contain a letter, so a numeric date range and a
        # timestamp still read as data rather than as a stem.
        "dated-vault-stem",
        re.compile(r"\b\d{4}-\d{2}-\d{2}-[a-z0-9-]*[a-z][a-z0-9-]*"),
    ),
    ("codified-rule-name", re.compile(r"\b(?:" + "|".join(RULE_STEMS) + r")\b")),
    (
        # A rule citation by POSITION rather than by name. The list above only
        # knows the rules that exist today, so it is blind to every citation of a
        # rule since renamed or consolidated away - and this project collapsed
        # fifteen rules into seven, so those citations are the common case, not a
        # hypothetical. Matching the pointer phrasing instead needs no list.
        #
        # Only the pointer forms match, because "rule" is core product
        # vocabulary here: this product ships built-in rules, indexes
        # user-authored ones, and wraps linters that have their own. "a
        # document-preprocessing rule", "basedpyright's uppercase-is-constant
        # rule" and "Ruff has no module-length rule" are all legitimate and all
        # stay legal. What distinguishes a citation is that it POINTS: "per the
        # X rule", "(the X rule)", "project X rule", or a quoted identifier
        # after the artefact word. Every one of those was checked against the
        # tree; a looser pattern lit up ten legitimate lines, and a pattern that
        # cries wolf ten times is one the next person deletes.
        "rule-citation",
        re.compile(
            r"\b(?:per|under|see|violates?|breaks?|contrary to)\s+(?:the\s+)?"
            r"[a-z0-9]+(?:-[a-z0-9]+)+\s+(?:rule|convention|mandate)\b"
            r"|\(the\s+[a-z0-9]+(?:-[a-z0-9]+)+\s+(?:rule|convention|mandate)\)"
            r"|\bproject\s+[a-z0-9]+(?:-[a-z0-9]+)+\s+(?:rule|convention|mandate)\b"
            r"|\b(?:rule|convention|mandate)\s+[`'\"]{1,2}[a-z0-9]+(?:-[a-z0-9]+)+"
        ),
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
            r"\((?:ADR\s+)?(?:D|Q|QR|C)\d{1,2}(?:\s*[,/]\s*(?:D|Q|QR|C|P)\d{1,2})*\)"
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
    # numbered, so ``phase 2`` is a plan Phase). ``step N`` is deliberately NOT
    # matched: unlike wave and phase it is ordinary instructional English, and a
    # sweep of the tree found every occurrence to be a numbered instruction in a
    # procedure rather than a plan Step. The zero-padded ``S07`` form that a plan
    # actually uses is matched by ``bare-plan-coordinate`` above.
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
    # The account segment must name somebody. Documentation has to show an
    # operator where their own home directory sits, and a stand-in that the
    # reader is expected to substitute reveals no identity - which is the whole
    # point of this pattern - so the placeholders are excluded by name rather
    # than by anchoring individual documentation lines that will move.
    (
        "user-home-path",
        re.compile(
            r"[\\/](?:Users|home)[\\/]"
            r"(?!(?:me|you|user|username|USER|HOME)[\\/\s\"'`]|[<{$])"
            r"[A-Za-z0-9_.-]+"
        ),
    ),
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


#: Keyword arguments whose string value is documentation by construction: an
#: argument parser renders each of these to an operator. A citation there has
#: escaped the codebase into the product's own user interface, so unlike an
#: ordinary string value these are prose and are scanned.
DOC_KEYWORDS: frozenset[str] = frozenset(
    {"help", "description", "epilog", "short_help"}
)


def _string_lines(node: ast.AST) -> list[tuple[int, str]]:
    """Return (line, text) for every string constant reachable from *node*.

    Walking for constants rather than reading one ``Constant`` is what reaches an
    f-string (whose literal segments are constants under a ``JoinedStr``) and a
    concatenated or implicitly-joined string (whose segments sit under a
    ``BinOp``). Each is scanned line by line so a reported line lands on the
    offending line rather than on the opening quote.
    """
    out: list[tuple[int, str]] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            for offset, text in enumerate(sub.value.splitlines() or [sub.value]):
                out.append((sub.lineno + offset, text))
    return out


def _comment_blocks(source: str) -> list[list[tuple[int, str]]]:
    """Group comment tokens into runs of consecutive lines.

    A comment sentence wraps across several ``#`` lines, and a citation inside it
    straddles the break. Grouping the run restores the sentence.

    The run is broken where the lines stop being consecutive so that a finding is
    attributed to the comment it actually sits in. Note what that break does NOT
    do: it is not what stops a phrase forming across two unrelated comments. Each
    token carries its own ``#`` into the joined text, and no pattern here matches
    across one. The invented-phrase risk lives in ``_text_blocks``, where
    markdown paragraphs have no such separator.
    """
    blocks: list[list[tuple[int, str]]] = []
    run: list[tuple[int, str]] = []
    previous = -2
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type != tokenize.COMMENT:
            continue
        line = tok.start[0]
        if line != previous + 1 and run:
            blocks.append(run)
            run = []
        run.append((line, tok.string))
        previous = line
    if run:
        blocks.append(run)
    return blocks


def _iter_prose(path: Path) -> list[list[tuple[int, str]]]:
    """Return the prose of *path* as blocks of (line, text).

    Prose is a docstring at any position, a comment in any form, a documentary
    keyword argument, or an exception message. Every other string in the file is
    a value and is deliberately ignored - that is the distinction which keeps
    vault-shaped fixture data legitimate.

    A BLOCK rather than a line is the unit, because prose is hard-wrapped and a
    citation does not respect the wrap. "per the" can end one line and the record
    it names begin the next, which every multi-word pattern misses when each line
    is matched alone - a real citation escaped exactly that way. The block is
    joined before matching and offsets are mapped back, so the finding still
    reports the line the citation starts on.
    """
    source = path.read_text(encoding="utf-8")
    blocks: list[list[tuple[int, str]]] = []

    tree = ast.parse(source)
    for node in ast.walk(tree):
        # A bare string-valued statement is a docstring wherever it appears -
        # module (including the file's first statement), class, function, async
        # function, nested function, method - or a string used as a comment.
        # Either way it is prose. ``JoinedStr`` and ``BinOp`` are admitted
        # alongside ``Constant`` because an f-string docstring and a
        # ``+``-concatenated one are still docstrings; excluding them was a hole.
        if isinstance(node, ast.Expr) and isinstance(
            node.value, ast.Constant | ast.JoinedStr | ast.BinOp
        ):
            if not isinstance(node.value, ast.Constant) or isinstance(
                node.value.value, str
            ):
                blocks.append(_string_lines(node.value))
            continue
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in DOC_KEYWORDS:
                    blocks.append(_string_lines(keyword.value))
            continue
        if isinstance(node, ast.Raise) and node.exc is not None:
            blocks.append(_string_lines(node.exc))

    blocks.extend(_comment_blocks(source))
    return [block for block in blocks if block]


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
    *,
    allowed_lines: frozenset[tuple[str, int]] = frozenset(),
) -> list[Finding]:
    """Match *patterns* against *items*, honouring both allowlist shapes.

    *allowed_lines* skips a whole (file, line) anchor - the citation allowlist,
    which sanctions one prose line. ``PATH_ALLOWLIST`` skips one (file, line,
    text) triple, so a sanctioned path does not widen a pattern.
    """
    findings: list[Finding] = []
    for line, text in items:
        if (rel, line) in allowed_lines:
            continue
        for slug, pattern in patterns:
            match = pattern.search(text)
            if match and (rel, line, match.group(0)) not in PATH_ALLOWLIST:
                findings.append(Finding((rel, line, slug, match.group(0))))
    return findings


def _match_blocks(
    blocks: list[list[tuple[int, str]]],
    rel: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    *,
    allowed_lines: frozenset[tuple[str, int]] = frozenset(),
) -> list[Finding]:
    """Match *patterns* against each block's joined prose, reporting real lines.

    Joining is what makes a wrapped citation visible; the offset-to-line map is
    what keeps the finding useful once it is. Reporting the block's first line
    instead would send every reader to the top of a long docstring.
    """
    findings: list[Finding] = []
    for block in blocks:
        joined = " ".join(text.strip() for _line, text in block)
        # Character offset of the start of each piece within *joined*, so a match
        # position can be resolved back to the line it began on.
        starts: list[tuple[int, int]] = []
        cursor = 0
        for line, text in block:
            starts.append((cursor, line))
            cursor += len(text.strip()) + 1
        for slug, pattern in patterns:
            match = pattern.search(joined)
            if not match:
                continue
            line = next(
                (ln for offset, ln in reversed(starts) if offset <= match.start()),
                block[0][0],
            )
            if (rel, line) in allowed_lines:
                continue
            if (rel, line, match.group(0)) in PATH_ALLOWLIST:
                continue
            findings.append(Finding((rel, line, slug, match.group(0))))
    return findings


def _text_lines(path: Path) -> list[tuple[int, str]]:
    """Return (line, text) for every raw line of a non-Python file."""
    return list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))


def _text_blocks(path: Path) -> list[list[tuple[int, str]]]:
    """Return the paragraphs of a non-Python file as blocks of (line, text).

    Markdown prose is hard-wrapped, so a paragraph is the unit for the same
    reason a docstring is. A blank line ends a paragraph; joining across one
    would splice two unrelated sentences together.
    """
    blocks: list[list[tuple[int, str]]] = []
    run: list[tuple[int, str]] = []
    for line, text in _text_lines(path):
        if text.strip():
            run.append((line, text))
        elif run:
            blocks.append(run)
            run = []
    if run:
        blocks.append(run)
    return blocks


def scan_file(path: Path, *, repo_root: Path = REPO_ROOT) -> list[Finding]:
    """Return every citation in the prose of a Python file.

    *repo_root* is a parameter rather than only the module constant because a
    gate whose detection can be run against nothing but the live checkout can be
    confirmed green and never shown able to go red. Being able to point the scan
    at a throwaway tree is part of the gate, not test scaffolding.
    """
    rel = path.relative_to(repo_root).as_posix()
    return _match_blocks(_iter_prose(path), rel, PATTERNS, allowed_lines=ALLOWLIST)


def scan_file_paths(
    path: Path, *, repo_root: Path = REPO_ROOT
) -> tuple[list[Finding], list[Finding]]:
    """Return (hard identity leaks, soft absolute-path smells) for a Python file."""
    rel = path.relative_to(repo_root).as_posix()
    items = _iter_values_and_comments(path)
    return _match_patterns(items, rel, PATH_PATTERNS), _match_patterns(
        items, rel, PATH_SMELL_PATTERNS
    )


def scan_text(
    path: Path, *, repo_root: Path = REPO_ROOT
) -> tuple[list[Finding], list[Finding], list[Finding]]:
    """Return (citations, hard leaks, soft smells) for a non-Python file.

    Markdown and TOML carry no AST, so prose and value cannot be separated and
    the whole line is scanned for citations as well as for paths. That is sound
    only because the excluded set keeps harness trees and the evaluation rubric -
    the two places holding legitimate vault-shaped data - out of this walk.
    """
    rel = path.relative_to(repo_root).as_posix()
    items = _text_lines(path)
    return (
        _match_blocks(_text_blocks(path), rel, PATTERNS, allowed_lines=ALLOWLIST),
        _match_patterns(items, rel, PATH_PATTERNS),
        _match_patterns(items, rel, PATH_SMELL_PATTERNS),
    )


def _is_excluded(rel: str) -> bool:
    """Whether a repo-relative path is excluded from the walk entirely."""
    return rel in EXCLUDED_FILES or any(
        rel == d or rel.startswith(f"{d}/") for d in EXCLUDED_DIRS
    )


def iter_surface_files(repo_root: Path) -> tuple[list[Path], list[Path]]:
    """Return (Python files, text files) to scan for the repository at *root*.

    The enumeration is subtractive - everything git knows about, minus a stated
    exclusion - and never a list of directories to visit. Which surfaces are
    reached is as much a part of the gate as which patterns match, and an
    unreached surface is invisible from a green run: the tooling directory held a
    live citation for exactly as long as the enumeration was a list of includes.
    Anything added anywhere in the tree is now scanned by default, and escaping
    the scan means adding an exclusion with its reason on the record.

    Git supplies the file set because "tracked source" is precisely git's own
    notion of it. A filesystem walk cannot make that distinction: it descends
    into ignored vendored trees, whose imported changelogs then fail the gate on
    somebody else's release notes. ``--others --exclude-standard`` adds the files
    that are new but not ignored, so a citation in a brand-new file is caught
    before it is ever committed rather than one commit later.
    """
    listing = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    py_files: list[Path] = []
    text_files: list[Path] = []
    gate_file = Path(__file__).resolve()
    for rel in sorted(entry for entry in listing.split("\0") if entry):
        if _is_excluded(rel):
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        name = path.name
        if name.endswith(".py"):
            # The gate's own file is the sole source exemption: it spells every
            # citation shape out as a pattern literal and again in prose to
            # explain it, so scanning itself reports its own definitions as
            # findings.
            if path.resolve() != gate_file:
                py_files.append(path)
        elif name.endswith(TEXT_SUFFIXES) or name in TEXT_FILENAMES:
            text_files.append(path)
    return py_files, text_files


def collect_findings(
    repo_root: Path = REPO_ROOT,
) -> tuple[list[Finding], list[Finding], list[Finding], list[Finding]]:
    """Return (active citations, deferred citations, path leaks, path smells).

    Active citations and hard path leaks (identity-revealing) FAIL the gate.
    Deferred citations and soft path smells (generic absolute paths) are
    reported but do not fail - the smell surfaces a tmp_path-conversion backlog
    without blocking on non-leaking synthetic values.
    """
    active: list[Finding] = []
    deferred: list[Finding] = []
    leaks: list[Finding] = []
    smells: list[Finding] = []
    py_files, text_files = iter_surface_files(repo_root)
    for path in py_files:
        rel = path.relative_to(repo_root).as_posix()
        target = deferred if rel in DEFERRED_PENDING_FOLLOWUP else active
        target.extend(scan_file(path, repo_root=repo_root))
        f_leaks, f_smells = scan_file_paths(path, repo_root=repo_root)
        leaks.extend(f_leaks)
        smells.extend(f_smells)
    for path in text_files:
        rel = path.relative_to(repo_root).as_posix()
        target = deferred if rel in DEFERRED_PENDING_FOLLOWUP else active
        t_citations, t_leaks, t_smells = scan_text(path, repo_root=repo_root)
        target.extend(t_citations)
        leaks.extend(t_leaks)
        smells.extend(t_smells)
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

    py_files, text_files = iter_surface_files(REPO_ROOT)
    active, deferred, leaks, smells = collect_findings(REPO_ROOT)
    mode = "REPORT-ONLY" if args.report_only else "GATE"
    print(
        f"[citation-gate] {mode} - {len(py_files)} python and {len(text_files)} "
        "text file(s): docstrings, comments, documentary strings, exception "
        "messages, documentation, config, and string values (paths)"
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
