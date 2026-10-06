"""Guard: the committed Qdrant pin tables have one writer in the tests.

The two tables decide which bytes may be installed and run. One declared
test seam, ``pinned_stand_in``, writes a stand-in's digests into them for the
length of a block, so the shipped code can be driven end to end without the
real release. That is a substitution of a trust constant. Three things keep
it from growing or leaking, and each is held here:

* **One writer.** Every Python file in the repository is scanned for a write
  to either table: assigning or deleting an entry, a mutating method, a
  patching helper handed the table or its name, rebinding it, or giving it
  another name to be written through. The one seam, in one function of one
  file, is the only writer allowed. The scan reads the syntax tree, so prose
  that mentions a table does not trip it.
* **Every use declared.** Each file that enters the seam is listed below
  with how many times it names it and why. A new use fails here until it is
  listed, which is the review step the count exists to force.
* **Nothing left behind.** The seam restores the committed digests however
  its block ends, and after every test in the suite both tables are compared
  with a copy of the committed values read from the source file on its own.

What the scan cannot see: a write through a reference it never sees bound,
such as a table returned by a function or stored in a container. The check
after every test is what catches the effect of one.

None of this shows that the committed digests describe the real release.
That is shown where the real release is: by the tool that derives the digests
from the official source, and by runs against the real archive.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ..qdrant_runtime._constants import QDRANT_ASSET_SHA256, QDRANT_EXECUTABLE_SHA256
from ..qdrant_runtime._resolve import asset_for_platform
from ._committed_pins import COMMITTED_PINS, pin_table_drift
from ._stand_in_release import NEW_EXECUTABLE, pinned_stand_in, sha256_hex

pytestmark = [pytest.mark.unit]

_ROOT = Path(__file__).resolve().parents[3]
_SCANNED = ("src", "tools", "dev", "conftest.py")

_TABLES = frozenset(COMMITTED_PINS)
_SEAM = "pinned_stand_in"
#: Every name a file can enter the seam by: the seam, and the one composition
#: of it with a loopback release source, defined beside it.
_SEAM_ENTRIES = frozenset({_SEAM, "served_stand_in"})

#: Where a table may be written, as (file, enclosing function). The tables
#: are bound once each where they are defined, and written in the one seam.
_DEFINED = ("src/vaultspec_rag/qdrant_runtime/_constants.py", "<module>")
_WRITER = ("src/vaultspec_rag/tests/_stand_in_release.py", _SEAM)

#: Methods that change the mapping they are called on.
_MUTATORS = frozenset(
    {"update", "pop", "popitem", "clear", "setdefault", "__setitem__", "__delitem__"}
)
#: Helpers that write to, or replace, what they are handed: methods of a
#: patching object, and the builtins that set or delete an attribute by name.
_PATCHERS = frozenset(
    {"setitem", "delitem", "setattr", "delattr", "dict", "object", "multiple"}
)
_BUILTINS = frozenset({"setattr", "delattr"})

# File -> (times it names the seam outside an import, why it needs it).
_DECLARED_USES: dict[str, tuple[int, str]] = {
    "src/vaultspec_rag/tests/_provisioning_child.py": (
        1,
        "a provisioning run in a child process, killed by its parent, must be "
        "held to the same stand-in the parent pinned; a pin lives in one "
        "process's memory",
    ),
    "src/vaultspec_rag/tests/test_managed_install.py": (
        1,
        "a healthy verdict needs an executable the committed pins vouch for",
    ),
    "src/vaultspec_rag/tests/test_qdrant_install_recovery.py": (
        1,
        "whole provisioning calls over a healthy install, a killed run and an "
        "unreadable executable need the public call to accept a stand-in",
    ),
    "src/vaultspec_rag/tests/test_start_provisioning.py": (
        1,
        "a start that fetches the server, and one that finishes what a killed "
        "install left, need the real provisioner to accept a stand-in release",
    ),
    "src/vaultspec_rag/tests/test_pin_table_writers.py": (
        6,
        "the seam's own tests: that it pins, and that it restores after a "
        "return, a failure, an interrupt and a nested block",
    ),
}


def _names_a_table(node: ast.AST) -> bool:
    """Whether *node* is a reference to one of the tables, bare or qualified."""
    if isinstance(node, ast.Name):
        return node.id in _TABLES
    return isinstance(node, ast.Attribute) and node.attr in _TABLES


def _mentions_a_table(node: ast.AST) -> bool:
    """Whether *node* is a table, or a string that names one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.rpartition(".")[2] in _TABLES
    return _names_a_table(node)


