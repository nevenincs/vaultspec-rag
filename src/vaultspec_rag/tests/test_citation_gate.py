"""Guard tests for the Code Stands Alone citation gate.

The gate is the mechanical half of a convention whose other half is a human
read, and that division only holds if the mechanical half is actually
mechanical. A gate that returns clean on a live violation is worse than no gate:
it converts "nobody checked" into "the check passed", and the attention that
would have gone looking never goes. So these tests assert the gate can SEE each
shape it claims to catch, never merely that it runs.

The cases are organised on the two axes the coverage hole ran along - which
CONSTRUCT a citation sits in, and which forbidden TOKEN CLASS it belongs to.
A gate can be blind on either axis independently, and it was blind on both.

Every case builds a throwaway tree and scans that, so a shape is introduced and
its detection asserted without ever mutating the checkout. The final case is the
only one pointed at the live tree, and it is a regression guard on the tree
rather than evidence about the gate.

Each assertion below names the mutation it catches. Every one of those mutations
was run: the gate broken one way at a time, the named tests run alone, observed
to fail on the assertion they name, the gate restored from a copy held outside
the repository, the tests re-run and observed to pass. One uninterrupted
sequence, restoring in a ``finally`` so no mutation could outlive it on disk. An
unexplained matcher is one the next reader loosens, so each mutation is recorded
beside the assertion it defends rather than in a message somewhere else.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

# repo-root/src/vaultspec_rag/tests/<this file> -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATE_PATH = _REPO_ROOT / "tools" / "citation_gate.py"

#: One representative token per forbidden class, held as data so no test prose
#: has to spell one out. A value is not a citation - which is the distinction the
#: gate is built on, and the reason this file can carry these at all.
_STEM = "2026-06-02-index-perf-hardening"


def _load_gate() -> ModuleType:
    """Import the gate from ``tools/``, which is not an installed package."""
    spec = importlib.util.spec_from_file_location("_citation_gate", _GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    return _load_gate()


def _slugs(findings: list[tuple[str, int, str, str]]) -> list[str]:
    return [slug for _rel, _line, slug, _text in findings]


def _texts(findings: list[tuple[str, int, str, str]]) -> list[str]:
    return [text for _rel, _line, _slug, text in findings]


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _git_tree(root: Path) -> None:
    """Make *root* a git work tree, which is how the gate enumerates surfaces."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)


def test_the_reported_shape_is_seen(gate: ModuleType, tmp_path: Path) -> None:
    """A bare dated stem in a module docstring - the shape reported as clean.

    The module docstring was never the problem: the pattern was. It required a
    trailing document-type segment, so the bare dated stem - how prose actually
    abbreviates a record, and the only form the exec folder has - matched
    nothing. Asserted on the exact slug and the exact matched text, because a
    dozen patterns share one failure message and a looser assertion would pass
    on whichever of them happened to fire.

    Mutation proving this can fail: restore the ``-(?:adr|plan|...)`` suffix
    requirement on ``dated-vault-stem``.
    """
    source = _write(
        tmp_path,
        "module.py",
        f'"""Worker docstring.\n\nSee ADR ``{_STEM}`` and rule ``x``.\n"""\n',
    )

    findings = gate.scan_file(source, repo_root=tmp_path)

    assert _slugs(findings) == ["dated-vault-stem"]
    assert _texts(findings) == [_STEM]


def test_a_citation_is_reported_on_its_own_line_not_the_opening_quote(
    gate: ModuleType, tmp_path: Path
) -> None:
    """The reported line must land on the offending line inside the docstring.

    A finding that points at line 1 of every module sends the reader to the
    wrong place, and a wrong locator in a gate nobody trusts is how a gate stops
    being read at all.

    Mutation proving this can fail: report ``node.lineno`` for the whole
    docstring instead of accumulating the per-line offset.
    """
    source = _write(
        tmp_path, "module.py", f'"""Line one.\n\nLine three.\nSee ``{_STEM}``.\n"""\n'
    )

    findings = gate.scan_file(source, repo_root=tmp_path)

    assert [(line, slug) for _rel, line, slug, _text in findings] == [
        (4, "dated-vault-stem")
    ]


