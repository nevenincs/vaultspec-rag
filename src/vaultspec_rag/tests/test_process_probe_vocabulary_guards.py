"""Canonical ownership guard tests for the process-probe split."""

from __future__ import annotations

import ast
import collections
import re
import tempfile
from pathlib import Path
from typing import ClassVar

import pytest

from ._process_probe_guard_helpers import (
    _PACKAGE_ROOT,
    _production_sources,
    absolute_import,
    every_production_file,
    module_name,
    parsed_production_sources,
    string_literals,
)

pytestmark = [pytest.mark.unit]


def _option_declarations(tree: ast.Module, path: Path) -> list[tuple[str, str]]:
    declarations: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        declarations.extend(_function_option_declarations(node, path))
    return declarations


def _function_option_declarations(
    node: ast.FunctionDef | ast.AsyncFunctionDef, path: Path
) -> list[tuple[str, str]]:
    return [
        (key, f"{path.name}:{argument.lineno}")
        for argument in [*node.args.args, *node.args.kwonlyargs]
        if argument.annotation is not None
        if (key := " ".join(ast.unparse(argument.annotation).split()))
        if "typer.Option" in key or "typer.Argument" in key
    ]


class TestPinnedAssetNamesAreNamedOnce:
    """Every release asset filename is written once and pinned once.

    The digest table is keyed by asset filename, and the platform resolver
    wrote those filenames out again as literals to pick one. The resolver
    already refused an asset with no committed digest, so a typo could not
    reach a download - but that check only runs for the platform the typo is
    on, so a bad edit surfaced as a provisioning failure on one architecture
    instead of as a bad edit.

    The reverse direction had no check at all, and the two lists do differ:
    six assets are pinned, five are reachable. The x86-64 musl build is pinned
    and no platform selects it. That is deliberate - dropping a reviewed pin is
    how an unpinned asset later becomes reachable - so it is asserted as the
    one known exception rather than left as an unexplained gap.
    """

    #: Pinned but deliberately unreachable; see the constant's comment.
    _UNREACHABLE: ClassVar[frozenset[str]] = frozenset(
        {"qdrant-x86_64-unknown-linux-musl.tar.gz"}
    )

    #: Every pair the resolver accepts today.
    _PLATFORMS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("win32", "amd64"),
        ("win32", "x86_64"),
        ("darwin", "arm64"),
        ("darwin", "aarch64"),
        ("darwin", "x86_64"),
        ("linux", "x86_64"),
        ("linux", "amd64"),
        ("linux", "aarch64"),
        ("linux", "arm64"),
    )

    def test_no_module_but_the_constants_spells_an_asset_filename(self) -> None:
        """A literal asset name anywhere else is a second spelling."""
        pattern = re.compile(r"^qdrant-[a-z0-9_]+-[a-z0-9-]+\.(tar\.gz|zip)$")
        find_offenders: list[str] = []
        for path in every_production_file():
            if path.name == "_constants.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            find_offenders.extend(
                f"{path.name}:{node.lineno} spells {node.value!r}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and pattern.match(node.value)
            )
        assert not find_offenders, (
            f"a release asset filename is spelled outside the pin table at "
            f"{find_offenders}; import the named constant, so the name the digest "
            "is keyed by and the name the resolver picks cannot diverge"
        )

    def test_every_selectable_asset_is_pinned_and_the_gap_is_declared(self) -> None:
        """Both directions, so neither list can drift unnoticed.

        Proven able to fail: adding a pin with no selecting platform, or
        making the musl build selectable, fails the second assertion.

        The first assertion needs the resolver's OWN pin check removed before
        it can be reached - pointing a branch at an unpinned asset raises
        inside ``asset_for_platform`` first, so a one-line mutation fails this
        test on that RuntimeError rather than on the assertion, which proves
        nothing about the assertion. It is deliberately kept as the check that
        survives if that guard is ever loosened.
        """
        from ..qdrant_runtime._constants import QDRANT_ASSET_SHA256
        from ..qdrant_runtime._resolve import asset_for_platform

        selectable = {
            asset_for_platform(platform, machine)
            for platform, machine in self._PLATFORMS
        }
        assert not selectable - set(QDRANT_ASSET_SHA256), (
            "the resolver can select an asset with no committed SHA256 pin"
        )
        assert set(QDRANT_ASSET_SHA256) - selectable == self._UNREACHABLE, (
            "the set of pinned-but-unreachable assets changed; either a "
            "platform gained an asset or a pin became dead - both need saying "
            "out loud rather than drifting"
        )


