"""Canonical ownership guard tests for the process-probe split."""

from __future__ import annotations

import ast
import hashlib
import os
import tempfile
from pathlib import Path

import pytest

from ._process_probe_guard_helpers import (
    _PACKAGE_ROOT,
    _production_sources,
    is_attr_call,
)

pytestmark = [pytest.mark.unit]


def _collection_vocabulary_offenders(
    vocabularies: dict[str, frozenset[str]],
) -> list[str]:
    find_offenders: list[str] = []
    for path in _production_sources():
        if path.name == "store_schema.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - parsed elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Tuple | ast.List | ast.Set):
                continue
            literals = {
                element.value
                for element in node.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
            find_offenders.extend(
                f"{path.name}:{node.lineno} re-lists {name}"
                for name, keys in vocabularies.items()
                if keys <= literals
            )
    return find_offenders


def _literal_enum_offenders(vocabularies: dict[str, frozenset[str]]) -> list[str]:
    find_offenders: list[str] = []
    for path in _production_sources():
        if path.name == "job_models.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - parsed elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript) or not _literal_subscript(node):
                continue
            literals = _literal_strings(node.slice)
            find_offenders.extend(
                f"{path.name}:{node.lineno} restates {name}"
                for name, members in vocabularies.items()
                if members and members == literals
            )
    return find_offenders


def _literal_subscript(node: ast.Subscript) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "Literal"
    )


def _literal_strings(node: ast.expr) -> frozenset[str]:
    elements = node.elts if isinstance(node, ast.Tuple) else [node]
    return frozenset(
        element.value
        for element in elements
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    )


def _repeated_return_offenders() -> list[str]:
    find_offenders: list[str] = []
    for path in _production_sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - parsed elsewhere
            continue
        for function in ast.walk(tree):
            if isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                find_offenders.extend(_repeated_returns(path, function))
    return find_offenders


def _repeated_returns(
    path: Path, function: ast.FunctionDef | ast.AsyncFunctionDef
) -> list[str]:
    return [
        f"{path.name}:{statement.lineno} in {function.name}()"
        for statement, following in zip(function.body, function.body[1:], strict=True)
        if _same_guarded_return(statement, following)
    ]


def _same_guarded_return(statement: ast.stmt, following: ast.stmt) -> bool:
    if not (
        isinstance(statement, ast.If)
        and not statement.orelse
        and len(statement.body) == 1
        and isinstance(statement.body[0], ast.Return)
        and isinstance(following, ast.Return)
    ):
        return False
    guarded, fallback = statement.body[0].value, following.value
    return (
        guarded is not None
        and fallback is not None
        and ast.dump(guarded) == ast.dump(fallback)
    )


def _parse_error_envelope_offenders() -> list[str]:
    find_offenders: list[str] = []
    for path in _production_sources():
        if path.name == "_source_types.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - parsed elsewhere
            continue
        find_offenders.extend(
            f"{path.name}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Dict) and _is_parse_error_envelope(node)
        )
    return find_offenders


def _is_parse_error_envelope(node: ast.Dict) -> bool:
    names = {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    return {"ok", "message"} <= names and any(
        key is None
        and isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "as_payload"
        for key, value in zip(node.keys, node.values, strict=True)
    )


def _literal_collection_sites() -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for path in _production_sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - parsed elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Tuple | ast.List | ast.Set | ast.Dict):
                continue
            if _literal_collection(node):
                seen.setdefault(ast.unparse(node), []).append(
                    f"{path.name}:{node.lineno}"
                )
    return seen


def _literal_collection(node: ast.Tuple | ast.List | ast.Set | ast.Dict) -> bool:
    elements = node.keys if isinstance(node, ast.Dict) else node.elts
    present = [element for element in elements if element is not None]
    return len(present) >= 3 and all(
        isinstance(element, ast.Constant) for element in present
    )