# Every construct a citation can sit in. The docstring positions and the comment
# forms were already reached; the last five were not, and each was found blind by
# probing rather than by reading the code - an f-string docstring and a
# concatenated one parse to something other than a bare ``Constant``, and a
# documentary argument and an exception message are strings the gate had no
# reason to treat as prose until you notice an operator reads them.
_CONSTRUCTS: tuple[tuple[str, str], ...] = (
    ("module docstring", '"""Head.\n\nSee {t}.\n"""\nX = 1\n'),
    ("module docstring first line", '"""Head {t}."""\nX = 1\n'),
    ("class docstring", 'class C:\n    """Doc {t}."""\n'),
    ("function docstring", 'def f() -> None:\n    """Doc {t}."""\n'),
    ("async function docstring", 'async def f() -> None:\n    """Doc {t}."""\n'),
    (
        "nested function docstring",
        'def f() -> None:\n    def g() -> None:\n        """Doc {t}."""\n',
    ),
    (
        "method docstring",
        'class C:\n    def m(self) -> None:\n        """Doc {t}."""\n',
    ),
    ("own-line comment", "# See {t}.\nX = 1\n"),
    ("trailing comment", "X = 1  # See {t}.\n"),
    ("sphinx attribute comment", "#: See {t}.\nX = 1\n"),
    ("implicitly joined docstring", 'def f() -> None:\n    """Doc "\n    "{t}."""\n'),
    ("adjacent concatenated strings", 'def f() -> None:\n    "Doc " "{t}."\n'),
    ("plus-concatenated strings", 'def f() -> None:\n    "Doc " + "{t}."\n'),
    ("f-string docstring", 'def f() -> None:\n    f"""Doc {{1}} {t}."""\n'),
    (
        "documentary keyword argument",
        'def o(**k: str) -> None: ...\no(help="See {t}.")\n',
    ),
    ("exception message", 'def f() -> None:\n    raise ValueError("See {t}.")\n'),
)


@pytest.mark.parametrize(
    ("label", "body"), _CONSTRUCTS, ids=[c[0] for c in _CONSTRUCTS]
)
def test_every_prose_construct_is_scanned(
    gate: ModuleType, tmp_path: Path, label: str, body: str
) -> None:
    """Mutation proving this can fail: drop ``ast.JoinedStr`` or ``ast.BinOp``
    from the bare-statement check, or delete the documentary-keyword or the
    ``ast.Raise`` branch. Each mutation reds exactly the rows it blinds.
    """
    source = _write(tmp_path, "module.py", body.format(t=_STEM))

    findings = gate.scan_file(source, repo_root=tmp_path)

    assert "dated-vault-stem" in _slugs(findings), f"{label} was not scanned"


# Every forbidden token class, each with the slug that must fire on it. Several
# patterns overlap by construction (a plan coordinate is also a bare coordinate),
# so each row asserts its own slug is present rather than that it is the only
# one - the point is that the named branch fired, not that no other did.
_TOKEN_CLASSES: tuple[tuple[str, str], ...] = (
    ("dated-vault-stem", _STEM),
    ("codified-rule-name", "gpu-discipline"),
    ("plan-container-id", "W01.P02.S03"),
    ("bare-plan-coordinate", "S07"),
    ("numbered-plan-container", "phase 3"),
    ("decision-token", "(D7)"),
    ("bare-decision-token", "D7"),
    ("vault-doc-role", ":doc:`../.vault/adr/thing`"),
    ("codification-candidate", "codification candidate"),
    ("audit-finding-ref", "F6.5"),
    ("review-finding-tag", "R36-C1"),
    ("research-finding-ref", "research O3"),
    ("quality-review-token", "QR4"),
    ("feature-named-adr", "index-gpu-pipeline ADR"),
)


@pytest.mark.parametrize(
    ("slug", "token"), _TOKEN_CLASSES, ids=[c[0] for c in _TOKEN_CLASSES]
)
def test_every_token_class_is_matched_in_prose(
    gate: ModuleType, tmp_path: Path, slug: str, token: str
) -> None:
    """Mutation proving this can fail: delete the pattern named by the row's
    slug. The row reds on its own slug, which no other pattern supplies.
    """
    source = _write(tmp_path, "module.py", f"# See {token} for why.\nX = 1\n")

    assert slug in _slugs(gate.scan_file(source, repo_root=tmp_path))


def test_a_rule_name_is_a_citation_wherever_the_prose_sits(
    gate: ModuleType, tmp_path: Path
) -> None:
    """A codified rule name is dev metadata as much as a dated stem is.

    It names how the project is governed rather than how the code works, and the
    tree carrying it is removable, so the pointer dangles the same way. The gate
    was completely blind to this class.

    Mutation proving this can fail: delete the ``codified-rule-name`` pattern.
    """
    source = _write(
        tmp_path,
        "module.py",
        'def f() -> None:\n    """Workers stay CPU-only per storage-discipline."""\n',
    )

    findings = gate.scan_file(source, repo_root=tmp_path)

    assert _slugs(findings) == ["codified-rule-name"]
    assert _texts(findings) == ["storage-discipline"]


