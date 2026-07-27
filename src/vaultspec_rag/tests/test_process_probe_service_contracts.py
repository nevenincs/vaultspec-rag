"""Canonical ownership guard tests for the process-probe split."""

from __future__ import annotations

import ast
import hashlib
import tempfile
from pathlib import Path
from typing import ClassVar

import pytest

from ._process_probe_guard_helpers import (
    _PACKAGE_ROOT,
    every_production_file,
)

pytestmark = [pytest.mark.unit]


def _shape_preserving_write_offenders() -> list[str]:
    find_offenders: list[str] = []
    for path in every_production_file():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - parsed elsewhere
            continue
        find_offenders.extend(_caller_shape_writes(tree, path))
    return find_offenders


def _caller_shape_writes(tree: ast.Module, path: Path) -> list[str]:
    find_offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_trailing_newline_match(node):
            continue
        enclosing = _enclosing_functions(tree, node)
        if "write_doc_preserving_shape" not in enclosing:
            find_offenders.append(f"{path.name}:{node.lineno} in {enclosing}")
    return find_offenders


def _is_trailing_newline_match(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_match_trailing_newline"
    )


def _enclosing_functions(tree: ast.Module, node: ast.Call) -> list[str]:
    return [
        outer.name
        for outer in ast.walk(tree)
        if isinstance(outer, ast.FunctionDef)
        and outer.lineno <= node.lineno <= (outer.end_lineno or 0)
    ]


class TestEveryRegisteredRouteIsTokenGated:
    """No route reaches its body without the token check having run.

    Twenty-six handlers open with the same three lines - call ``require_token``,
    test the result, return it when set. The check itself is already one
    function; what is repeated is the call and the early return, and that is
    the part a new route can simply omit. Omitting it does not fail: the route
    works, and works for anyone who can reach the port.

    This asserts the property rather than the shape, so a handler that gets the
    gate some other way still passes. Two already do: ``pause`` and ``resume``
    delegate to the quiesce handler, which is gated - a check looking only for
    a literal ``require_token`` call in each registered handler would have
    called both of them unauthenticated and been wrong.

    A decorator would collapse the three lines to one and make the gate
    impossible to half-apply. That is the better shape and it is not done here:
    it rewrites twenty-five authentication call sites, and this guard is what
    makes doing that safely possible rather than hopefully.
    """

    @staticmethod
    def _routes_module() -> ast.Module:
        return ast.parse(
            (_PACKAGE_ROOT / "server" / "_routes.py").read_text(encoding="utf-8")
        )

    @staticmethod
    def _route_bodies() -> dict[str, str]:
        bodies: dict[str, str] = {}
        for path in (_PACKAGE_ROOT / "server").glob("_routes*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            bodies.update(
                {
                    node.name: ast.unparse(node)
                    for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                }
            )
        return bodies

    @staticmethod
    def _gated_route_names(bodies: dict[str, str]) -> set[str]:
        gated = {
            name for name, body in bodies.items() if "require_token(request)" in body
        }
        changed = True
        while changed:
            changed = False
            for name, body in bodies.items():
                if name not in gated and any(
                    f"{peer}(request" in body for peer in gated
                ):
                    gated.add(name)
                    changed = True
        return gated

    @staticmethod
    def _registered_route_names(tree: ast.Module) -> list[str]:
        return [
            node.args[1].id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Route"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Name)
        ]

    def test_no_registered_route_skips_the_token_check(self) -> None:
        """Directly or by delegation, every route must reach the gate."""
        tree = self._routes_module()

        bodies = self._route_bodies()
        gated = self._gated_route_names(bodies)
        registered = self._registered_route_names(tree)
        assert registered, "no routes discovered; the scan is looking wrongly"
        ungated = sorted(name for name in registered if name not in gated)
        assert not ungated, (
            f"these registered routes never reach require_token: {ungated}; "
            "a route without the gate does not fail, it serves anyone who can "
            "reach the port"
        )