class TestSearchFilterVocabularyHasOneHome:
    """Which payload keys a search may filter on is declared once.

    ``store_schema`` opens by claiming the shape "cannot drift between the
    writer, the reader, the wire, and the reference" - and that holds for
    the store owners, which build payloads and index sets from it. The FILTER side
    did not: three builders and a validator each re-listed the key names.

    The document filter learned why first. It re-listed its keys, so a keyword
    index the schema had added was rejected as unknown and the condition was
    dropped - handing back UNFILTERED results to a caller who had asked to
    narrow. Its fix stopped at that one builder; the code filter and the
    validator kept their copies until now.
    """

    def test_every_filter_key_is_backed_by_an_index(self) -> None:
        """A filter key with no index is a full scan or silently unsupported.

        Proven able to fail: adding an unindexed name to any of the three
        tuples fails this test on the unbacked list below.
        """
        from .. import store_schema

        for keys, indexes, label in (
            (store_schema.CODE_FILTER_KEYS, store_schema.CODE_KEYWORD_INDEXES, "code"),
            (
                store_schema.VAULT_FILTER_KEYS,
                store_schema.VAULT_KEYWORD_INDEXES,
                "vault",
            ),
            (
                store_schema.DOCUMENT_FILTER_KEYS,
                store_schema.DOCUMENT_KEYWORD_INDEXES,
                "document",
            ),
        ):
            unbacked = [
                key
                for key in keys
                if store_schema.FILTER_KEY_PAYLOAD_FIELD.get(key, key) not in indexes
            ]
            assert not unbacked, (
                f"{label} filter keys with no payload index behind them: "
                f"{unbacked}; index the field or drop it from the vocabulary"
            )

        # DOCUMENT_QUERY_FILTER_KEYS splats the argument set, so containment
        # between the two holds by construction and asserting it would prove
        # nothing. What is NOT guaranteed is that the keys it adds on top are
        # indexed - the loop above only walks the argument set - so that is
        # the assertion worth making.
        unbacked_query_keys = [
            key
            for key in store_schema.DOCUMENT_QUERY_FILTER_KEYS
            if key not in store_schema.DOCUMENT_KEYWORD_INDEXES
        ]
        assert not unbacked_query_keys, (
            f"query-token filter keys with no payload index: "
            f"{unbacked_query_keys}; the store will reject them as unknown"
        )

    def test_no_module_relists_the_filter_vocabulary(self) -> None:
        """A collection literal holding the vocabulary is a second copy of it.

        Scoped to collection literals on purpose: these field names appear all
        over the search path as keyword arguments, payload keys and dataclass
        fields, and those are uses of one field, not a restatement of the set.
        What matters is a tuple or set that enumerates the vocabulary, because
        that is what gets consulted as a whitelist and then goes stale.
        """
        from .. import store_schema

        vocabularies: dict[str, frozenset[str]] = {
            "CODE_FILTER_KEYS": frozenset(store_schema.CODE_FILTER_KEYS),
            "VAULT_FILTER_KEYS": frozenset(store_schema.VAULT_FILTER_KEYS),
            "DOCUMENT_FILTER_KEYS": frozenset(store_schema.DOCUMENT_FILTER_KEYS),
            "DOCUMENT_QUERY_FILTER_KEYS": frozenset(
                store_schema.DOCUMENT_QUERY_FILTER_KEYS
            ),
        }
        find_offenders = _collection_vocabulary_offenders(vocabularies)
        assert not find_offenders, (
            f"{find_offenders}; import the tuple from store_schema so a key added "
            "to the schema cannot be rejected as unknown by a stale copy"
        )

    def test_the_code_filter_admits_exactly_the_declared_keys(self) -> None:
        """The builder must read the schema, not a list of its own."""
        import inspect

        from .._store_search import _VaultSearchMixin

        source = inspect.getsource(_VaultSearchMixin._build_code_filter)
        assert "CODE_FILTER_KEYS" in source, (
            "the code filter must take its whitelist from store_schema, the "
            "same way the document filter does"
        )


class TestJsonOptionHasOneDeclaration:
    """Every verb's ``--json`` flag is declared in one place.

    Thirty-three verbs declared it for themselves and had reached four
    wordings and two declaration styles: the storage verbs were still on the
    pre-``Annotated`` form with a terser sentence, so ``--help`` described the
    same flag differently depending on which verb an operator ran it on.

    One wording is deliberately kept separate. The lifecycle verbs promise
    exactly one structured envelope on every exit path, success or failure -
    a stronger contract than "machine-readable output", not a reworded one.
    """

    def test_no_verb_spells_the_json_help_text(self) -> None:
        """Composing on the shared sentence is fine; restating it is not.

        Keyed on the exact canonical sentences rather than the words they
        start with: a first attempt matched any string opening "Emit one
        structured" and flagged a dry-run docstring that happens to begin the
        same way.
        """
        from ..cli._app import JSON_ENVELOPE_OPTION_HELP, JSON_OPTION_HELP

        sentences = (JSON_OPTION_HELP, JSON_ENVELOPE_OPTION_HELP)
        find_offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_app.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if any(f'"{sentence}' in line for sentence in sentences)
        ]
        assert not find_offenders, (
            f"a hand-written --json help string at {find_offenders}; annotate the "
            "parameter with JsonMode or JsonEnvelopeMode, or compose on "
            "JSON_OPTION_HELP when the verb has more to say"
        )

    def test_no_verb_builds_its_own_json_option(self) -> None:
        """A second ``typer.Option("--json", ...)`` is a second declaration."""
        find_offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_app.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call) and is_attr_call(node, "typer", "Option")
                ):
                    continue
                if not any(
                    isinstance(arg, ast.Constant) and arg.value == "--json"
                    for arg in node.args
                ):
                    continue
                # Composing on a canonical constant is the supported way for a
                # verb to say more; restating the sentence is not.
                composes = any(
                    isinstance(inner, ast.Name)
                    and inner.id in {"JSON_OPTION_HELP", "JSON_ENVELOPE_OPTION_HELP"}
                    for inner in ast.walk(node)
                )
                if not composes:
                    find_offenders.append(f"{path.name}:{node.lineno}")
        assert not find_offenders, (
            f"a second --json option declaration at {find_offenders}; use the "
            "JsonMode / JsonEnvelopeMode annotations from _app"
        )

    def test_the_two_contracts_stay_distinct(self) -> None:
        """Flattening the lifecycle promise into the general one loses it.

        Proven able to fail: pointing JSON_ENVELOPE_OPTION_HELP at
        JSON_OPTION_HELP fails this test on the inequality below.
        """
        from ..cli._app import JSON_ENVELOPE_OPTION_HELP, JSON_OPTION_HELP

        assert JSON_ENVELOPE_OPTION_HELP != JSON_OPTION_HELP
        assert "one structured" in JSON_ENVELOPE_OPTION_HELP