class TestNoOptionIsDeclaredTwice:
    """No two commands declare the same flag for themselves.

    A repeated ``Annotated[T, typer.Option(...)]`` repeats a contract: the flag
    name, its type, and the sentence an operator reads in ``--help``. Twenty-
    five duplicate declarations had accumulated, and one had already drifted -
    ``--port`` was described two ways, sixteen verbs calling it "Service port
    (defaults to running service)." and ``index``/``search`` calling it "Use
    the service running on this port." for the identical flag and type.

    Nothing fails when that happens. An operator comparing two ``--help``
    screens simply reads a difference that is not there, and the next verb to
    need the flag copies whichever neighbour it happened to look at.

    The package already fixed this once for ``--json``, whose shared constant
    records that thirty-three declarations had reached four wordings. This is
    the same rule applied to the flags that were still spelled per verb.

    Scoped to IDENTICAL declarations on purpose. A companion check asserting
    that one flag name carries one description was written and deleted: it
    fails on sixteen flags, and it is wrong to. ``--port`` names the Qdrant
    HTTP port on one verb, the port ``server start`` binds on another, and the
    port to stop a service by identity on a third; ``--dry-run`` and ``--yes``
    each name what that specific verb previews or confirms. Same flag name,
    genuinely different contracts. Only a repeated declaration - same name,
    same type, same sentence - is evidence of a copy.
    """

    def test_no_annotated_option_declaration_repeats(self) -> None:
        """Two commands wanting one flag share a declaration, or drift."""
        declarations: dict[str, list[str]] = {}
        cli_root = _PACKAGE_ROOT / "cli"
        for path in sorted(cli_root.rglob("*.py")):
            if path.name == "_app.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for key, site in _option_declarations(tree, path):
                declarations.setdefault(key, []).append(site)
        find_offenders = {
            key: sites for key, sites in declarations.items() if len(sites) > 1
        }
        assert not find_offenders, (
            f"these option declarations are written more than once: "
            f"{ {k[:60]: v for k, v in find_offenders.items()} }; declare the "
            "shared ones in _app and annotate with the alias, so one flag "
            "cannot end up documented two ways"
        )