class TestRepeatedStatementRunsStayMerged:
    """No long run of statements is repeated inside two functions.

    Every other structural check here compares whole function bodies, so a run
    repeated INSIDE two larger functions was invisible to all of them. That is
    how a nine-statement pyproject write, a nine-statement incremental ingest
    phase, and an eleven-statement report section all survived earlier passes.

    The threshold is measured, not guessed. On the merged tree the repeated-run
    count by window size is: seven and above, none; six, four; five, ten; four,
    thirty-eight. The lower bands are dominated by constructor assignment
    sequences, which look alike once identifiers are blinded without being
    copies of anything, so a bound below seven would report noise and train its
    reader to ignore the check. Seven is the lowest bound that holds with no
    allowlist, which is the property worth having - an allowlist longer than
    the rule is how a guard stops meaning anything.

    Counting is by TOP-LEVEL statement, so a nested ``if`` or ``for`` body
    counts as one. A seven-statement run here is therefore a larger fragment
    than the number suggests.

    The two groups sitting just under the bound have been read, so the next
    person to lower it inherits the verdict rather than re-deriving it:

    * ``_progress`` and ``_run_policy`` constructors. Different classes,
      different fields, the same shape only because blinding erases the names -
      a run of attribute assignments is what every constructor looks like. Not
      duplication, and no bound distinguishes it from one that is.
    * ``job_dispatch`` code and document attempt runners. Genuine: two parallel
      implementations differing by which admission call and which indexer they
      use, where the sixth matched statement is the whole ``try`` body. Merging
      them means parameterising the job execution path by source, which is a
      real change to the path that runs every index job and wants its own
      iteration rather than a hurried one.
    """

    _MIN_RUN: ClassVar[int] = 7

    @staticmethod
    def _blinded_runs(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        """Return the function's top-level statements, identifier-blinded."""

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
                self.generic_visit(node)
                node.name = "_" if node.name else None
                return node

        rendered: list[str] = []
        for statement in node.body:
            if isinstance(statement, ast.Expr) and isinstance(
                statement.value, ast.Constant
            ):
                continue
            if isinstance(statement, ast.Import | ast.ImportFrom):
                continue
            try:
                reparsed = ast.parse(ast.unparse(statement)).body[0]
            except (SyntaxError, ValueError):  # pragma: no cover - unparseable
                continue
            rendered.append(ast.dump(_Blind().visit(reparsed)))
        return rendered

    def test_no_long_statement_run_appears_in_two_functions(self) -> None:
        """A repeated run is a copy that shares only part of its host."""
        runs: dict[str, set[str]] = {}
        for path in every_production_file():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                body = self._blinded_runs(node)
                if len(body) < self._MIN_RUN:
                    continue
                where = f"{path.name}:{node.lineno} {node.name}"
                for start in range(len(body) - self._MIN_RUN + 1):
                    window = hashlib.sha256(
                        chr(31).join(body[start : start + self._MIN_RUN]).encode()
                    ).hexdigest()
                    runs.setdefault(window, set()).add(where)
        find_offenders = sorted(
            {tuple(sorted(sites)) for sites in runs.values() if len(sites) > 1}
        )
        assert not find_offenders, (
            f"a run of {self._MIN_RUN}+ statements is repeated inside these "
            f"functions: {find_offenders}; extract the shared phase, because a "
            "fragment copy is the one shape the whole-body scans cannot see"
        )


class TestPyprojectWritesGoThroughOneWriter:
    """Every pyproject rewrite preserves byte shape through one function.

    ``write_doc_preserving_shape`` already had seven callers in two other
    modules while ``apply_patch`` and ``remove_patch``, eight lines above it in
    its own file, still inlined the same nine-statement sequence. The
    repetition was not the worst of it: those two owe a stated promise to each
    other - apply followed by remove leaves the file byte-identical - and a
    promise between two hand-maintained copies of a byte-shaping routine holds
    only while someone keeps them aligned.

    Two shapes survive the round trip and neither is recoverable from the
    parsed document: ``tomlkit`` always emits LF, and always exactly one
    trailing newline. Both are read back off the file, which is why the
    routine cannot be replaced by a plain dump.
    """

    def test_no_caller_reassembles_the_shape_preserving_write(self) -> None:
        """The trailing-newline restore belongs to one writer."""
        find_offenders = _shape_preserving_write_offenders()
        assert not find_offenders, (
            f"a caller restores the trailing-newline shape itself at "
            f"{find_offenders}; call write_doc_preserving_shape, so the "
            "apply/remove byte-symmetry is one function's property rather "
            "than an agreement between copies"
        )

    def test_apply_then_remove_leaves_the_file_byte_identical(self) -> None:
        """The promise the two copies existed to keep, across every shape.

        Proven able to fail: dropping the ``_match_trailing_newline`` call from
        the writer fails this on the no-trailing-newline shapes, and dropping
        the CRLF restore fails it on the CRLF ones.
        """
        from ..torch_config._mutate import apply_patch, remove_patch

        newline = chr(10)
        carriage = chr(13) + newline
        base = newline.join(
            [
                "[project]",
                'name = "demo"',
                'version = "0.1.0"',
                "",
                "[tool.other]",
                "keep = true",
            ]
        )
        shapes = [
            base + newline,
            base,
            base + newline + newline,
            base.replace(newline, carriage) + carriage,
            base.replace(newline, carriage),
            base.replace(newline, carriage) + carriage + carriage,
        ]
        for text in shapes:
            with tempfile.TemporaryDirectory() as workspace:
                pyproject = Path(workspace) / "pyproject.toml"
                pyproject.write_text(text, encoding="utf-8", newline="")
                before = pyproject.read_bytes()
                apply_patch(pyproject)
                assert pyproject.read_bytes() != before, "apply changed nothing"
                remove_patch(pyproject)
                assert pyproject.read_bytes() == before, repr(text[:40])


class TestPublishGateAndRefusalAreShared:
    """The manifest admission gate and the feedback refusal each have one home.

    Two publishers opened their write loop with the same five-statement gate -
    refuse unconverged, refuse out-of-order, remember the path, skip
    non-indexed, assert the survivor has a hash - and then did entirely
    different things with the survivor. Only the gate was shared; the loops
    stayed. It had already drifted where drift is cheapest: the ordering
    refusal was two sentences for one violation, so the explanation an operator
    got depended on which index was publishing.

    The feedback refusal is the more interesting shape. The HTTP route and the
    service client each carried the same source set, the same "did the caller
    name any points" test, and the same three-key envelope. The client builds
    it locally to refuse without a round trip - worth doing, and exactly what
    makes the copy dangerous, because the two are a request apart and a
    server-side change leaves the client refusing on the old terms with nothing
    observing the disagreement.
    """

    def test_no_publisher_writes_its_own_admission_gate(self) -> None:
        """A second gate is a second definition of publishable evidence."""
        find_offenders: list[str] = []
        for path in every_production_file():
            if path.name == "_file_state.py":
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
                and (
                    "cannot publish unresolved file state" in node.value
                    or "ledger file states must be" in node.value
                )
            )
        assert not find_offenders, (
            f"a publisher states the admission rule itself at {find_offenders}; "
            "iterate with iter_publishable_states, so one violation is not "
            "explained two ways depending on which index published"
        )

    def test_the_gate_refuses_unconverged_and_unordered_evidence(self) -> None:
        """Both refusals, and the skip that is not a refusal.

        Proven able to fail: dropping the ``converged`` clause fails on the
        unconverged case; dropping the ordering clause fails on the duplicate.
        """
        from .._job_errors import JobErrorKind
        from ..indexer._content_policy import AdmissionReason, ContentKind
        from ..indexer._file_state import (
            FileState,
            FileStateKind,
            iter_publishable_states,
        )

        digest = "a" * 128

        def indexed(rel_path: str) -> FileState:
            return FileState(
                rel_path=rel_path,
                state=FileStateKind.INDEXED,
                kind=ContentKind.CODE,
                content_hash=digest,
            )

        def skipped(rel_path: str) -> FileState:
            return FileState(
                rel_path=rel_path,
                state=FileStateKind.POLICY_REJECTED,
                kind=None,
                admission_reason=AdmissionReason.IGNORED,
            )

        assert [
            rel
            for rel, _ in iter_publishable_states([indexed("a.py"), skipped("b.py")])
        ] == ["a.py"]
        with pytest.raises(ValueError, match="unique and ordered"):
            list(iter_publishable_states([indexed("a.py"), indexed("a.py")]))
        with pytest.raises(ValueError, match="unique and ordered"):
            list(iter_publishable_states([indexed("b.py"), indexed("a.py")]))

        unconverged = FileState(
            rel_path="pending.py",
            state=FileStateKind.EXTRACT_RETRYABLE,
            kind=ContentKind.CODE,
            error_kind=JobErrorKind.EXTRACTION_RETRYABLE,
            detail="transient",
        )
        assert not unconverged.converged
        with pytest.raises(ValueError, match="cannot publish unresolved"):
            list(iter_publishable_states([unconverged]))

    def test_no_surface_builds_the_feedback_refusal_itself(self) -> None:
        """The client and the route must refuse on identical terms."""
        find_offenders: list[str] = []
        for path in every_production_file():
            if path.name == "_source_types.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            find_offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and node.value == "unsupported_feedback_for_search_type"
            )
        assert not find_offenders, (
            f"the feedback refusal is built outside its owner at {find_offenders}; "
            "call unsupported_feedback_envelope, because the client refuses "
            "locally and would otherwise drift a request behind the server"
        )

    def test_the_refusal_covers_exactly_the_identity_free_sources(self) -> None:
        """Which sources refuse, asserted rather than left to two copies.

        Proven able to fail: adding or removing a source from the refusing set
        fails this, as does refusing when the caller named no point ids.
        """
        from .._source_types import PublicSourceType, unsupported_feedback_envelope

        refusing = {
            source
            for source in PublicSourceType
            if unsupported_feedback_envelope(source, has_point_ids=True) is not None
        }
        assert refusing == {PublicSourceType.DOCUMENT, PublicSourceType.COMBINED}
        for source in PublicSourceType:
            assert unsupported_feedback_envelope(source, has_point_ids=False) is None, (
                source
            )