class TestOneVocabularyHasOneType:
    """No two enums carry the same member set.

    ``ProvisionAction`` existed twice - once in the install front door, once in
    the qdrant runtime - with identical members, each docstring saying it
    "mirrors the project-wide sync vocabulary" that neither owned. Keeping the
    mirror aligned needed a six-entry translation whose every entry mapped a
    member onto the member of the same name.

    An identity map is the clearest signal two types are one type, and it has
    to be edited whenever either side gains a member: a missed edit raises
    ``KeyError`` the first time the new outcome occurs, on the least-tested
    path there is.
    """

    def test_no_two_enums_share_a_member_set(self) -> None:
        import collections

        by_members: collections.defaultdict[frozenset[str], list[str]] = (
            collections.defaultdict(list)
        )
        for path in _production_sources():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if not any(
                    isinstance(base, ast.Name) and "Enum" in base.id
                    for base in node.bases
                ):
                    continue
                values = {
                    stmt.value.value
                    for stmt in node.body
                    if isinstance(stmt, ast.Assign)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                }
                # Two-member enums are too small for a shared set to mean
                # anything; a boolean-ish pair collides by coincidence.
                if len(values) >= 3:
                    by_members[frozenset(values)].append(f"{path.name}:{node.name}")
        # tuple(), not sorted(): a list is unhashable, so the dict
        # comprehension raised TypeError instead of reporting - which only
        # showed up when a twin actually existed.
        twins = {
            tuple(sorted(members)): names
            for members, names in by_members.items()
            if len(names) > 1
        }
        assert not twins, (
            f"enums with identical member sets: {twins}; one vocabulary is one "
            "type, or the copies need a hand-written translation that goes "
            "stale the moment either side gains a member"
        )


class TestDesiredJobStateHasOneStatement:
    """The operator-intent vocabulary is stated by its enum and nowhere else.

    ``DesiredJobState`` has three members, and they were written out five
    times: the enum, two ``Literal`` aliases mirroring it for typing (one
    sharing the enum's own name), a runtime membership set in the HTTP route,
    and again inside that route's error sentence.

    The set was the one that mattered. The route already called
    ``DesiredJobState(state)`` two lines further down, so the enum was the
    real validator and the set was a pre-check restating it - a fourth member
    would have been accepted by the domain and rejected at the API boundary
    with ``invalid_desired_state``.
    """

    def test_no_module_relists_the_desired_states(self) -> None:
        from ..job_models import DesiredJobState

        members = frozenset(member.value for member in DesiredJobState)
        find_offenders: list[str] = []
        for path in _production_sources():
            if path.name == "job_models.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Tuple | ast.List | ast.Set):
                    continue
                literals = {
                    element.value
                    for element in node.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                }
                if members <= literals:
                    find_offenders.append(f"{path.name}:{node.lineno}")
        assert not find_offenders, (
            f"the desired-state vocabulary is relisted at {find_offenders}; check "
            "membership against DesiredJobState so a new intent is not "
            "accepted by the domain and refused at the route"
        )

    def test_the_route_admits_exactly_the_declared_states(self) -> None:
        """Adding a member must widen the route with no edit to the route.

        Proven able to fail: restoring the literal set in ``_set_desired_state``
        fails the relist scan above, and pinning this assertion to today's
        three members would pass a stale check - so it asks the module for
        them instead.
        """
        import inspect

        from ..job_models import DesiredJobState
        from ..server import _routes

        source = inspect.getsource(_routes)
        assert "set(DesiredJobState)" in source, (
            "the route must test membership against the enum, not a literal set"
        )
        # The sentence an operator reads is built from the same members.
        assert all(
            f"'{member}'" in source or "for member in DesiredJobState" in source
            for member in DesiredJobState
        )