class TestRootPrefixFormatHasOneSpelling:
    """The root-prefix shape is written once, by the module that builds it.

    Four modules recognised the prefix by writing ``r[0-9a-f]{12}_`` out for
    themselves. The twelve is not a free choice: it is the builder's six-byte
    blake2b digest rendered as hex, restated as a digit count somewhere nothing
    connects it to the digest. Widening the digest leaves every reader matching
    a prefix the writer no longer produces, and nothing raises - an unmatched
    collection name just looks like it belongs to no root.

    The fourth copy is why this is checked by shape rather than by string. It
    was ``^r[0-9a-f]{12}_$`` where the others were ``^(r[0-9a-f]{12}_)``, so a
    scan comparing pattern text saw three copies and one unrelated pattern.
    """

    def test_no_module_but_the_builder_writes_the_prefix_shape(self) -> None:
        """Any regex naming a 12-hex run after ``r`` is another copy."""
        shape = re.compile(r"r\[0-9a-f\]\{\d+\}_")
        find_offenders: list[str] = []
        for path in every_production_file():
            if path.name == "_store_models.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            find_offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and shape.search(node.value)
            )
        assert not find_offenders, (
            f"the root-prefix shape is written outside its builder at "
            f"{find_offenders}; use ROOT_COLLECTION_PREFIX_RE, or the digit count "
            "and the builder's digest size drift apart silently"
        )

    def test_the_pattern_matches_what_the_builder_emits(self) -> None:
        """The coupling itself, asserted rather than trusted.

        Proven able to fail: changing ``_ROOT_PREFIX_DIGEST_BYTES`` alone fails
        this, because the builder's output length moves and the pattern -
        derived from the same constant - moves with it only if the derivation
        is real. Hard-coding the pattern back to ``{12}`` fails it too.
        """
        from .._store_models import ROOT_COLLECTION_PREFIX_RE, root_collection_prefix

        emitted = root_collection_prefix(Path(tempfile.gettempdir()))
        assert ROOT_COLLECTION_PREFIX_RE.fullmatch(emitted), emitted
        assert ROOT_COLLECTION_PREFIX_RE.match(emitted + "vault")

    def test_the_delete_gate_rejects_a_trailing_newline(self) -> None:
        """``$`` accepts one; a gate guarding a wipe must not.

        The copy this replaced was ``$``-anchored and matched with ``match``,
        and ``$`` also matches immediately before a trailing newline - so a
        prefix ending in one passed the canonical check. The shared pattern is
        used with ``fullmatch``, which does not.

        Proven able to fail: swapping ``fullmatch`` for ``match`` in
        ``is_canonical_prefix`` fails this on the newline assertion below.
        """
        from ..storage_survey import is_canonical_prefix

        assert is_canonical_prefix("r0123456789ab_")
        assert not is_canonical_prefix("r0123456789ab_\n")
        assert not is_canonical_prefix("")
        assert not is_canonical_prefix("r")