def test_the_rule_stem_list_still_matches_the_rules_on_disk(gate: ModuleType) -> None:
    """The gate holds the rule stems as a literal, so they can fall behind.

    Spelling them out is what lets the gate keep working once the harness
    directory is gone, but a literal list silently stops covering a rule added
    after it was written - and a class the gate no longer covers is exactly the
    hole this whole change exists to close. The generated per-provider copies are
    ignored: they are regenerated from one source, so checking one is checking
    all. Product-shipped stems are excluded because they are product names.

    Mutation proving this can fail: add or drop one entry in ``RULE_STEMS``.
    """
    on_disk = {
        path.name.removesuffix(".md")
        for path in (_REPO_ROOT / ".claude" / "rules").glob("*.md")
        if not path.name.endswith(".builtin.md")
    }

    assert set(gate.RULE_STEMS) == on_disk


def test_a_vault_shaped_string_value_is_data_and_never_a_citation(
    gate: ModuleType, tmp_path: Path
) -> None:
    """Fixture filenames are values the indexer is tested against, not pointers.

    This is the carve-out the prose-only scan exists to make. If the gate ever
    starts matching ordinary string values, the corpus the indexer is tested
    against fails the gate wholesale, and the pressure to widen an exclusion
    until the gate sees nothing becomes irresistible.

    Mutation proving this can fail: scan every ``ast.Constant`` for citations
    rather than only the prose positions.
    """
    source = _write(
        tmp_path,
        "module.py",
        f'FIXTURE = "{_STEM}-adr.md"\nPATHS = ["adr/{_STEM}.md"]\nT = "type:adr"\n',
    )

    assert gate.scan_file(source, repo_root=tmp_path) == []


def test_product_vocabulary_and_instructional_prose_are_not_citations(
    gate: ModuleType, tmp_path: Path
) -> None:
    """The product indexes a vault, so it must be able to talk about one.

    Naming the directory it walks, the doc-id prefix it parses and the filter it
    advertises is domain vocabulary. A numbered instruction in a procedure is
    ordinary English. A date with no kebab tail is a date. Each of these was
    weighed against the tree before the patterns were widened; firing on any of
    them would make the gate the thing people route around.

    Mutation proving this can fail: drop the letter requirement from the
    ``dated-vault-stem`` tail, or add ``step \\d+`` to the numbered-container
    pattern.
    """
    source = _write(
        tmp_path,
        "module.py",
        '"""Index ``.vault/`` markdown, parse ``adr/`` doc ids, advertise\n'
        "``type:adr``.\n\n"
        "Step 1: measured 2026-06-02, re-measured over 2026-06-02-2026-07-01.\n"
        'Phase names are warming and running, and vaultspec-rag is the product.\n"""\n',
    )

    assert gate.scan_file(source, repo_root=tmp_path) == []


# The surfaces the walk must reach. Each is a file the gate never visited under
# the include-list enumeration, and the tooling row held a live citation for
# exactly as long as that lasted.
_SURFACES: tuple[str, ...] = (
    "tools/helper.py",
    "scripts/render.py",
    "conftest.py",
    "tests/smoke.py",
    "src/pkg/module.py",
    "docs/guide.md",
    "README.md",
    "pyproject.toml",
    "justfile",
    ".github/workflows/ci.yml",
)


@pytest.mark.parametrize("rel", _SURFACES)
def test_every_product_surface_is_reached_by_the_walk(
    gate: ModuleType, tmp_path: Path, rel: str
) -> None:
    """Which surfaces are reached is as much the gate as which patterns match.

    An unreached surface is invisible from a green run, so this is asserted
    through the collector rather than a per-file scan: no amount of per-file
    testing observes a file the walk never yields.

    Mutation proving this can fail: enumerate a list of roots to visit instead of
    subtracting exclusions from what git tracks, or stop scanning text files for
    citations.
    """
    _git_tree(tmp_path)
    comment = "#" if rel.endswith((".py", ".toml", ".yml", "justfile")) else ""
    _write(tmp_path, rel, f"{comment} See {_STEM} for why.\n")

    active, _deferred, _leaks, _smells = gate.collect_findings(tmp_path)

    assert [(found, slug) for found, _line, slug, _text in active] == [
        (rel, "dated-vault-stem")
    ]