class TestStatusDirHasOneResolver:
    """The managed service directory is resolved in one place.

    Nine sites resolved it: five inline, plus named helpers in the manifest
    and the discovery client. They had settled on two spellings -
    ``Path(cfg.status_dir)`` and ``Path(str(cfg.status_dir))``. The attribute
    is a ``str``, so both are identical and the ``str()`` was defensive typing
    that spread by copying rather than by need.

    One resolver stays separate, and its own docstring says why:
    ``config._status_dir_path`` reads the environment DIRECTLY because it
    belongs to the layer that feeds the config. Every consumer goes through
    the config instead, so a ``--status-dir`` override on the command line is
    honoured - the manifest helper's docstring warned that reading the
    environment there would "silently ignore a --status-dir override and split
    the manifest from the rest of the service's durable state".
    """

    def test_no_module_resolves_the_status_dir_itself(self) -> None:
        """A consumer builds the path from the config, or it drifts.

        Proven able to fail: restoring the inline expression in any consumer
        fails this test on the offender list below.
        """
        find_offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.relative_to(_PACKAGE_ROOT).as_posix() != "config/_settings.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "status_dir)" in line and ".expanduser()" in line
        ]
        assert not find_offenders, (
            f"the status directory is resolved inline at {find_offenders}; call "
            "config.managed_status_dir so a --status-dir override reaches "
            "every file the service keeps there"
        )

    def test_every_managed_path_sits_under_the_one_directory(self) -> None:
        """The files the service keeps must land in the same place.

        Splitting them is the failure the manifest helper's docstring
        describes: an override honoured by some writers and not others leaves
        durable state in two directories, one of which nothing reads.
        """
        from ..config._settings import managed_status_dir
        from ..serviceclient._discovery import _status_file
        from ..storage_manifest import manifest_path

        root = managed_status_dir()
        for path in (_status_file(), manifest_path()):
            assert path.parent == root, (path, root)


class TestWorkspaceLayoutHasOneOwner:
    """Where the workspace keeps its files is declared once.

    ``.vaultspec`` was spelled thirty-one times across five modules, and the
    names inside it fared no better - ``rules`` seven times, ``mcps`` six,
    ``mcp-ownership.json`` four. Nothing owned the layout, so installing it,
    projecting it, uninstalling it and seeding a synthetic copy each carried
    their own idea of what it contains.

    Two of those ideas were the same six directories written out twice: the
    scaffolder's list and the topology projection's. A directory added to one
    and not the other is how a projected workspace comes out missing a tree
    the real one has - and the projection exists precisely to be a faithful
    copy.
    """

    def test_no_module_spells_a_workspace_path(self) -> None:
        find_offenders = [
            f"{path.name}:{number}"
            for path in _production_sources()
            if path.name != "_workspace_layout.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if '".vaultspec"' in line or '".vault"' in line
        ]
        assert not find_offenders, (
            f"a workspace path spelled inline at {find_offenders}; join the "
            "constants from _workspace_layout so the install, the projection "
            "and the uninstall cannot disagree about what a workspace is"
        )

    def test_the_projection_covers_what_the_scaffolder_creates(self) -> None:
        """The two lists must be one list, not two that happen to match.

        Proven able to fail: pinning either side to its own tuple fails this
        on the identity assertion below. Comparing today's six names would
        pass two hand-written lists for exactly as long as nobody edited one.
        """
        from .._workspace_layout import workspace_directories
        from ..commands._mcp_topology import _WORKSPACE_CONTAINERS

        assert tuple(_WORKSPACE_CONTAINERS) == tuple(workspace_directories())

        import inspect

        from ..commands import _workspace

        source = inspect.getsource(_workspace._ensure_workspace_dirs)
        assert "workspace_directories()" in source, (
            "the scaffolder must build from the shared tuple, or it and the "
            "projection drift the next time either gains a directory"
            "projection drift the next time either gains a directory"
        )


class TestJobVocabulariesHaveOneStatement:
    """The job enums are the only statement of their own members.

    ``DesiredJobState`` was fixed three iterations ago and its siblings were
    not, because that pass looked at one enum instead of the shape. ``JobMode``
    existed twice - the domain ``StrEnum`` and a ``Literal`` of the same name
    in the service client, which the server's availability adapter imported in
    preference to the domain's. ``JobSource``'s four members were restated as
    a ``Literal`` in the jobs module, and the route enumerated ``JobMode``'s
    two members by hand rather than asking the enum.
    """

    def test_no_literal_restates_a_job_enum(self) -> None:
        """A ``Literal`` mirroring an enum is a second declaration of it."""
        from ..job_models import DesiredJobState, JobMode, JobSource

        vocabularies = {
            name: frozenset(member.value for member in enum)
            for name, enum in (
                ("JobMode", JobMode),
                ("JobSource", JobSource),
                ("DesiredJobState", DesiredJobState),
            )
        }
        find_offenders = _literal_enum_offenders(vocabularies)
        assert not find_offenders, (
            f"{find_offenders}; annotate with the enum so a new member is legal "
            "everywhere at once instead of being refused by whichever mirror "
            "was not updated"
        )

    def test_no_route_enumerates_a_job_enum_by_hand(self) -> None:
        """Membership comes from the enum, so a new member widens the route.

        Proven able to fail: restoring either literal member set in the job
        routes fails this on the offender list below.
        """
        import inspect

        from ..server import _routes

        source = inspect.getsource(_routes)
        for enum_name in ("JobMode", "DesiredJobState"):
            assert f"set({enum_name})" in source, (
                f"the route must test membership against {enum_name} rather "
                "than listing its members, or a new member is accepted by the "
                "domain and refused at the API boundary"
            )