class TestOperatorVerdictVocabularyHasOneHome:
    """The words and exit codes an operator sees are the service domain's.

    The service composes a verdict; the CLI walks its own signal ladder and
    reaches a finer state token - a dead pid told apart from a reused one,
    where the service says ``crashed`` for both. That difference is real and
    stays. What was duplicated is everything around it: three labels typed out
    in both places, and the broker-facing exit codes written as bare integers
    in the entry point while the domain module defined them as constants and
    documented them as a contract.

    Both costs are quiet. Two wordings for one condition means the same daemon
    is explained differently depending on which path an operator arrived
    through. A bare ``4`` in a return tuple is unsearchable, so a contract
    change reaches the constant and misses every literal spelling of it.
    """

    #: Verdict exit codes, and the module allowed to write them as integers.
    _CONTRACT_OWNER = "_status.py"
    _CONTRACT_CODES: ClassVar[frozenset[int]] = frozenset({3, 5})

    def test_no_entry_point_respells_a_verdict_label(self) -> None:
        """A second spelling of a label the service already produces."""
        from ..serviceclient import _status

        owned = {
            _status.LABEL_WARMING,
            _status.LABEL_CRASHED_PORT_SILENT,
            _status.LABEL_CRASHED_HEARTBEAT_STALE,
        }
        find_offenders: list[str] = []
        for path in every_production_file():
            if path.name == self._CONTRACT_OWNER:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            find_offenders.extend(
                f"{path.name}:{node.lineno} spells {node.value!r}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in owned
            )
        assert not find_offenders, (
            f"an operator verdict label is spelled outside the service domain "
            f"at {find_offenders}; import it, so one condition cannot be described "
            "in two wordings depending on which surface reported it"
        )

    def test_the_status_renderer_names_its_exit_codes(self) -> None:
        """The renderer must not restate the contract as bare integers.

        Restricted to the codes that only ever mean a verdict. ``0`` and ``4``
        are excluded deliberately: they are ordinary integers that appear all
        over any module, so requiring a name for them would flag arithmetic
        and indices rather than the contract.
        """
        from ..cli import _status_render

        source = Path(_status_render.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        find_offenders: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            if not isinstance(node.value, ast.Tuple):
                continue
            find_offenders.extend(
                f"line {node.lineno} returns a bare {element.value}"
                for element in node.value.elts
                if isinstance(element, ast.Constant)
                and isinstance(element.value, int)
                and not isinstance(element.value, bool)
                and element.value in self._CONTRACT_CODES
            )
        assert not find_offenders, (
            f"the status renderer returns a verdict exit code as a literal: "
            f"{find_offenders}; use the EXIT_* constant, because a bare integer is "
            "unsearchable when the broker-facing contract changes"
        )


class TestSidecarKeysAreNamedNotSpelled:
    """A reserved sidecar key is written as a literal in exactly one module.

    The code side kept its keys in a module both the writer and the reader
    import. The vault side kept them private to the indexer, so the donor
    reader spelled them out again - and said so, calling itself a mirror of
    keys "private to the vault indexer, which owns the write side". The same
    function imported the code keys from their owner two lines above. A test
    made a third copy, and an integration test a fourth and fifth.

    A mirrored payload key fails in the worst available way: renaming one does
    not raise, it makes the reader's lookup return ``None``, every vault donor
    falls to ineligible, and vector reuse quietly stops. Every answer stays
    correct, there are just fewer of them, so no correctness test notices.

    Checked as literals rather than as names, because the mirror was never a
    shared name - it was the same string typed twice under two spellings
    (``_SCHEMA_KEY`` here, ``_VAULT_POINT_SCHEMA_KEY`` there).
    """

    #: Reserved sidecar keys and the one module each may be spelled in.
    _OWNERS: ClassVar[dict[str, str]] = {
        "__vault_point_schema__": "_vault_meta.py",
        "__vault_content_epoch__": "_vault_meta.py",
        "__code_embed_schema__": "_code_meta.py",
        "__code_content_epoch__": "_code_meta.py",
        "__code_membership_epoch__": "_code_meta.py",
    }

    def test_no_module_but_the_owner_spells_a_reserved_key(self) -> None:
        """A second spelling is a mirror, whatever name it is bound to."""
        find_offenders: list[str] = []
        for path in every_production_file():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant):
                    continue
                if not isinstance(node.value, str):
                    continue
                owner = self._OWNERS.get(node.value)
                if owner is not None and path.name != owner:
                    find_offenders.append(
                        f"{path.name}:{node.lineno} spells {node.value!r} "
                        f"(owned by {owner})"
                    )
        assert not find_offenders, (
            f"a reserved sidecar key is spelled outside the module that owns "
            f"it: {find_offenders}; import the constant, because a renamed key does "
            "not raise - it silently makes every donor ineligible"
        )

    def test_the_reader_and_the_writer_share_one_object(self) -> None:
        """Not equal strings - the same constant, reached from both sides.

        Proven able to fail: rebinding either name in the donor reader to a
        fresh literal of the same text fails this on the identity assertion
        below, which equality would not catch.
        """
        from ..indexer import _donor_candidates, _vault_indexer, _vault_meta

        assert (
            _donor_candidates.VAULT_CONTENT_EPOCH_KEY
            is _vault_meta.VAULT_CONTENT_EPOCH_KEY
        )
        assert (
            _donor_candidates.VAULT_POINT_SCHEMA_KEY
            is _vault_meta.VAULT_POINT_SCHEMA_KEY
        )
        assert (
            _vault_indexer.VAULT_POINT_SCHEMA_KEY is _vault_meta.VAULT_POINT_SCHEMA_KEY
        )
        assert _vault_indexer.VAULT_POINT_SCHEMA is _vault_meta.VAULT_POINT_SCHEMA