@pytest.mark.parametrize(
    "rel",
    [
        ".vault/adr/note.md",
        ".claude/rules/thing.md",
        ".vaultspec/rules/thing.md",
        "src/vaultspec_rag/tests/quality/rubric.toml",
        "src/vaultspec_rag/builtins/rules/thing.md",
        "CHANGELOG.md",
        "CLAUDE.md",
    ],
)
def test_an_excluded_surface_is_not_scanned(
    gate: ModuleType, tmp_path: Path, rel: str
) -> None:
    """Each exclusion is a place where a vault reference is the subject matter.

    The harness trees, the evaluation rubric and the product's own shipped rule
    text all legitimately name records; the changelog is generated from commit
    subjects, so a finding there is not fixable in the file. Excluding them is a
    decision on the record, which is the only kind of hole worth having.

    Mutation proving this can fail: remove the row's entry from
    ``EXCLUDED_DIRS`` or ``EXCLUDED_FILES``.
    """
    _git_tree(tmp_path)
    _write(tmp_path, rel, f"See {_STEM} for why.\n")

    active, _deferred, _leaks, _smells = gate.collect_findings(tmp_path)

    assert active == []


def test_a_git_ignored_tree_is_not_a_product_surface(
    gate: ModuleType, tmp_path: Path
) -> None:
    """Git decides what is tracked source, because that is git's own notion.

    A filesystem walk cannot: it descends into an ignored vendored tree and fails
    the gate on somebody else's imported release notes, which is a finding no
    developer here can act on.

    Mutation proving this can fail: enumerate with ``Path.rglob`` instead of
    ``git ls-files``.
    """
    _git_tree(tmp_path)
    _write(tmp_path, ".gitignore", "/externals/\n")
    _write(tmp_path, "externals/vendor/CHANGES.md", f"Released {_STEM}.\n")

    active, _deferred, _leaks, _smells = gate.collect_findings(tmp_path)

    assert active == []


def test_a_new_untracked_file_is_scanned_before_it_is_ever_committed(
    gate: ModuleType, tmp_path: Path
) -> None:
    """A citation should be caught in the file that introduces it, not later.

    Enumerating only committed files would let every new file through for one
    commit, which is precisely long enough for the gate to report clean over it.

    Mutation proving this can fail: drop ``--others --exclude-standard`` from the
    git invocation.
    """
    _git_tree(tmp_path)
    _write(tmp_path, "src/pkg/fresh.py", f"# See {_STEM}.\n")

    active, _deferred, _leaks, _smells = gate.collect_findings(tmp_path)

    assert _slugs(active) == ["dated-vault-stem"]


def test_a_real_account_name_is_an_identity_leak(
    gate: ModuleType, tmp_path: Path
) -> None:
    """A home-directory path naming an account names the developer.

    Asserted on the leak bucket rather than the citation bucket: a path leak
    fails the gate through a different branch with a different remediation, and a
    test that only checked "something was found" would pass on either.

    Mutation proving this can fail: widen the placeholder lookahead to any
    account segment.
    """
    # Assembled from two literals on purpose. The path scan matches string
    # VALUES, not only prose, so a whole account path written out here would be
    # a leak in this very file. Keep it split.
    account = "gergely"
    source = _write(tmp_path, "module.py", f'P = "C:/Users/{account}/code/thing"\n')

    leaks, _smells = gate.scan_file_paths(source, repo_root=tmp_path)

    assert _slugs(leaks) == ["user-home-path"]


def test_a_documentation_placeholder_account_is_not_a_leak(
    gate: ModuleType, tmp_path: Path
) -> None:
    """Documentation has to show an operator where their own home directory is.

    A stand-in the reader substitutes reveals no identity, which is the entire
    thing this pattern exists to catch. Excluding the placeholders by name keeps
    documentation editable, where anchoring individual lines would break on the
    next paragraph inserted above them.

    Mutation proving this can fail: delete the placeholder lookahead.
    """
    source = _write(
        tmp_path,
        "guide.md",
        "Snapshots land under `C:\\Users\\me\\.cache`, logs under `/home/you/.log`.\n",
    )

    _citations, leaks, _smells = gate.scan_text(source, repo_root=tmp_path)

    assert leaks == []


def test_the_checkout_carries_no_active_citation_or_identity_leak(
    gate: ModuleType,
) -> None:
    """Regression guard on the tree, not evidence about the gate.

    The cases above are what establish the gate can go red; this one only
    asserts the live checkout is on the clean side of it. Read in isolation it
    would prove nothing at all - which is the shape of failure that filed the
    issue behind this file.
    """
    active, _deferred, leaks, _smells = gate.collect_findings(_REPO_ROOT)

    assert active == [], f"active development-record citation(s): {active}"
    assert leaks == [], f"workstation-identity path leak(s): {leaks}"