class TestNoTwoModulesGrewTheSameHelper:
    """No two unrelated modules define the same function with the same body.

    The other guards here catch a copy that keeps its shape (the structural
    scan) or one that keeps its name (the alias scan). This catches the case
    neither sees on its own: two modules with no import path between them,
    each having grown a helper of the same name and the same body, because
    neither could see the other's.

    "Unrelated" is resolved rather than guessed. An earlier version of this
    analysis matched module STEMS, so ``api`` importing ``.search`` looked
    like a link to ``search._searcher`` and hid pairs behind false ones; it
    also counted methods as functions, so a facade function looked like a copy
    of the method it delegates to. Both cost a real finding to a false one.
    """

    @staticmethod
    def _shape(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, int]:
        """Return a name-blind hash of *node*'s body, and its statement count."""
        body = [
            statement
            for statement in node.body
            if not (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
            )
        ]

        class _Blind(ast.NodeTransformer):
            def visit_Name(self, node: ast.Name) -> ast.AST:
                return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

            def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
                self.generic_visit(node)
                return ast.copy_location(
                    ast.Attribute(value=node.value, attr="_", ctx=node.ctx), node
                )

            def visit_Constant(self, node: ast.Constant) -> ast.AST:
                return ast.copy_location(ast.Constant(value=None), node)

            def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.AST:
                # An ``except ... as`` alias is a bare string on the handler,
                # not a Name node, so the visitors above never reached it. Two
                # byte-identical bodies that spelled the caught exception
                # differently therefore hashed differently, and one such pair
                # sat undetected in the tree until a separate scan found it.
                self.generic_visit(node)
                node.name = "_" if node.name else None
                return node

        count = sum(
            1
            for _ in ast.walk(ast.Module(body=body, type_ignores=[]))
            if isinstance(_, ast.stmt)
        )
        blinded = ast.Module(
            body=[_Blind().visit(ast.parse(ast.unparse(s)).body[0]) for s in body],
            type_ignores=[],
        )
        return hashlib.sha256(ast.dump(blinded).encode()).hexdigest(), count

    @staticmethod
    def _reached_modules(tree: ast.Module, owner: list[str], package: str) -> set[str]:
        """Return every in-package module this one imports, at any nesting."""
        reached: set[str] = set()
        for node in ast.walk(tree):
            reached.update(
                TestNoTwoModulesGrewTheSameHelper._import_targets(node, owner, package)
            )
        return reached

    @staticmethod
    def _import_targets(node: ast.AST, owner: list[str], package: str) -> set[str]:
        if isinstance(node, ast.Import):
            return {
                alias.name for alias in node.names if alias.name.startswith(package)
            }
        if not isinstance(node, ast.ImportFrom):
            return set()
        target = TestNoTwoModulesGrewTheSameHelper._import_target(node, owner)
        if not target.startswith(package):
            return set()
        return {target, *(f"{target}.{alias.name}" for alias in node.names)}

    @staticmethod
    def _import_target(node: ast.ImportFrom, owner: list[str]) -> str:
        if not node.level:
            return node.module or ""
        depth = len(owner) - (node.level - 1) if node.level > 1 else len(owner)
        base = owner[:depth]
        return ".".join([*base, node.module]) if node.module else ".".join(base)

    def _helper_index(
        self, package: str
    ) -> tuple[dict[str, set[str]], dict[str, list[tuple[str, int, str]]]]:
        imports: dict[str, set[str]] = {}
        defined: dict[str, list[tuple[str, int, str]]] = {}
        for path in _production_sources():
            module = self._module_name(path, package)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            imports[module] = self._reached_modules(
                tree, module.split(".")[:-1], package
            )
            self._index_defined_helpers(tree, module, defined)
        return imports, defined

    @staticmethod
    def _module_name(path: Path, package: str) -> str:
        relative = path.relative_to(_PACKAGE_ROOT).with_suffix("")
        return ".".join(
            [package, *(part for part in relative.parts if part != "__init__")]
        )

    def _index_defined_helpers(
        self,
        tree: ast.Module,
        module: str,
        defined: dict[str, list[tuple[str, int, str]]],
    ) -> None:
        for node in ast.walk(tree):
            entry = self._helper_site(node, module)
            if entry is not None:
                name, site = entry
                defined.setdefault(name, []).append(site)

    def _helper_site(
        self, node: ast.AST, module: str
    ) -> tuple[str, tuple[str, int, str]] | None:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return None
        first = node.args.args[0].arg if node.args.args else ""
        if first in {"self", "cls"} or node.name.startswith("__"):
            return None
        shape, count = self._shape(node)
        return (node.name, (module, node.lineno, shape)) if count >= 3 else None

    @classmethod
    def _reaches(
        cls,
        imports: dict[str, set[str]],
        source: str,
        target: str,
        seen: set[str] | None = None,
    ) -> bool:
        seen = set() if seen is None else seen
        if source == target or target in imports.get(source, ()):
            return True
        if source in seen:
            return False
        seen.add(source)
        return any(
            cls._reaches(imports, step, target, seen)
            for step in imports.get(source, ())
            if step in imports
        )

    @classmethod
    def _unrelated_duplicate_helpers(
        cls,
        imports: dict[str, set[str]],
        defined: dict[str, list[tuple[str, int, str]]],
    ) -> list[str]:
        find_offenders: list[str] = []
        for name, sites in sorted(defined.items()):
            for index, (module, line, shape) in enumerate(sites):
                for other, other_line, other_shape in sites[index + 1 :]:
                    if cls._unrelated_twins(imports, module, other, shape, other_shape):
                        find_offenders.append(
                            f"{name}: {module}:{line} and {other}:{other_line}"
                        )
        return find_offenders

    @classmethod
    def _unrelated_twins(
        cls,
        imports: dict[str, set[str]],
        module: str,
        other: str,
        shape: str,
        other_shape: str,
    ) -> bool:
        return (
            module != other
            and shape == other_shape
            and not cls._reaches(imports, module, other)
            and not cls._reaches(imports, other, module)
        )

    def test_no_unrelated_pair_shares_a_name_and_a_body(self) -> None:
        package = "vaultspec_rag"
        imports, defined = self._helper_index(package)
        find_offenders = self._unrelated_duplicate_helpers(imports, defined)
        assert not find_offenders, (
            f"the same helper grew twice in modules that cannot see each "
            f"other: {find_offenders}; give it one home both can import"
        )


