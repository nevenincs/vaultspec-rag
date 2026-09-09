"""The scoped publication path may not reach for the whole collection.

A scoped update knows exactly which paths changed. Everything it does should
be bounded by that set plus a fixed overhead, and the two ways that stops
being true are both cheap to reintroduce and invisible in a passing suite:
scrolling the served collection to recover something canonical proof already
records, and reading the complete evidence map to change a few entries in it.
Both are what made a one-file update take a minute and a half on a large
index.

These are source-shape assertions rather than a driven run, deliberately. A
run proves the path did not scan the collection it happened to be given; this
proves the code cannot, whatever collection it is handed and whichever branch
it takes.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, ClassVar

import pytest

from ..store_catalog import _VaultCatalogMixin
from ._process_probe_guard_helpers import every_production_file

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

#: Store reads whose cost follows the size of the served collection rather
#: than the size of the request. Named by attribute, because that is how a
#: caller reaches them and what a reintroduction would have to spell.
COLLECTION_WIDE_READS: frozenset[str] = frozenset(
    {
        "_scroll_all_ids",
        "_scroll_content",
        "scroll_code_content",
        "scroll_document_content",
        "scroll_index_audit_content",
    }
)

#: The backend's own paging call. Naming the three public scrolls and the two
#: engines beneath them still leaves the client itself reachable - ``client``
#: is a public property on the store, so any indexer can page the collection
#: directly and never spell a store method at all. Matched as a CALL rather
#: than as a bare attribute, because ``scroll`` on its own is a common enough
#: word to catch things that are not this.
RAW_BACKEND_SCROLL = "scroll"

#: Reading every evidence row for a source. Correct for a rebuild, which is
#: republishing all of it anyway, and for an archive, which is preserving it.
#: On a scoped update it is the complete metadata map the issue names.
WHOLE_MAP_READS: frozenset[str] = frozenset({"read_all_publication_evidence"})

#: The function every source type names its scoped reconciliation.
SCOPED_ENTRY_POINT = "_scoped_incremental_locked"


def _scoped_publication_functions() -> Iterator[tuple[str, ast.AST]]:
    """Yield every function that carries out one scoped publication."""
    for path in every_production_file():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - parsed by a dedicated check
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name == SCOPED_ENTRY_POINT:
                yield f"{path.name}:{node.name}", node


def _calls_the_raw_backend(node: ast.AST) -> bool:
    """Whether the subtree calls ``.scroll(...)`` on anything."""
    return any(
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Attribute)
        and inner.func.attr == RAW_BACKEND_SCROLL
        for inner in ast.walk(node)
    )


def _names_in(node: ast.AST) -> set[str]:
    """Every attribute, bare name and imported name the subtree spells."""
    found: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Attribute):
            found.add(inner.attr)
        elif isinstance(inner, ast.Name):
            found.add(inner.id)
        elif isinstance(inner, ast.ImportFrom):
            found.update(alias.name for alias in inner.names)
    return found


class TestScopedPublicationStaysProportional:
    """The two whole-collection costs the issue names, both refused.

    Proven able to fail, in both directions, and recorded here because a
    later reader loosening either assertion has no other way to know what it
    was pinning.

    Adding a ``self.store.scroll_code_content(...)`` call inside
    ``_codebase_indexer._scoped_incremental_locked`` fails
    ``test_no_scoped_path_reaches_a_collection_wide_read``, naming
    ``_codebase_indexer.py:_scoped_incremental_locked`` and
    ``scroll_code_content``. Removing the call passes it again.

    Replacing the batched ``publication_evidence_for_paths`` loop in that same
    function with ``read_all_publication_evidence(proof_snapshot)`` - which
    returns the same mapping, and leaves 4,675 other tests green - fails
    ``test_no_scoped_path_reads_the_complete_evidence_map`` on that name.
    Restoring the batched loop passes it again.

    Two ways around an earlier version of this guard, both closed and both
    re-driven. ``self.store._scroll_content(...)`` reaches the engine the
    three public scrolls delegate to and skips every name they spell; it now
    fails the collection-wide assertions on ``_scroll_content``.
    ``self.store.client.scroll(...)`` skips the store altogether - ``client``
    is a public property - and now fails the two backend assertions. Removing
    either call passes them again.
    """

    #: Modules that legitimately read a whole collection, each because its
    #: subject IS the whole collection. Anything not listed here has to ask
    #: for the paths it actually wants.
    _WHOLE_COLLECTION_OWNERS: ClassVar[dict[str, str]] = {
        "store_catalog.py": "defines the reads; the store is where they live",
        "_route_migration.py": "re-routes every stored point to a new layout",
        "_index_integrity.py": (
            "the explicit audit, whose subject is the whole collection and"
            " which this issue keeps as the authoritative verification path"
        ),
    }

    #: Modules that may page the backend client directly. The store owns its
    #: own engine; a migration rewrites every point by definition. Nothing
    #: else should be holding the client at all.
    _RAW_BACKEND_OWNERS: ClassVar[dict[str, str]] = {
        "store_runtime.py": "owns the client and is where paging is implemented",
        "storage_migration.py": "copies every point from one backend to another",
    }

    def test_no_scoped_path_reaches_a_collection_wide_read(self) -> None:
        """No scoped publication function scrolls the served collection."""
        offenders = {
            where: sorted(_names_in(node) & COLLECTION_WIDE_READS)
            for where, node in _scoped_publication_functions()
            if _names_in(node) & COLLECTION_WIDE_READS
        }

        assert not offenders, (
            f"scoped publication reaches a collection-wide read: {offenders}. "
            "Ask canonical proof for the paths that changed instead."
        )

    def test_no_scoped_path_pages_the_backend_directly(self) -> None:
        """No scoped publication function reaches past the store to the client.

        Naming the store's scroll methods is not enough on its own: ``client``
        is a public property, so a caller can page the collection without
        spelling a single one of them.
        """
        offenders = sorted(
            where
            for where, node in _scoped_publication_functions()
            if _calls_the_raw_backend(node)
        )

        assert not offenders, (
            f"scoped publication pages the backend directly: {offenders}. "
            "Ask canonical proof for the paths that changed instead."
        )

    def test_no_scoped_path_reads_the_complete_evidence_map(self) -> None:
        """No scoped publication function loads every evidence row."""
        offenders = {
            where: sorted(_names_in(node) & WHOLE_MAP_READS)
            for where, node in _scoped_publication_functions()
            if _names_in(node) & WHOLE_MAP_READS
        }

        assert not offenders, (
            f"scoped publication reads the complete evidence map: {offenders}. "
            "Read the changed paths in bounded batches instead."
        )

    def test_the_scoped_functions_this_guards_still_exist(self) -> None:
        """A guard over nothing passes forever; pin what it is scanning.

        Both assertions above are satisfied by an empty scan, so a rename of
        the scoped entry point would retire them silently. This fails instead.
        """
        found = {where for where, _node in _scoped_publication_functions()}

        assert found >= {
            f"_codebase_indexer.py:{SCOPED_ENTRY_POINT}",
            f"_vault_incremental.py:{SCOPED_ENTRY_POINT}",
        }, found

    def test_the_package_scan_actually_reaches_the_package(self) -> None:
        """The two package-wide rules below pass over an empty file list.

        Same shape as the scoped-entry-point pin above: both are `assert not
        offenders`, so a helper that stopped finding production modules would
        retire them without failing anything.
        """
        names = {path.name for path in every_production_file()}

        assert len(names) > 100, len(names)
        assert {"store_catalog.py", "store_runtime.py"} <= names, sorted(names)[:10]

    def test_only_declared_owners_read_a_whole_collection(self) -> None:
        """A collection-wide read anywhere else has to be argued for first."""
        offenders: dict[str, list[str]] = {}
        for path in every_production_file():
            if path.name in self._WHOLE_COLLECTION_OWNERS:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            reached = sorted(_names_in(tree) & COLLECTION_WIDE_READS)
            if reached:
                offenders[path.name] = reached

        assert not offenders, (
            f"collection-wide read outside its declared owners: {offenders}. "
            "Either scope the read, or record the module above with the "
            "reason its subject really is the whole collection."
        )

    def test_only_declared_owners_page_the_backend_directly(self) -> None:
        """Holding the client and paging it has to be argued for first."""
        offenders: list[str] = []
        for path in every_production_file():
            if path.name in self._RAW_BACKEND_OWNERS:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - parsed elsewhere
                continue
            if _calls_the_raw_backend(tree):
                offenders.append(path.name)

        assert not offenders, (
            f"backend paged outside its declared owners: {sorted(offenders)}. "
            "Go through the store, or record the module above with the reason "
            "it must hold the client itself."
        )


def test_no_scroll_backed_file_count_survives_on_the_store() -> None:
    """The scroll-backed distinct-file count is gone, not merely unused.

    It counted distinct paths by scrolling every point in the served
    collection - the exact cost this issue exists to remove - and it had no
    caller left once publication started reading breadth from canonical
    proof. Left defined, with a docstring explaining when to reach for it, it
    is one completion away from coming back.

    Proven able to fail: re-adding a ``count_code_files`` method to the store
    fails this on the attribute.
    """
    assert not hasattr(_VaultCatalogMixin, "count_code_files"), (
        "count_code_files is back on the store; publication reads breadth "
        "from canonical proof and must not scroll the collection for it"
    )