class TestVectorWidthAndCapHaveOneResolver:
    """The sparse width and the emitted-output cap are decided in one place.

    Both indexers resolved the sparse width inline, in blocks identical down to
    the strict ``type(...) is not int`` test - seven statements each, inside
    two different methods in two files that never import each other. That shape
    is why no earlier scan saw it: every structural comparison here reads whole
    function bodies, and this was a fragment of two larger ones.

    The cap was worse than duplicated, it was divergent. The resolved policy
    rejected anything that was not an ``int``; the cache identity only rejected
    ``bool`` and non-positive values, so a float passed the cache check and
    compared fine against zero. The shared validator uses the stricter rule,
    which narrows the cache path - the only safe direction for a check that
    exists to catch a value config did not coerce.
    """

    def test_no_indexer_resolves_the_sparse_width_itself(self) -> None:
        """A second resolver is a second answer to the collection's width."""
        find_offenders: list[str] = []
        for path in every_production_file():
            if path.name == "store_schema.py":
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
                and "no valid output dimension" in node.value
            )
        assert not find_offenders, (
            f"the sparse width is resolved outside store_schema at {find_offenders}; "
            "call effective_sparse_dim, so the width a collection is built "
            "with comes from one place like the dense width already does"
        )

    def test_a_model_reporting_true_is_not_read_as_width_one(self) -> None:
        """Why the resolver tests ``type`` rather than ``isinstance``.

        ``bool`` subclasses ``int``, so an ``isinstance`` check would accept
        ``True`` and build a collection accepting exactly one sparse term.

        Proven able to fail: relaxing ``type(value) is not int`` to
        ``not isinstance(value, int)`` fails this on the ``True`` case.
        """
        from ..store_schema import effective_sparse_dim

        class _Model:
            def __init__(self, value: object) -> None:
                self.sparse_dimension = value

        for bad in (True, False, 2.5, "30522", None, 0, -1):
            with pytest.raises(RuntimeError, match="no valid output dimension"):
                effective_sparse_dim(_Model(bad))
        assert effective_sparse_dim(_Model(30522)) == 30522

    def test_the_cap_check_is_the_strict_one_everywhere(self) -> None:
        """The divergence the two copies had: a float passed one of them.

        Proven able to fail: dropping the ``isinstance(value, int)`` clause
        reproduces the cache's weaker check and fails this on the float.
        """
        from ..indexer._preprocess_schema import validate_max_emitted_bytes

        assert validate_max_emitted_bytes(10 * 1024 * 1024) == 10 * 1024 * 1024
        for bad in (2.5, 1e7, True, False, 0, -1, "5", None):
            with pytest.raises(ValueError, match="positive integer"):
                validate_max_emitted_bytes(bad)

    def test_the_cap_rule_is_stated_once(self) -> None:
        """A second statement of the rule is how the two drifted apart."""
        find_offenders: list[str] = []
        for path in every_production_file():
            if path.name == "_preprocess_schema.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            find_offenders.extend(
                f"{path.name}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and node.value == "max_emitted_bytes must be a positive integer"
            )
        assert not find_offenders, (
            f"the emitted-cap rule is stated outside its validator at "
            f"{find_offenders}; call validate_max_emitted_bytes, because the two "
            "copies it replaced did not agree on what an integer is"
        )