class TestNoGuardedReturnRepeatsItsFallback:
    """A guarded return whose value equals the fallback decides nothing.

    ``_network_label`` took ``pid_alive`` and branched on it to the string its
    fallback already returned, so the argument could not change the answer.
    The reader of that code sees three outcomes; the operator gets two. Either
    the branch was meant to say something and does not, or it is dead - and
    both readings need the same edit.

    Not the same defect as the structural scan's: that one compares two
    FUNCTIONS. This compares two branches inside one, which no cross-function
    comparison can reach.
    """

    def test_no_branch_returns_what_the_fallback_returns(self) -> None:
        find_offenders = _repeated_return_offenders()
        assert not find_offenders, (
            f"a guarded return repeats its fallback at {find_offenders}; the "
            "condition cannot change the answer, so either the branch owes a "
            "different one or it and whatever it tests are dead"
        )


class TestParseErrorEnvelopeHasOneShape:
    """A rejected source type is reported in one envelope, built by the error.

    Five call sites assembled it: two HTTP routes and three service-client
    calls, each spreading ``as_payload()`` into the same three keys. The
    exception already knew its kind and how it reads; what it did not own was
    how it gets reported, so every new caller learned the shape by copying an
    older one - and a caller copying a stale example reports a shape the
    others do not.

    Deliberately not caught here: the job-create route classifies the same
    exception as ``invalid_job_spec`` and routes it through the jobs envelope
    helper. A bad source inside a job spec is a job-spec error, so that is a
    different report, not a copy of this one.
    """

    def test_no_module_assembles_the_parse_error_envelope(self) -> None:
        find_offenders = _parse_error_envelope_offenders()
        assert not find_offenders, (
            f"the parse-error envelope is assembled by hand at {find_offenders}; "
            "call SourceTypeParseError.as_error_envelope so every adapter "
            "reports the rejection the same way"
        )

    def test_the_envelope_carries_what_the_adapters_relied_on(self) -> None:
        """The keys the five call sites emitted must all still be there."""
        from .._source_types import SourceTypeParseError, parse_source_type

        with pytest.raises(SourceTypeParseError) as caught:
            parse_source_type("bogus", allow_aliases=True)
        envelope = caught.value.as_error_envelope()

        assert envelope["ok"] is False
        assert envelope["error"] == caught.value.error_kind
        assert envelope["message"] == str(caught.value)
        # The payload is spread in, not nested: an adapter reads received and
        # allowed off the top level.
        for key, value in caught.value.as_payload().items():
            assert envelope[key] == value


class TestCrossModuleLiteralTwins:
    """No data literal of three or more elements is written out twice.

    A scan for identical multi-element literals across modules found six: a
    failure envelope in five places, the sync-counter labels, the managed-log
    source vocabulary, the document-filter projection, the dry-run sample
    shape, and the probe-unavailable block - the last of which already had a
    helper in the transport that the status renderer simply did not call.

    Each had a natural owner that already existed. The sample now reports
    itself, the way the breadth figures already did; the counters and the log
    sources were declared once and re-listed; the filter projection sits with
    the type it produces.
    """

    def test_no_literal_collection_is_defined_in_two_modules(self) -> None:
        seen = _literal_collection_sites()
        find_offenders = {
            literal: sites
            for literal, sites in seen.items()
            if len({site.split(":")[0] for site in sites}) > 1
        }
        assert not find_offenders, (
            f"the same literal collection is written in two modules: "
            f"{find_offenders}; give it one owner both can import"
        )

    def test_the_sample_reports_itself(self) -> None:
        """The projection lives with the data, not in each adapter.

        Proven able to fail: dropping a key from ``as_payload`` fails this on
        the field comparison below.
        """
        from ..indexer._content_discovery import AdmissionReason, AdmissionSample
        from ..indexer._content_policy import ContentKind

        sample = AdmissionSample(
            path="p.py",
            kind=ContentKind.CODE,
            admitted=True,
            reason=next(iter(AdmissionReason)),
        )
        assert sample.as_payload() == {
            "path": sample.path,
            "kind": sample.kind.value if sample.kind is not None else None,
            "admitted": sample.admitted,
            "reason": sample.reason.value,
        }