class TestManagedLogFiltersHaveOneRule:
    """Which log filters exist, and what makes one empty, is stated once.

    The CLI verb asked the logging domain. The HTTP route had its own copy,
    reading the two query parameters and applying its own strip-and-drop-empty
    test - the same rule, restated at the boundary, in a module whose whole
    contents were that one function.

    Nothing failed while they agreed. The cost is that they had to keep
    agreeing by hand: a third filter, or a change to what counts as empty,
    lands in one and not the other, and then a whitespace-only ``--contains``
    filters nothing over HTTP and everything from the CLI, for the same
    service and the same contract.
    """

    def test_only_the_logging_domain_builds_the_filter_mapping(self) -> None:
        """A second builder of these keys is a second definition of the rule."""
        find_offenders: list[str] = []
        for path in _production_sources():
            if path.name == "logging_config.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Subscript):
                    continue
                target = node.slice
                if (
                    isinstance(node.value, ast.Name)
                    and "filter" in node.value.id.lower()
                    and isinstance(target, ast.Constant)
                    and target.value in {"job_id", "contains"}
                    and isinstance(node.ctx, ast.Store)
                ):
                    find_offenders.append(
                        f"{path.name}:{node.lineno} sets {target.value!r}"
                    )
        assert not find_offenders, (
            f"a managed-log filter mapping is built outside the logging "
            f"domain at {find_offenders}; call managed_log_filters, so the HTTP "
            "boundary and the CLI cannot disagree about what an empty filter is"
        )

    def test_a_whitespace_only_filter_is_dropped_not_carried(self) -> None:
        """The behaviour both copies happened to share, pinned to one home.

        Proven able to fail: dropping the ``.strip()`` test so any truthy
        string is kept fails this on the whitespace assertion below - which is
        the divergence a second copy would eventually introduce, since a bare
        ``if job_id:`` reads as obviously correct.
        """
        from ..logging_config import managed_log_filters

        assert managed_log_filters(job_id="   ", contains="\t") == {}
        assert managed_log_filters(job_id="  j1  ") == {"job_id": "j1"}
        assert managed_log_filters() == {}
        # "0" is falsy-looking to a careless rewrite but is a real filter.
        assert managed_log_filters(contains="0") == {"contains": "0"}