class TestMcpFailureIsRecordedOneWay:
    """The install/uninstall pair words a topology refusal once, and records it once.

    Both verbs built the same three sentences for themselves and then appended
    each to two lists by hand. Both halves matter. The pair has to stay
    symmetric, because the same condition worded one way when installing and
    another when removing is a difference an operator has to work out is not
    real. And the two-channel record is load-bearing: ``mcp_errors`` drives the
    exit path while ``warnings`` drives the human report, so a failure written
    to only one either exits without explaining itself or explains itself
    without failing.

    The two copies had already settled on opposite append orders, which is the
    visible end of that drift rather than a bug in itself.
    """

    def test_no_verb_builds_a_topology_sentence_itself(self) -> None:
        """A prefix written anywhere but its owner is a second wording."""
        from ..commands import _mcp_topology

        owned = (
            _mcp_topology.TOPOLOGY_PREFLIGHT_FAILED,
            _mcp_topology.TOPOLOGY_MATERIALIZATION_FAILED,
        )
        find_offenders: list[str] = []
        for path in every_production_file():
            if path.name == "_mcp_topology.py":
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
                and any(prefix in node.value for prefix in owned)
            )
        assert not find_offenders, (
            f"a topology refusal is worded outside the module that owns it at "
            f"{find_offenders}; build it with the shared helper so installing and "
            "removing describe one condition the same way"
        )

    def test_no_verb_records_the_two_channels_by_hand(self) -> None:
        """Both lists are reached through one function, or one gets forgotten."""
        find_offenders: list[str] = []
        # The verbs only. ``_mcp_topology`` holds ``record_mcp_failure``, whose
        # body is the two appends this forbids everywhere else.
        for name in ("_install.py", "_uninstall.py"):
            path = _PACKAGE_ROOT / "commands" / name
            lines = path.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, start=1):
                nxt = lines[number] if number < len(lines) else ""
                first, second = line.strip(), nxt.strip()
                # Both orders count: the two copies had settled on opposite
                # ones, so matching only errors-then-warnings would have seen
                # half the sites.
                channels = {
                    suffix
                    for suffix in (
                        "mcp_errors.append(message)",
                        "warnings.append(message)",
                    )
                    if first.endswith(suffix) or second.endswith(suffix)
                }
                if len(channels) == 2:
                    find_offenders.append(f"{name}:{number}")
        assert not find_offenders, (
            f"a failure is appended to both channels by hand at {find_offenders}; "
            "call record_mcp_failure, because the pair is what makes a refusal "
            "both exit and explain itself"
        )

    def test_both_report_shapes_satisfy_the_recorder(self) -> None:
        """The structural contract, exercised on the real report objects.

        Proven able to fail: dropping either append from ``record_mcp_failure``
        fails this on the channel it stopped writing.
        """
        from pathlib import Path as _Path

        from ..commands._mcp_topology import record_mcp_failure
        from ..commands._models import InstallReport, UninstallReport

        for shape in (InstallReport, UninstallReport):
            report = shape(action="x", target=_Path("."))
            record_mcp_failure(report, "a failure")
            assert report.mcp_errors == ["a failure"], shape.__name__
            assert report.warnings == ["a failure"], shape.__name__