class TestJobEnumGroupingsAreDeclared:
    """A named subset of an enum's members is declared on the enum.

    ``JobState`` already carried ``is_terminal`` as a property, so the
    mechanism existed and the code was written around it: three more
    groupings were enumerated at call sites instead. Nine sites listed
    members to ask one of three questions - is an attempt in flight, may this
    be retried, is this a corpus rather than housekeeping.

    Naming them also fixed an imprecision. The retry route rejected a job with
    "Only terminal jobs can be retried" while testing the narrower retryable
    set: a succeeded job is terminal and has nothing to retry. A grouping with
    no name gets described by whichever nearby word is close enough.
    """

    @staticmethod
    def _declared_groupings() -> dict[str, frozenset[str]]:
        """Return each named subset as the enum itself declares it."""
        from ..job_models import JobSource, JobState

        return {
            "JobState.is_live_attempt": frozenset(
                m.name for m in JobState if m.is_live_attempt
            ),
            "JobState.is_retryable": frozenset(
                m.name for m in JobState if m.is_retryable
            ),
            "JobState.is_terminal": frozenset(
                m.name for m in JobState if m.is_terminal
            ),
            "JobSource.is_corpus": frozenset(m.name for m in JobSource if m.is_corpus),
        }

    @staticmethod
    def _job_enum_members(node: ast.Set | ast.Tuple | ast.List) -> set[str]:
        """Return the ``JobState``/``JobSource`` member names *node* lists."""
        return {
            element.attr
            for element in node.elts
            if isinstance(element, ast.Attribute)
            and isinstance(element.value, ast.Name)
            and element.value.id in {"JobState", "JobSource"}
        }

    @classmethod
    def _relisted_groupings(
        cls, tree: ast.Module, groupings: dict[str, frozenset[str]]
    ) -> list[tuple[int, str]]:
        """Return ``(line, grouping)`` for every literal restating a grouping."""
        found: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Set | ast.Tuple | ast.List):
                continue
            members = cls._job_enum_members(node)
            if not members:
                continue
            found.extend(
                (node.lineno, name)
                for name, expected in groupings.items()
                if frozenset(members) == expected
            )
        return found

    def test_no_module_enumerates_a_job_enum_grouping(self) -> None:
        groupings = self._declared_groupings()
        find_offenders: list[str] = []
        for path in _production_sources():
            if path.name == "job_models.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            find_offenders.extend(
                f"{path.name}:{lineno} relists {name}"
                for lineno, name in self._relisted_groupings(tree, groupings)
            )
        assert not find_offenders, (
            f"{find_offenders}; ask the enum, so a member added to the grouping "
            "reaches every caller instead of whichever ones get remembered"
        )

    def test_retryable_is_narrower_than_terminal(self) -> None:
        """The distinction the enumerated version kept losing.

        Proven able to fail: widening ``is_retryable`` to ``is_terminal``
        fails this on the strict-subset assertion below.
        """
        from ..job_models import JobState

        terminal = {state for state in JobState if state.is_terminal}
        retryable = {state for state in JobState if state.is_retryable}
        assert retryable < terminal
        assert JobState.SUCCEEDED in terminal
        assert JobState.SUCCEEDED not in retryable