class TestNoFacadeReExportServesOnlyTests:
    """A package ``__init__`` re-exports a private name only if production reads it.

    Twenty-eight such entries had accumulated across the ``cli`` and ``server``
    packages, and not one had a production reader by any route. Production
    already imported each from the module that owns it, so the facade entry
    existed for tests alone - and a symbol reachable only that way tells you
    nothing about the code that ships, while making the package look like the
    home of behaviour defined elsewhere.

    Reads are resolved, not guessed, because two shapes count and missing
    either one gives the wrong answer in opposite directions. A from-import
    must resolve to EXACTLY the facade package. An attribute read must go
    through a name the AST shows bound to that same package - the discipline
    ``server`` uses deliberately, where submodules reach mutable globals via
    ``import vaultspec_rag.server as _m`` so a rebind is observed. Thirty-two
    ``server`` entries are load-bearing for that reason and must survive this.

    Scoped to private names. A public name in a package ``__init__`` is API
    for consumers outside this tree, and no internal reader is expected.
    """

    @staticmethod
    def _absolute_import_aliases(node: ast.Import) -> dict[str, str]:
        """Return vaultspec package aliases established by one import."""
        return {
            entry.asname or entry.name.split(".")[0]: entry.name
            for entry in node.names
            if entry.name.startswith("vaultspec_rag")
        }

    @staticmethod
    def _from_import_reads(
        node: ast.ImportFrom, module: str, is_package: bool
    ) -> tuple[set[tuple[str, str]], dict[str, str]]:
        """Return reads and aliases established by one from-import."""
        target = absolute_import(node, module, is_package)
        reads = {(target, entry.name) for entry in node.names}
        aliases = {
            entry.asname or entry.name: f"{target}.{entry.name}" for entry in node.names
        }
        return reads, aliases

    @classmethod
    def _import_reads(
        cls, tree: ast.Module, module: str, is_package: bool
    ) -> tuple[set[tuple[str, str]], dict[str, str]]:
        """Return direct import reads and the names they bind."""
        reads: set[tuple[str, str]] = set()
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                aliases.update(cls._absolute_import_aliases(node))
            elif isinstance(node, ast.ImportFrom):
                direct_reads, imported_aliases = cls._from_import_reads(
                    node, module, is_package
                )
                reads.update(direct_reads)
                aliases.update(imported_aliases)
        return reads, aliases

    @staticmethod
    def _attribute_reads(
        tree: ast.Module, aliases: dict[str, str]
    ) -> set[tuple[str, str]]:
        """Return attribute reads made through a bound package alias."""
        return {
            (aliases[node.value.id], node.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
        }

    @staticmethod
    def _private_facade_exports(
        tree: ast.Module, package: str, reads: set[tuple[str, str]]
    ) -> list[str]:
        """Return unused private facade imports in one package initializer."""
        used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        exports: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not (node.module or ""):
                continue
            exports.extend(
                f"{package}.{name} (line {node.lineno})"
                for entry in node.names
                if (name := entry.asname or entry.name).startswith("_")
                and not name.startswith("__")
                and name not in used
                and (package, name) not in reads
            )
        return exports

    @staticmethod
    def _facade_reads() -> set[tuple[str, str]]:
        """Return every ``(package, name)`` production reaches through a facade."""
        reads: set[tuple[str, str]] = set()
        for path, tree in parsed_production_sources(every_production_file(), set()):
            module = module_name(path)
            is_package = path.name == "__init__.py"
            direct_reads, aliases = TestNoFacadeReExportServesOnlyTests._import_reads(
                tree, module, is_package
            )
            reads.update(direct_reads)
            reads.update(
                TestNoFacadeReExportServesOnlyTests._attribute_reads(tree, aliases)
            )
        return reads

    def test_no_private_re_export_lacks_a_production_reader(self) -> None:
        reads = self._facade_reads()
        find_offenders: list[str] = []
        for path, tree in parsed_production_sources(every_production_file(), set()):
            if path.name != "__init__.py":
                continue
            package = module_name(path)
            find_offenders.extend(self._private_facade_exports(tree, package, reads))
        assert not find_offenders, (
            f"these private names are re-exported with no production reader: "
            f"{find_offenders}; import them from the module that owns them and "
            "delete the entry, so a test cannot be the only reason one exists"
        )


class TestNoSymbolKeptAliveForTests:
    """No private production symbol exists only because a test calls it.

    ``CodebaseIndexer`` carried ``_resolve_operation_policy`` and
    ``resolve_policy_snapshot`` with byte-identical bodies forwarding to the
    same collaborator. Production used the public one; fourteen test call
    sites used the private one. So the path the tests exercised was not the
    path production ran - which is the whole reason the rule forbids keeping a
    symbol alive for tests.
    """

    #: Client-transport calls that reach a real service route this project's
    #: own CLI has not adopted yet. They are not test conveniences duplicating
    #: a production path - each covers a capability no production caller can
    #: otherwise reach - so deleting them would drop client coverage of a live
    #: route. An entry needs that justification, not merely a passing test.
    _CLIENT_SURFACE: ClassVar[dict[str, str]] = {
        "_try_http_create_job": (
            "creates a job with start_paused and an idempotency key; "
            "_try_http_reindex, the path the CLI uses, has neither parameter, "
            "so no production caller can create a paused job"
        ),
    }

    @staticmethod
    def _source_outside_dunder_all(text: str, tree: ast.Module) -> str:
        """Return *text* with the lines of every ``__all__`` assignment dropped.

        An ``__all__`` listing is a declaration of intent, not a use. Counting
        it as one hid an exported symbol that nothing imported and only tests
        called - the case this test exists to catch.
        """
        exported = [
            (node.lineno, node.end_lineno or node.lineno)
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
        ]
        return "\n".join(
            line
            for number, line in enumerate(text.split("\n"), start=1)
            if not any(lo <= number <= hi for lo, hi in exported)
        )

    @staticmethod
    def _private_function_definitions(tree: ast.Module) -> list[tuple[str, int]]:
        """Return the ``(name, line)`` of every single-underscore function."""
        return [
            (node.name, node.lineno)
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("_")
            and not node.name.startswith("__")
        ]

    def test_no_private_symbol_is_reachable_only_from_tests(self) -> None:
        definitions: dict[str, list[str]] = {}
        production: list[str] = []
        for path in _production_sources():
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            production.append(self._source_outside_dunder_all(text, tree))
            for name, lineno in self._private_function_definitions(tree):
                definitions.setdefault(name, []).append(
                    f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{lineno}"
                )

        tests_dir = _PACKAGE_ROOT / "tests"
        test_blob = "\n".join(
            p.read_text(encoding="utf-8") for p in tests_dir.rglob("*.py")
        )
        production_blob = "\n".join(production)

        # Count identifiers once per blob rather than scanning both blobs once
        # per symbol. A `\b`-anchored search for an identifier matches exactly
        # the `\w+` tokens equal to it, so the tally is the same one the
        # per-symbol regex produced - but it is read off a dict instead of
        # re-walking megabytes of source for every name. The old shape was
        # quadratic in a way that grew with the codebase, and at ~1600 private
        # symbols over ~7 MB of source it cost over two minutes on its own.
        production_mentions = collections.Counter(re.findall(r"\w+", production_blob))
        test_mentions = collections.Counter(re.findall(r"\w+", test_blob))
        orphans = {
            name: sites
            for name, sites in definitions.items()
            # every production mention minus the definition lines themselves
            if production_mentions[name] - len(sites) == 0 and test_mentions[name]
        }

        unexplained = {
            name: sites
            for name, sites in orphans.items()
            if name not in self._CLIENT_SURFACE
        }
        assert not unexplained, (
            f"private symbol(s) reachable only from tests: {unexplained}. "
            "Delete them and repoint the tests at the production entry point - "
            "a test-only path proves nothing about the path production runs"
        )


class TestSchemaDeclarationsAreNotCopied:
    """A payload-index declaration lives in ``store_schema``, nowhere else.

    ``_store_search._build_document_filter`` re-listed the six document
    keyword indexes its own docstring said it must take from the schema. A
    keyword index added to the schema would have been rejected there as an
    unknown filter key - logged as a warning, the filter silently dropped, and
    the search returning UNFILTERED results rather than failing.
    """

    @staticmethod
    def _copied_schema_sets(
        tree: ast.Module, declared: dict[str, frozenset[str]], filename: str
    ) -> list[str]:
        """Return schema-index collections copied into one production file."""
        find_offenders: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Set | ast.Tuple | ast.List):
                continue
            literal = string_literals(node)
            if len(literal) < 2 or len(literal) != len(node.elts):
                continue
            find_offenders.extend(
                f"{filename}:{node.lineno} == {name}"
                for name, values in declared.items()
                if frozenset(literal) == values
            )
        return find_offenders

    def test_no_module_relists_a_schema_index_set(self) -> None:
        from .. import store_schema

        declared: dict[str, frozenset[str]] = {
            name: frozenset(getattr(store_schema, name))
            for name in dir(store_schema)
            if name.endswith(("_KEYWORD_INDEXES", "_INTEGER_INDEXES"))
        }
        assert declared, "store_schema declares no index sets; has it moved?"

        find_offenders = [
            offender
            for path, tree in parsed_production_sources(
                _production_sources(), {"store_schema.py"}
            )
            for offender in self._copied_schema_sets(
                tree, declared, path.relative_to(_PACKAGE_ROOT).as_posix()
            )
        ]
        assert not find_offenders, (
            f"schema index set copied at {find_offenders}; import it from "
            "store_schema so a new index reaches every reader"
        )