def _stored(node: ast.AST) -> str | None:
    """A table, or an entry of one, as the target of an assignment or deletion."""
    if not isinstance(node, (ast.Subscript, ast.Name, ast.Attribute)):
        return None
    if not isinstance(node.ctx, (ast.Store, ast.Del)):
        return None
    if isinstance(node, ast.Subscript):
        return "assigns or deletes an entry" if _names_a_table(node.value) else None
    return "binds or deletes the table itself" if _names_a_table(node) else None


def _renamed(node: ast.AST) -> str | None:
    """A table given a second name, through which it could then be written."""
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
        if node.value is not None and _names_a_table(node.value):
            return "gives the table another name"
    elif (
        isinstance(node, ast.alias)
        and node.name in _TABLES
        and node.asname not in (None, node.name)
    ):
        return "imports the table under another name"
    return None


def _called_on(node: ast.AST) -> str | None:
    """A call that changes a table, or hands it to something that will."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if isinstance(func, ast.Attribute) and _names_a_table(func.value):
        return f"calls {name}() on the table" if name in _MUTATORS else None
    # A patching helper is reached through whatever provides it; the builtin
    # that copies a mapping shares a name with one and is a plain call.
    patches = (
        name in _PATCHERS if isinstance(func, ast.Attribute) else name in _BUILTINS
    )
    handed = [*node.args, *(keyword.value for keyword in node.keywords)]
    if patches and any(map(_mentions_a_table, handed)):
        return f"hands the table to {name}()"
    return None


def _write_in(node: ast.AST) -> str | None:
    """Say how *node* writes a table, or ``None`` when it does not."""
    return _stored(node) or _renamed(node) or _called_on(node)


def _writes(source: str) -> list[tuple[str, int, str]]:
    """Return every write to a table in *source*: where, the line, and how."""
    found: list[tuple[str, int, str]] = []

    def visit(node: ast.AST, inside: str) -> None:
        how = _write_in(node)
        if how is not None:
            found.append((inside, getattr(node, "lineno", 0), how))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inside = node.name
        for child in ast.iter_child_nodes(node):
            visit(child, inside)

    visit(ast.parse(source), "<module>")
    return found


def _seam_references(source: str) -> int:
    """Count the places *source* names an entry to the seam, imports aside."""
    return sum(
        (isinstance(node, ast.Name) and node.id in _SEAM_ENTRIES)
        or (isinstance(node, ast.Attribute) and node.attr in _SEAM_ENTRIES)
        for node in ast.walk(ast.parse(source))
    )


def _sources_naming(*names: str) -> dict[str, str]:
    """Return the text of every scanned file that mentions one of *names*.

    A file that never spells a name can neither write a table nor enter the
    seam, so only the files that do are parsed. The repository holds over a
    thousand Python files and a handful mention any of these.
    """
    files: list[Path] = []
    for entry in _SCANNED:
        path = _ROOT / entry
        files.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    assert len(files) > 500, f"the scan found only {len(files)} files under {_ROOT}"
    mentioning: dict[str, str] = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        if any(name in text for name in names):
            mentioning[path.relative_to(_ROOT).as_posix()] = text
    return mentioning


def test_nothing_but_the_one_seam_writes_a_pin_table() -> None:
    """Every write to either table is the definition or the seam.

    Mutation: added ``QDRANT_EXECUTABLE_SHA256[asset_for_platform()] = "0"``
    to the body of a test in another module. Observed this test fail, naming
    that file, that function and that line. Then added a second write inside
    the seam's own file, in another function. Observed it fail the same way.
    Restored after each; passes.
    """
    unexpected: list[str] = []
    writers: set[tuple[str, str]] = set()
    for path, text in _sources_naming(*_TABLES).items():
        for inside, line, how in _writes(text):
            writers.add((path, inside))
            if (path, inside) not in (_DEFINED, _WRITER):
                unexpected.append(f"{path}:{line} in {inside}: {how}")

    assert not unexpected, (
        "the committed pin tables may be written only by the one declared "
        "seam; remove these writers, or drive the case through the seam:\n"
        + "\n".join(unexpected)
    )
    # The scan is looking at the real things: it found where the tables are
    # defined and found the seam writing them. A scan that matched nothing
    # would pass the assertion above for the wrong reason.
    assert writers == {_DEFINED, _WRITER}


def test_every_use_of_the_seam_is_declared() -> None:
    """A file may enter the seam only if it is listed here with its reason.

    Mutation: added one more ``with pinned_stand_in():`` block to a listed
    test module. Observed this test fail on that file's count. Restored;
    passes.
    """
    used = {
        path: count
        for path, text in _sources_naming(*_SEAM_ENTRIES).items()
        if path != _WRITER[0] and (count := _seam_references(text))
    }
    declared = {path: count for path, (count, _why) in _DECLARED_USES.items()}

    assert used == declared, (
        "the uses of the pin-table seam changed. A new or extra use is "
        "listed in _DECLARED_USES with why the case cannot be driven without "
        "it; a use that is gone is removed from the list."
    )
    assert all(why.strip() for _count, why in _DECLARED_USES.values())


@pytest.mark.parametrize(
    ("source", "how"),
    [
        ("QDRANT_ASSET_SHA256['a'] = 'b'", "assigns or deletes an entry"),
        ("del consts.QDRANT_EXECUTABLE_SHA256['a']", "assigns or deletes an entry"),
        ("QDRANT_ASSET_SHA256['a'] += 'b'", "assigns or deletes an entry"),
        ("QDRANT_ASSET_SHA256 |= {'a': 'b'}", "binds or deletes the table itself"),
        ("consts.QDRANT_ASSET_SHA256 = {}", "binds or deletes the table itself"),
        ("QDRANT_ASSET_SHA256.update(a='b')", "calls update() on the table"),
        ("consts.QDRANT_EXECUTABLE_SHA256.pop('a')", "calls pop() on the table"),
        ("QDRANT_ASSET_SHA256.clear()", "calls clear() on the table"),
        (
            "monkeypatch.setitem(QDRANT_ASSET_SHA256, 'a', 'b')",
            "hands the table to setitem()",
        ),
        # Spelt in two pieces: these are scanned as text by the guard that
        # counts real substitutions, and neither is one.
        (
            "monkeypatch." + "setattr(consts, 'QDRANT_EXECUTABLE_SHA256', {})",
            "hands the table to setattr()",
        ),
        (
            "monkeypatch." + "setattr('pkg.consts.QDRANT_ASSET_SHA256', {})",
            "hands the table to setattr()",
        ),
        ("patch.dict(QDRANT_ASSET_SHA256, a='b')", "hands the table to dict()"),
        ("table = QDRANT_EXECUTABLE_SHA256", "gives the table another name"),
        (
            "from consts import QDRANT_ASSET_SHA256 as table",
            "imports the table under another name",
        ),
    ],
)
def test_the_scan_sees_each_way_a_table_can_be_written(source: str, how: str) -> None:
    """The scan is only as good as the shapes it knows; each is pinned here.

    Mutation: removed the patching helpers from the scan. Observed the four
    cases that hand a table to one fail, each finding no write. Restored;
    passes.
    """
    assert [found for _inside, _line, found in _writes(source)] == [how]


@pytest.mark.parametrize(
    "source",
    [
        "digest = QDRANT_ASSET_SHA256[asset]",
        "digest = consts.QDRANT_EXECUTABLE_SHA256.get(asset, '')",
        "for asset, digest in QDRANT_EXECUTABLE_SHA256.items(): pass",
        "known = asset in QDRANT_ASSET_SHA256",
        "from consts import QDRANT_ASSET_SHA256, QDRANT_EXECUTABLE_SHA256",
        "text = 'QDRANT_ASSET_SHA256 is read here and never written'",
        "copy = dict(QDRANT_ASSET_SHA256)",
    ],
)
def test_the_scan_leaves_a_read_alone(source: str) -> None:
    assert _writes(source) == []


def _stand_in() -> bytes:
    """An executable no other test pins, so a leak here is told from theirs."""
    return b"an executable only the seam's own tests pin\x00" * 8


class TestTheSeam:
    """What the one writer does to the tables, and that it undoes all of it."""

    def test_it_pins_both_digests_of_this_platform_s_asset_and_nothing_else(
        self,
    ) -> None:
        asset = asset_for_platform()
        executable = _stand_in()

        with pinned_stand_in(executable) as archive:
            pinned_archive = QDRANT_ASSET_SHA256[asset]
            pinned_executable = QDRANT_EXECUTABLE_SHA256[asset]
            others = [line for line in pin_table_drift() if repr(asset) not in line]

        assert pinned_archive == sha256_hex(archive)
        assert pinned_executable == sha256_hex(executable)
        assert pinned_executable != COMMITTED_PINS["QDRANT_EXECUTABLE_SHA256"][asset]
        assert others == []
        assert pin_table_drift() == []

    def test_the_same_executable_pins_the_same_archive_every_time(self) -> None:
        """Two processes that pin one stand-in must agree on its archive."""
        with pinned_stand_in() as first:
            pass
        with pinned_stand_in() as second:
            pass

        assert first == second
        assert NEW_EXECUTABLE not in first, "the archive is compressed"

    @pytest.mark.parametrize(
        "ending",
        [AssertionError("a test body that fails"), KeyboardInterrupt()],
        ids=["a failing test body", "an interrupt"],
    )
    def test_it_restores_the_committed_digests_however_the_block_ends(
        self, ending: BaseException
    ) -> None:
        """A test that fails or is interrupted inside the block leaks nothing.

        Mutation: moved the restore in ``pinned_stand_in`` out of ``finally``
        to after the block. Observed both cases fail on the drift assertion,
        each naming the two entries left holding the stand-in's digests.
        Restored; passes.
        """
        with pytest.raises(type(ending)), pinned_stand_in(_stand_in()):
            assert pin_table_drift() != []
            raise ending

        assert pin_table_drift() == []

    def test_nested_blocks_each_put_back_what_they_found(self) -> None:
        asset = asset_for_platform()
        outer, inner = _stand_in(), _stand_in() + b"and a second one"

        with pinned_stand_in(outer):
            with pinned_stand_in(inner):
                assert QDRANT_EXECUTABLE_SHA256[asset] == sha256_hex(inner)
            assert QDRANT_EXECUTABLE_SHA256[asset] == sha256_hex(outer)

        assert pin_table_drift() == []


class TestTheCommittedTables:
    """What the tables must be when no seam is open. The seam is not used here."""

    def test_the_live_tables_are_exactly_what_the_source_file_commits(self) -> None:
        """The reference is a second reading of the source, sharing no object.

        Run after every other test in this module by its place in the file,
        and after every test in the suite by the check the root fixtures
        make, so a leak anywhere is reported and not carried forward.
        """
        assert COMMITTED_PINS["QDRANT_ASSET_SHA256"] is not QDRANT_ASSET_SHA256
        assert (
            COMMITTED_PINS["QDRANT_EXECUTABLE_SHA256"] is not QDRANT_EXECUTABLE_SHA256
        )
        assert pin_table_drift() == []

    def test_this_platform_s_asset_is_held_to_two_distinct_whole_digests(self) -> None:
        asset = asset_for_platform()
        archive = COMMITTED_PINS["QDRANT_ASSET_SHA256"][asset]
        executable = COMMITTED_PINS["QDRANT_EXECUTABLE_SHA256"][asset]

        for digest in (archive, executable):
            assert len(digest) == 64
            assert set(digest) <= set("0123456789abcdef")
        assert archive != executable
        assert QDRANT_ASSET_SHA256[asset] == archive
        assert QDRANT_EXECUTABLE_SHA256[asset] == executable

    def test_every_asset_has_both_digests(self) -> None:
        assert set(COMMITTED_PINS["QDRANT_ASSET_SHA256"]) == set(
            COMMITTED_PINS["QDRANT_EXECUTABLE_SHA256"]
        )