class TestTimestampReadingHasOneHome:
    """Only ``_timestamps`` turns a stored ISO string back into an instant.

    The writing side was made canonical long ago - one helper stamps both
    discovery fields so their format cannot drift. The reading side was not,
    and five sites parsed a stamp back, two of them the same function under
    the same name in modules one of which imports the other.

    The rule that mattered was the one for a value carrying no offset. Four
    readers called it UTC; the fifth handed it to ``astimezone``, which reads
    a naive value as local. Same string, two instants, differing by the
    machine's offset - and nothing failed, because the canonical writer always
    emits an offset. It would have surfaced first on a hand-edited file.
    """

    #: The typed round-trip for preprocess config scalars is not this. It
    #: dispatches across ``date``/``time``/``datetime`` and must RAISE on bad
    #: input, where every timestamp reader returns ``None`` and carries on.
    #: Merging them would force one contract onto both.
    _TYPED_SCALAR_THAW = "_resolved_policy.py"

    def test_only_the_timestamp_module_parses_an_iso_instant(self) -> None:
        """A new ``fromisoformat`` elsewhere is a sixth reader."""
        find_offenders: list[str] = []
        for path in _production_sources():
            if path.name in {"_timestamps.py", self._TYPED_SCALAR_THAW}:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            find_offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "fromisoformat"
            )
        assert not find_offenders, (
            f"an ISO timestamp is parsed outside the timestamp module at "
            f"{find_offenders}; call parse_iso_timestamp, so the rule for a value "
            "carrying no offset is stated once instead of guessed per reader"
        )

    def test_only_the_timestamp_module_calls_a_naive_value_utc(self) -> None:
        """The coercion is the rule itself, so it may exist in one place."""
        find_offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_timestamps.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            find_offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "replace"
                and any(kw.arg == "tzinfo" for kw in node.keywords)
            )
        assert not find_offenders, (
            f"a naive timestamp is given a timezone outside the timestamp "
            f"module at {find_offenders}; whichever offset it picks becomes a "
            "second answer to the question that module exists to answer once"
        )

    def test_a_naive_stamp_reads_as_utc_and_not_as_local(self) -> None:
        """The divergence the fifth reader carried.

        ``astimezone`` on a naive value assumes LOCAL time, so the label path
        placed the same string at a different instant from every other reader
        whenever the machine was not on UTC.

        Proven able to fail: returning ``parsed`` unchanged instead of
        ``parsed.replace(tzinfo=UTC)`` fails this on the ``tzinfo`` assertion
        below; making the fallback ``astimezone()`` fails it on the equality.
        """
        from datetime import UTC, datetime

        from .._timestamps import parse_iso_timestamp

        naive = parse_iso_timestamp("2026-07-26T10:00:00")
        assert naive is not None
        assert naive.tzinfo is UTC
        assert naive == datetime(2026, 7, 26, 10, 0, 0, tzinfo=UTC)

    def test_no_module_rewrites_a_z_suffix_before_parsing(self) -> None:
        """The dead workaround one reader still carried, kept out.

        ``fromisoformat`` has accepted ``Z`` since 3.11 and this package
        requires later, so substituting ``+00:00`` first is a no-op that reads
        as a necessary step. Asserting the parser accepts ``Z`` would test
        CPython rather than this codebase; asserting nothing performs the
        substitution tests the thing that was actually wrong.
        """
        find_offenders: list[str] = []
        for path in _production_sources():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            find_offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "replace"
                and [
                    argument.value
                    for argument in node.args
                    if isinstance(argument, ast.Constant)
                ]
                == ["Z", "+00:00"]
            )
        assert not find_offenders, (
            f"a Z suffix is rewritten before parsing at {find_offenders}; the "
            "parser has accepted it since 3.11, and a no-op that looks "
            "load-bearing is how the copy carrying it escaped notice"
        )


class TestTreeRemovalHasOneHandler:
    """Only ``_rmtree`` decides what to do with a link found mid-tree.

    Two modules had grown the handler independently, byte-for-byte identical
    apart from the name each gave the caught exception - and that rename is
    exactly why the structural scan could not see them. It blinds identifiers
    and constants, but an ``except ... as`` alias is a plain string on the
    handler node, so two identical bodies hashed differently.
    """

    def test_no_module_passes_its_own_onexc_handler(self) -> None:
        """A second handler is a second policy for following a link."""
        find_offenders: list[str] = []
        for path in _production_sources():
            if path.name == "_rmtree.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            find_offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and any(kw.arg in {"onexc", "onerror"} for kw in node.keywords)
            )
        assert not find_offenders, (
            f"a tree removal supplies its own error handler at {find_offenders}; "
            "call remove_tree, so descending through a link is refused by one "
            "policy rather than by whichever copy the caller reached for"
        )

    def test_the_handler_clears_a_link_instead_of_following_it(self) -> None:
        """The branch, exercised directly rather than through a tree.

        A tree-shaped test cannot reach this on Windows: ``rmtree`` there
        walks with ``scandir`` and removes both link shapes itself, so the
        handler is never invoked and the test passes whatever the handler
        does. Only the POSIX fd-walk raises on a link found mid-tree. Calling
        the handler with the arguments ``rmtree`` would pass it exercises the
        real branch on either platform.

        Proven able to fail: dropping the ``is_symlink`` branch so the handler
        only re-raises fails this on the ``pytest.fail`` below.
        """
        from .._rmtree import _unlink_link_or_reraise

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outside = root / "outside"
            outside.mkdir()
            kept = outside / "precious.txt"
            kept.write_text("must survive", encoding="utf-8")
            link = root / "link"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:  # pragma: no cover - unprivileged Windows
                pytest.skip(f"symlink creation not permitted here: {exc}")
            try:
                _unlink_link_or_reraise(os.rmdir, str(link), OSError("refused"))
            except OSError as exc:
                pytest.fail(
                    f"the handler re-raised over a link instead of clearing it: {exc}"
                )
            assert not link.is_symlink()
            assert kept.read_text(encoding="utf-8") == "must survive"

    def test_the_handler_re_raises_anything_that_is_not_a_link(self) -> None:
        """A real failure must not be swallowed by the link branch.

        Proven able to fail: returning instead of ``raise exc`` fails this on
        the ``pytest.raises`` below, and every genuine removal error would
        then be reported as a successful delete.
        """
        from .._rmtree import _unlink_link_or_reraise

        with tempfile.TemporaryDirectory() as td:
            ordinary = Path(td) / "ordinary.txt"
            ordinary.write_text("not a link", encoding="utf-8")
            with pytest.raises(OSError, match="disk went away"):
                _unlink_link_or_reraise(
                    os.unlink, str(ordinary), OSError("disk went away")
                )