class TestValidationRulesAreStatedOnce:
    """A rejection rule lives in one function, not one per caller.

    Two validations were written twice. The rel_path check - nine clauses
    deciding whether a stored path is canonical and project-relative - existed
    as a row's own method and again as a ledger function, byte-identical. The
    content-route pattern check existed at the configuration boundary and again
    in the compiled policy vocabulary.

    Neither had drifted, and that is the whole difficulty: a duplicated
    rejection rule does not fail when it diverges, it just starts accepting
    different things in different places. Four of the rel_path clauses are
    containment checks - a backslash, a drive letter, an absolute path, and
    ``..`` each name a file outside the project the row claims to describe -
    so the copy that loses one accepts a path the other rejects, and which one
    runs depends on whether the value arrived as a row or through the ledger.

    Checked by message, because the message is what a second copy must
    reproduce to be a copy at all, and because the two rel_path bodies were
    identical while living in different shapes - a method and a function - that
    a body-comparison scan with a statement-count floor never compared.
    """

    #: Rejection message -> the module allowed to raise it.
    _OWNERS: ClassVar[dict[str, str]] = {
        "rel_path must be canonical project-relative POSIX syntax": "_file_state.py",
        "content route pattern must not be empty": "_content_route_syntax.py",
        "content route pattern must not contain NUL": "_content_route_syntax.py",
    }

    def test_no_module_but_the_owner_raises_the_rule(self) -> None:
        """A second module raising the same rejection is a second rule."""
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
                        f"{path.name}:{node.lineno} raises {node.value!r}"
                    )
        assert not find_offenders, (
            f"a validation rule is stated outside the module that owns it: "
            f"{find_offenders}; call the shared validator, because a duplicated "
            "rejection does not fail when it drifts - it just starts "
            "accepting different things on different paths"
        )

    def test_the_ledger_and_the_row_share_one_validator(self) -> None:
        """Not equal behaviour - the same function, reached from both.

        Proven able to fail: giving the ledger its own copy again fails the
        message guard above, and rebinding the name here to an equivalent
        local function fails this identity assertion.
        """
        from ..indexer import _file_state, _run_ledger_models

        assert _run_ledger_models.validate_rel_path is _file_state.validate_rel_path

    def test_containment_clauses_all_still_reject(self) -> None:
        """The four clauses that keep a row inside the project.

        Proven able to fail: dropping any one of the ``..``, backslash, drive,
        or absolute clauses from the canonical validator fails this on the
        case that clause is the only one catching.
        """
        from ..indexer._file_state import validate_rel_path

        validate_rel_path("src/a.py")
        for escaping in (
            "..",
            "../escape",
            "a/../../etc/passwd",
            "/abs/path",
            "C:/win/path",
            "back" + chr(92) + "slash",
            "nul" + chr(0) + "byte",
        ):
            with pytest.raises(ValueError, match="canonical project-relative"):
                validate_rel_path(escaping)
