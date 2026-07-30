"""Canonical ownership guard tests for the process-probe split."""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from typing import TYPE_CHECKING, ClassVar

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

from ._process_probe_guard_helpers import (
    _PACKAGE_ROOT,
    _production_sources,
    every_production_file,
    parsed_production_sources,
)

pytestmark = [pytest.mark.unit]


class _FunctionBodyNormalizer(ast.NodeTransformer):
    def visit_Name(self, node: ast.Name) -> ast.Name:
        return ast.copy_location(ast.Name(id="_", ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg) -> ast.arg:
        return ast.copy_location(ast.arg(arg="_", annotation=None), node)

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        self.generic_visit(node)
        return ast.copy_location(
            ast.Attribute(value=node.value, attr="_", ctx=node.ctx), node
        )

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        return ast.copy_location(ast.Constant(value=None), node)


def _normalised_function_body(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> ast.Module | None:
    body = [
        statement
        for statement in function.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
        )
    ]
    if not body:
        return None
    return ast.Module(
        body=[
            ast.fix_missing_locations(
                _FunctionBodyNormalizer().visit(ast.parse(ast.unparse(statement)))
            )
            for statement in body
        ],
        type_ignores=[],
    )


def _duplicate_function_body_groups(min_nodes: int) -> dict[tuple[str, ...], list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for path in _production_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(_PACKAGE_ROOT).as_posix()
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            normalised = _normalised_function_body(function)
            if normalised is None or sum(1 for _ in ast.walk(normalised)) < min_nodes:
                continue
            digest = hashlib.sha1(ast.dump(normalised).encode()).hexdigest()
            groups[digest].append(f"{relative}:{function.name}")
    return {
        tuple(sorted(set(members))): members
        for members in groups.values()
        if len(set(members)) > 1
    }


def _self_call_names(node: ast.AST) -> set[str]:
    """Return every ``self.x(...)`` callee name anywhere under *node*."""
    return {
        inner.func.attr
        for inner in ast.walk(node)
        if isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Attribute)
        and isinstance(inner.func.value, ast.Name)
        and inner.func.value.id == "self"
    }


def _enters_self_lock(block: ast.With | ast.AsyncWith, lock_attr: str) -> bool:
    """Report whether *block* enters ``self.<lock_attr>``.

    Checks every context manager in the ``with`` header, because the registry
    takes the GPU lock and this one together in a single statement.
    """
    return any(
        isinstance(item.context_expr, ast.Attribute)
        and item.context_expr.attr == lock_attr
        and isinstance(item.context_expr.value, ast.Name)
        and item.context_expr.value.id == "self"
        for item in block.items
    )


def _class_methods(
    source: str, class_name: str
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return the directly-declared methods of *class_name* in *source*."""
    return {
        member.name: member
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef) and node.name == class_name
        for member in node.body
        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _methods_reaching(
    methods: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef],
    seeds: frozenset[str],
) -> set[str]:
    """Close *seeds* over ``self.`` calls to a fixed point.

    Returns every method that can reach a seed, at any depth. Lexical
    containment is not enough here: a caller can hold a lock and delegate the
    forbidden work to a helper one or more frames down.
    """
    reaching = set(seeds)
    growing = True
    while growing:
        growing = False
        for name, node in methods.items():
            if name not in reaching and _self_call_names(node) & reaching:
                reaching.add(name)
                growing = True
    return reaching


def _locked_load_offenders(
    source: str,
    *,
    class_name: str,
    lock_attr: str,
    load_seeds: frozenset[str],
) -> tuple[list[str], int, set[str]]:
    """Find lock-held paths that reach a model load.

    Returns the offenders, the number of blocks taking the lock (the scanned
    population), and the transitive set of methods that reach a load.
    """
    methods = _class_methods(source, class_name)
    reaching = _methods_reaching(methods, load_seeds)
    offenders: list[str] = []
    locked_blocks = 0
    for name, node in methods.items():
        for block in ast.walk(node):
            if not isinstance(block, ast.With | ast.AsyncWith):
                continue
            if not _enters_self_lock(block, lock_attr):
                continue
            locked_blocks += 1
            if name in load_seeds:
                # The load's own double-check. This block IS the critical
                # section the lock exists for, not work stacked around it.
                continue
            reached = sorted(
                _self_call_names(ast.Module(body=block.body, type_ignores=[]))
                & reaching
            )
            if reached:
                offenders.append(f"{class_name}.{name}:{block.lineno} calls {reached}")
    return offenders, locked_blocks, reaching


class TestOperatorAddressLineHasOneTemplate:
    """The "Address:" line is built by ``_render.address_line`` alone.

    ``address_line`` already existed and already had eight callers while eight
    OTHER sites hand-built the identical f-string - a half-adopted canonical,
    which is worse than none: it reads as if the template is owned, so the next
    author copies whichever form they happened to see.
    """

    def test_no_module_hand_builds_the_address_line(self) -> None:
        find_offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_render.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "Address: http://127.0.0.1:" in line
        ]
        assert not find_offenders, (
            f"hand-built operator address line at {find_offenders}; call "
            "_render.address_line(port) so the label and host rendering "
            "cannot disagree across the CLI's own output"
        )

    def test_the_template_still_renders_what_operators_parse(self) -> None:
        # The string itself is the contract - operators and docs read it - so
        # centralising must not quietly reword it.
        from ..cli._render import address_line

        assert address_line(8766) == "Address: http://127.0.0.1:8766"


class TestConfigDefaultsResolveInConfig:
    """A default belongs where the setting does, not at the point of use.

    Two settings had their fallback spelled at the call site instead: the
    Qdrant base URL (four identical expressions plus a variant) and the
    Hugging Face cache location (two). The HF one had already gone wrong -
    an operator who set ``HF_HOME`` was told a failed download's leftovers
    were in ``~/.cache/huggingface``, which is not where they are.
    """

    def test_no_module_rebuilds_the_qdrant_url_fallback(self) -> None:
        # Keys on the loopback fallback, not on reading qdrant_url: several
        # modules legitimately read it WITHOUT a fallback to ask a different
        # question - "is a remote configured?" - and must not be flagged.
        find_offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.relative_to(_PACKAGE_ROOT).as_posix() != "config/_settings.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "qdrant_port}" in line and "127.0.0.1" in line
        ]
        assert not find_offenders, (
            f"inline Qdrant URL fallback at {find_offenders}; read "
            "get_config().effective_qdrant_url"
        )

    def test_no_module_hardcodes_the_hf_cache_default(self) -> None:
        find_offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.relative_to(_PACKAGE_ROOT).as_posix() != "config/_settings.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "~/.cache/huggingface" in line
        ]
        assert not find_offenders, (
            f"hardcoded HF cache default at {find_offenders}; read "
            "get_config().hf_cache_location so a set HF_HOME is honoured"
        )

    def test_the_hf_cache_location_follows_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The behaviour the hardcoded default got wrong. Asserted through the
        # config property, which is what every reporting site now calls.
        from ..config._settings import get_config, reset_config
        from ..config._types import EnvVar

        monkeypatch.setenv(EnvVar.HF_HOME.value, "/tmp/hf-elsewhere")
        reset_config()
        try:
            assert get_config().hf_cache_location == "/tmp/hf-elsewhere"
        finally:
            monkeypatch.delenv(EnvVar.HF_HOME.value, raising=False)
            reset_config()
        assert get_config().hf_cache_location == "~/.cache/huggingface"


class TestNoStructurallyIdenticalFunctions:
    """No two production functions share a body that differs only by constants.

    Found by normalising every function body - identifiers, attributes,
    literals and docstrings replaced - and hashing it, which surfaces
    duplication no keyword search would: the store's code and document scroll
    pages were ~50 identical lines apart from the collection, the payload key,
    and the noun in two error messages.

    The allowlist below records groups that are structurally alike but
    semantically distinct - the same SHAPE applied to different domains, which
    merging would harm. Each entry names why.
    """

    #: (sorted tuple of "module:function") -> reason the shape is not shared
    #: behaviour. Shrink this as groups are merged; adding an entry to silence
    #: the check rather than to record a judgement defeats it.
    #: Why a group of identical-looking bodies is NOT shared behaviour. The
    #: reasons cluster, so they are named once and applied, rather than
    #: sixteen near-identical sentences - which would be this file committing
    #: the duplication it exists to prevent.
    _PARAMETERISATION = (
        "A named entry point supplying its own constants to an implementation "
        "that is ALREADY shared. Merging further would push those constants "
        "out to every call site, which is the opposite of the goal."
    )
    _OPTIONAL_ATTR = (
        "Python's missing optional-chaining: `x = self._attr; return x.f() if "
        "x is not None else None`. A generic helper reads worse than the two "
        "lines, and the classes involved share no base to hang it on."
    )
    _FIND_FIRST = (
        "Linear search for the first item matching an attribute. A generic "
        "finder costs more in indirection than the four lines it saves."
    )
    _DISTINCT_PROSE = (
        "Same rendering shape, different diagnosis. What differs is the "
        "operator-facing sentences, so merging would mean passing prose in as "
        "arguments."
    )
    _SMALL_GUARD = (
        "A two-line accessor or guard whose computation, return type, or "
        "error message differs. The shape is shared; nothing else is."
    )
    _SERIALISATION = (
        "Both build a dict literal from their own fields. The shape of "
        "`to_dict` is not behaviour that can be shared - the fields are "
        "unrelated."
    )

    _NAMED_SUBSET = (
        "A membership test against a named subset of one enum's members. The "
        "shape is `return self in {...}` and the whole content is WHICH "
        "members - parameterising it would mean a set of sets keyed by name, "
        "which is the enumeration these properties exist to remove."
    )

    _INDEPENDENT_LANE = (
        "Each bumps its own generation counter and dispatches its own worker. "
        "The separate counters are the point - they are what let the lanes be "
        "ordered independently, so one lane's slow answer cannot be mistaken "
        "for another's - and merging would mean reaching them by attribute "
        "name, which trades a checked reference for a string."
    )

    _UNSHARED_VIEW_STATE = (
        "Two view classes that deliberately share no rendering: one parses "
        "structured records, suppresses polling reflections and caps the "
        "window, the other only neutralizes control bytes. They hold "
        "differently named state and repaint through different methods, so "
        "what matches is the guard's shape. Giving them a common base to share "
        "three lines would couple exactly what they were separated to keep "
        "apart."
    )

    _CONSTRUCTOR_BINDING = (
        "Two unrelated constructors binding their own parameters to their own "
        "attributes. What matches is the run of `self._x = x` lines and the "
        "count of them; the classes share no base, no collaborator, and no "
        "behaviour, so there is nothing to merge - only a coincidence of arity."
    )

    _ALLOWED_SHAPES: ClassVar[dict[tuple[str, ...], str]] = {
        (
            "job_models.py:is_live_attempt",
            "job_models.py:is_retryable",
        ): _NAMED_SUBSET,
        (
            "indexer/_incremental_commit.py:__init__",
            "server/_stdio_lifetime.py:__init__",
        ): _CONSTRUCTOR_BINDING,
        (
            "cli/_search.py:_render_breadth_shortfall",
            "cli/_search.py:_render_file_breadth_shortfall",
        ): _DISTINCT_PROSE,
        (
            "_readiness.py:dimension",
            "cli/_jobs_tui_status.py:seat_pool",
            "commands/_provision.py:result_for",
        ): _FIND_FIRST,
        (
            "indexer/_preprocess_config.py:match",
            "indexer/_resolved_policy.py:match_preprocess",
        ): _FIND_FIRST,
        (
            "cli/_preprocess.py:_format_failure_handling",
            "cli/_preprocess.py:_status_effect_line",
        ): _SMALL_GUARD,
        (
            "commands/_mcp_topology.py:_require_identity",
            "commands/_mcp_topology.py:_require_unchanged",
        ): _SMALL_GUARD,
        (
            "watcher_runtime.py:dirty_paths",
            "watcher_runtime.py:pending_count",
        ): _SMALL_GUARD,
        (
            "commands/_provision.py:to_dict",
            "indexer/_drift_owner.py:snapshot",
        ): _SERIALISATION,
        (
            "_store_models.py:vault_indexed_metadata",
            "index_profiles.py:_limits",
        ): _SERIALISATION,
        (
            "cli/_jobs_tui.py:refresh_jobs",
            "cli/_jobs_tui.py:refresh_managed_logs",
            "cli/_jobs_tui.py:refresh_search_activity",
        ): _INDEPENDENT_LANE,
        (
            "cli/_jobs_tui_log.py:_render_if_content",
            "cli/_jobs_tui_managed_logs.py:_repaint_if_held",
        ): _UNSHARED_VIEW_STATE,
        (
            "cli/_jobs_tui_log.py:show_message",
            "cli/_jobs_tui_managed_logs.py:show_message",
        ): _UNSHARED_VIEW_STATE,
        (
            "indexer/_codebase_indexer.py:_reuse_snapshot",
            "indexer/_document_indexer.py:_reuse_snapshot",
            "indexer/_generation_lifecycle.py:drift_snapshot",
        ): _OPTIONAL_ATTR,
        (
            "indexer/_codebase_indexer.py:memory_budget_snapshot",
            "indexer/_document_indexer.py:memory_budget_snapshot",
        ): _OPTIONAL_ATTR,
        (
            "cli/_service_start.py:_fail_start",
            "cli/_service_stop.py:_fail_stop",
        ): _PARAMETERISATION,
        (
            "cli/_service_start.py:_start_success",
            "cli/_service_stop.py:_stop_success",
        ): _PARAMETERISATION,
        (
            "indexer/_content_discovery.py:resolve_policy",
            "indexer/_document_indexer.py:resolve_policy_snapshot",
        ): _PARAMETERISATION,
        (
            "store_runtime.py:_retrieve",
            "store_runtime.py:_scroll",
        ): _PARAMETERISATION,
        (
            "store_collections.py:ensure_document_table",
            "store_collections.py:ensure_table",
        ): _PARAMETERISATION,
        (
            "store_catalog.py:get_all_document_content_ids",
            "store_catalog.py:get_all_ids",
        ): _PARAMETERISATION,
        (
            "store_catalog.py:scroll_code_content",
            "store_catalog.py:scroll_document_content",
        ): _PARAMETERISATION,
    }

    _MIN_NODES: ClassVar[int] = 20

    def test_no_large_duplicate_function_bodies(self) -> None:
        find_offenders = _duplicate_function_body_groups(self._MIN_NODES)
        unexplained = {
            key: members
            for key, members in find_offenders.items()
            if key not in self._ALLOWED_SHAPES
        }
        assert not unexplained, (
            f"functions with identical bodies at {sorted(unexplained)}; either "
            "merge them behind one implementation that takes the differing "
            "values, or add the group to _ALLOWED_SHAPES with the reason the "
            "shape is not shared behaviour"
        )


class TestAtomicReplaceHasOneImplementation:
    """Publishing a file goes through ``_atomic_write``, never bare ``os.replace``.

    Twenty-odd modules published state with a bare ``os.replace``. One - the
    job persistence layer - had learned that Windows Defender and the Search
    indexer open a freshly published file, so a replace landing in that window
    fails with ACCESS_DENIED or SHARING_VIOLATION, and had grown a retry
    ladder for it. The other twenty were still exposed to the exact condition
    that layer was hardened against.
    """

    def test_no_module_calls_os_replace_directly(self) -> None:
        find_offenders = [
            f"{path.relative_to(_PACKAGE_ROOT).as_posix()}:{number}"
            for path in _production_sources()
            if path.name != "_atomic_write.py"
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if "os.replace(" in line and not line.lstrip().startswith("#")
        ]
        assert not find_offenders, (
            f"bare os.replace at {find_offenders}; use "
            "_atomic_write.replace_atomically, which retries the Windows "
            "sharing race and costs nothing when uncontended"
        )

    def test_the_retry_is_free_when_uncontended(self, tmp_path: Path) -> None:
        # The whole argument for applying this everywhere is that the ladder
        # exits on its first attempt. If a future edit made it sleep
        # unconditionally, every publish in the codebase would slow down and
        # no other test would notice.
        import time

        from .._atomic_write import replace_atomically

        source = tmp_path / "s.tmp"
        source.write_text("x", encoding="utf-8")
        started = time.perf_counter()
        replace_atomically(source, tmp_path / "d.json")
        elapsed = time.perf_counter() - started
        assert elapsed < 0.05, (
            f"an uncontended replace took {elapsed * 1000:.1f} ms; the retry "
            "ladder must not sleep when the first attempt succeeds"
        )

    def test_durability_is_opt_in_and_separate(self) -> None:
        # Keeping the two apart is what let every caller adopt the retry: a
        # per-file indexing write must not pay for an fsync it does not need.
        from .._atomic_write import replace_atomically, replace_durably

        assert replace_atomically is not replace_durably


class TestTheRegistryLockNeverCoversAModelLoad:
    """No registry method holds ``_lock`` across a path that loads the model.

    ``_lock`` is one lock for the whole registry - every root behind it - so
    every millisecond it is held beyond the state mutation it protects is a
    millisecond every other root waits. Bringing the GPU model up is the
    longest step the registry has.

    The registry already spells this rule twice in its own code, which is why
    it is worth guarding rather than inventing: slot creation runs outside
    ``_lock`` to preserve the parallel cold-start guarantee, and the GPU
    residency rebuild takes the GPU lock for the load and ``_lock`` only
    afterwards, for the cheap state reads.

    Keyed on ``_lock`` because that is what actually serializes. The previous
    version keyed on the project LEASE and named the lease as the blocker,
    which was never true: taking a lease locks only long enough to bump a
    refcount and a last-access stamp, and releases before the caller's body
    runs, so concurrent leases on one root and on different roots both
    proceed. The mis-keying also made the scan structurally empty - it
    required a lease call and a load call in ONE function body, and no
    function has ever had both - so it reported a clean codebase while a real
    violation sat in it.

    The scan follows ``self.`` calls transitively. Lexical containment inside
    the ``with`` block is not enough, because the way this goes wrong in
    practice is a method that holds the lock and delegates the loading to a
    builder a frame or two down.
    """

    #: The registry attribute holding the one process-wide registry lock.
    _LOCK_ATTR: ClassVar[str] = "_lock"
    #: The class the lock is private to, so the scan needs no cross-module
    #: receiver inference to know whose lock it is looking at.
    _REGISTRY: ClassVar[str] = "ServiceRegistry"
    #: The methods that bring the GPU model up. The private one counts:
    #: reaching past the ticketed wrapper is not an exemption. Both are
    #: asserted to exist below, because a rename is how the scan goes blind.
    _LOAD_SEEDS: ClassVar[frozenset[str]] = frozenset({"load_model", "_load_model"})
    #: Below the real count of blocks taking ``_lock``. Renaming the attribute
    #: drops this to zero, so the floor fires long before the scan can go
    #: quiet by looking at nothing.
    _MIN_LOCKED_BLOCKS: ClassVar[int] = 20

    @classmethod
    def _scan(cls, source: str) -> tuple[list[str], int, set[str]]:
        """Run the scan over *source* under this guard's own names."""
        return _locked_load_offenders(
            source,
            class_name=cls._REGISTRY,
            lock_attr=cls._LOCK_ATTR,
            load_seeds=cls._LOAD_SEEDS,
        )

    @classmethod
    def _scan_service_source(cls) -> tuple[list[str], int, set[str]]:
        return cls._scan((_PACKAGE_ROOT / "service.py").read_text(encoding="utf-8"))

    def test_the_scanned_names_are_the_registry_s_own(self) -> None:
        """A renamed load entry point fails here rather than emptying the scan.

        Proven able to fail: adding a name the registry does not define to
        ``_LOAD_SEEDS`` fails on the missing-name assertion, which is what a
        rename that left the scan behind looks like.
        """
        from ..service import ServiceRegistry

        missing = sorted(
            name for name in self._LOAD_SEEDS if not hasattr(ServiceRegistry, name)
        )
        assert not missing, (
            f"the scan looks for {missing}, which the registry no longer "
            "defines; repoint the seed set at the current load entry points "
            "instead of letting the scan match nothing"
        )

    def test_the_scan_follows_a_load_reached_through_a_helper(self) -> None:
        """The detector itself, against a known positive and a known negative.

        The failure mode being covered is the one that killed the previous
        guard: a scan that matches nothing and reports success. Here the
        positive holds the lock and reaches the load two frames down, which a
        lexical scan of the ``with`` body would miss.
        """
        positive = (
            "class ServiceRegistry:\n"
            "    def _load_model(self): ...\n"
            "    def _build(self): self._load_model()\n"
            "    def _runtime(self):\n"
            "        with self._lock:\n"
            "            return self._build()\n"
        )
        negative = (
            "class ServiceRegistry:\n"
            "    def _load_model(self): ...\n"
            "    def _build(self): self._load_model()\n"
            "    def _runtime(self):\n"
            "        runtime = self._build()\n"
            "        with self._lock:\n"
            "            return runtime\n"
        )
        seen, _, reaching = self._scan(positive)
        assert seen == ["ServiceRegistry._runtime:5 calls ['_build']"], seen
        assert reaching == self._LOAD_SEEDS | {"_build", "_runtime"}, reaching
        assert not self._scan(negative)[0]

    def test_no_registry_method_holds_the_lock_across_a_model_load(self) -> None:
        """The lock may cover the load's own critical section and nothing else.

        Proven able to fail: this reports the offending method, its line, and
        the call it reaches the load through, and the report goes away when
        the construction moves back outside the lock.
        """
        find_offenders, locked_blocks, reaching = self._scan_service_source()
        assert locked_blocks >= self._MIN_LOCKED_BLOCKS, (
            f"only {locked_blocks} blocks take {self._LOCK_ATTR}; the scan is "
            "looking wrongly, not the code getting cleaner"
        )
        assert reaching > self._LOAD_SEEDS, (
            "no method reaches a model load through another; the call graph "
            "walk has stopped working and the scan now sees only direct calls"
        )
        assert not find_offenders, (
            f"these hold the registry lock across a model load: {find_offenders}; "
            "build outside the lock and take it only to publish the result, as "
            "slot creation and the residency rebuild already do - one lock "
            "covers every root, so a cold start under it stalls all of them"
        )


class TestPointsAreWrittenUnderTheCreatedVectorNames:
    """The store writes a point's vectors under the names it created them with.

    The store already created collections with ``DENSE_VECTOR_NAME`` and read
    points back by it. Only the write side spelled the names out: four upsert
    paths built the vector map with the literals, eight sites in all.

    Create-by-constant, read-by-constant, write-by-literal is the shape that
    hurts. Renaming the constant would build the collection under the new name
    and look for points under the new name, while every upsert kept writing the
    old one - and the failure surfaces at ingest against a live backend, not in
    any check that reads the code.

    Scoped to vector maps. The same two words are also keys of the model
    identity block - which dense model, which sparse model - and that is a
    different mapping that happens to share the vocabulary.
    """

    def test_no_upsert_spells_a_vector_name(self) -> None:
        """A literal here writes to a name nothing else agreed to."""
        from .. import store_schema

        owned = {store_schema.DENSE_VECTOR_NAME, store_schema.SPARSE_VECTOR_NAME}
        sources = {
            name: (_PACKAGE_ROOT / name).read_text(encoding="utf-8")
            for name in (
                "store_runtime.py",
                "store_collections.py",
                "store_ingest.py",
                "store_catalog.py",
                "store_donors.py",
            )
        }
        find_offenders: list[str] = []
        for name, source in sources.items():
            for node in ast.walk(ast.parse(source)):
                keys: list[ast.expr] = []
                if isinstance(node, ast.Dict):
                    keys = [key for key in node.keys if key is not None]
                elif isinstance(node, ast.Subscript):
                    keys = [node.slice]
                find_offenders.extend(
                    f"{name}:{key.lineno} spells {key.value!r}"
                    for key in keys
                    if isinstance(key, ast.Constant) and key.value in owned
                )
        assert not find_offenders, (
            f"a vector name is spelled in the store at {find_offenders}; use the "
            "store_schema constant, because the collection is created and "
            "read by it and a write under a different name fails only at "
            "ingest against a live backend"
        )

    def test_the_created_and_read_names_are_the_same_object(self) -> None:
        """Creation, write and read must resolve to one constant, not three.

        Proven able to fail: rebinding either name to an equal-but-distinct
        string fails the identity assertion, which equality would not catch.
        """
        from .. import store_schema
        from ..indexer import _donor_candidates

        schema = _donor_candidates.expected_vector_schema()
        assert schema.dense_name is store_schema.DENSE_VECTOR_NAME
        assert schema.sparse_name in (None, store_schema.SPARSE_VECTOR_NAME)


class TestSearchPhaseKeysAreNamed:
    """A timings phase key is written once, not at every site that uses it.

    Seven keys were spelled as literals across twenty-three sites - at each
    recording site and again at each site that read one back to sum a total.
    Three of them were recorded from three different searches.

    A phase key is a wire name. Renaming one recording site and not its reader
    does not raise: the phase drops out of the total, and the search reports a
    smaller number than the work took. That is the failure this prevents, and
    it is invisible to every test that only checks results.
    """

    @staticmethod
    def _phase_key_subscript_offenders(
        tree: ast.Module, owned: set[str], filename: str
    ) -> list[str]:
        return [
            f"{filename}:{node.slice.lineno} stores {node.slice.value!r}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value in owned
        ]

    @staticmethod
    def _call_name(node: ast.Call) -> str:
        """Return the simple callee name used by this structural guard."""
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        if isinstance(node.func, ast.Name):
            return node.func.id
        return ""

    @classmethod
    def _phase_key_call_arguments(
        cls, node: ast.Call, owned: set[str], filename: str
    ) -> list[str]:
        """Describe phase-key literals passed to a timing lookup or recorder."""
        name = cls._call_name(node)
        if not (
            name == "get"
            or name.endswith("record_seconds")
            or name.endswith("add_seconds")
        ):
            return []
        return [
            f"{filename}:{argument.lineno} looks up {argument.value!r}"
            for argument in node.args
            if isinstance(argument, ast.Constant) and argument.value in owned
        ]

    @staticmethod
    def _phase_key_call_offenders(
        tree: ast.Module, owned: set[str], filename: str
    ) -> list[str]:
        return [
            offender
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for offender in TestSearchPhaseKeysAreNamed._phase_key_call_arguments(
                node, owned, filename
            )
        ]

    def test_no_search_module_spells_a_phase_key(self) -> None:
        """A literal key is a spelling the reader of the total cannot follow."""
        from ..search import _result_shaping

        owned = {
            value
            for name, value in vars(_result_shaping).items()
            if name.startswith("PHASE_") and isinstance(value, str)
        }
        assert owned, "no phase keys found; the scan is looking wrongly"
        find_offenders: list[str] = []
        for path, tree in parsed_production_sources(
            every_production_file(), {"_result_shaping.py"}
        ):
            # Only STORE and LOOKUP positions. The same string is also an HTTP
            # response field name in the search route, and that is a separate
            # contract - the wire shape a consumer parses, not the internal
            # key a phase was recorded under. Flagging it would force the two
            # to move together, which is the opposite of what is wanted.
            #
            # Subscripts count. A phase is often recorded by assigning into the
            # mapping rather than through the recorder, and the first version
            # of this check read only calls - so four keys across three
            # modules, two of them crossing a module boundary, sat underneath
            # it untouched.
            find_offenders.extend(
                self._phase_key_subscript_offenders(tree, owned, path.name)
            )
            find_offenders.extend(
                self._phase_key_call_offenders(tree, owned, path.name)
            )
        assert not find_offenders, (
            f"a timings phase key is spelled outside its owner at {find_offenders}; "
            "use the constant, because a key renamed at one of its sites "
            "silently drops that phase out of the reported total"
        )

    def test_every_key_is_distinct_and_suffixed(self) -> None:
        """Two phases sharing a key would overwrite each other's measurement.

        Proven able to fail: pointing two of the constants at one string fails
        the distinctness assertion, which is what a copy-paste of a new phase
        constant produces.
        """
        from ..search import _result_shaping

        keys = {
            name: value
            for name, value in vars(_result_shaping).items()
            if name.startswith("PHASE_") and isinstance(value, str)
        }
        assert len(set(keys.values())) == len(keys), keys
        for name, value in keys.items():
            assert value.endswith("_seconds"), (name, value)
