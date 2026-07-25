"""Every index entry point runs inside the one shared run lifecycle.

Stamping the persisted activity clock and emitting the ``service.index``
started / failed / completed triple used to live as a hand-copied block inside
each public ``full_index`` and ``incremental_index``. Four copies agreed; a
fifth - the document path - never received the stamping fix and ran entirely
silently, advancing no clock and emitting no operator event, for as long as an
indexing pass takes. Nothing failed, because nothing was comparing the copies.

These tests are that comparison, in two halves that answer different questions.

The behavioural half drives the real wrapper against a real server-mode
``VaultStore`` and the real on-disk storage manifest, with no mocks anywhere:
it proves the clock is genuinely advanced *before* the body runs (observed from
inside the body, which is the only place the mid-write property is visible),
genuinely advanced again on completion, still advanced when the body raises,
and that the event triple lands with the shared fields on both outcomes.

The structural half is what makes the fix hold. It discovers every
``*Indexer`` class in the package from source rather than from a list, and
requires each entry point to delegate to the shared wrapper - so a fifth
indexer, or a sixth entry point, is covered the moment it is written rather
than the moment somebody remembers this file. It then requires the stamp call
and the event namespace to have exactly one home, which is what forecloses a
new copy of the block being grown alongside the shared one.

MUTATION PROOFS (run individually, restored immediately, both directions
observed). Inlining the old lifecycle block back into
``DocumentIndexer.full_index`` in place of the ``run_index_lifecycle`` call
fails ``test_every_entry_point_delegates_to_shared_lifecycle`` on its
delegation assertion for that entry point, and fails
``test_activity_stamp_has_exactly_one_call_site`` and
``test_index_event_namespace_has_exactly_one_call_site`` on their
single-home assertions. Deleting the pre-body ``clock.touch...`` line in
``_index_lifecycle`` fails ``test_clock_is_stamped_before_the_body_runs`` on
the from-inside-the-body assertion while every other test here still passes.
Deleting the post-body stamp fails ``test_clock_is_stamped_again_on_completion``
on the sentinel assertion. Deleting the ``failed`` emission fails
``test_failing_run_emits_failed_and_no_completed``. Breaking the source
discovery so it returns nothing fails
``test_entry_point_discovery_covers_every_content_kind``, which exists
precisely so the delegation test cannot pass vacuously.
"""

from __future__ import annotations

import ast
import logging
import pathlib
from typing import TYPE_CHECKING, NamedTuple

import pytest

from .. import indexer as indexer_package
from ..indexer._index_lifecycle import (
    INDEX_EVENT_NAMESPACE,
    incremental_mode,
    run_index_lifecycle,
)
from ..indexer._vault_prep import IndexResult
from ..job_control import NO_RUN_CONTROL
from ..storage_manifest import load_manifest, record_root
from ..store import VaultStore, root_collection_prefix
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from _pytest.logging import LogCaptureFixture

pytestmark = [pytest.mark.unit]

#: The public entry points every content kind exposes. A new one added to any
#: indexer is picked up here without editing this file.
_ENTRY_POINTS = frozenset({"full_index", "incremental_index"})

#: The module that owns the lifecycle, and the two things it owns exclusively.
_LIFECYCLE_MODULE = "_index_lifecycle.py"
_LIFECYCLE_CALL = "run_index_lifecycle"
_STAMP_CALL = "touch_manifest_last_indexed"

#: The stamp the test seeds before a run, and re-seeds from inside the body.
#: Recognisably not a real timestamp, so a failure names the write that did
#: not happen rather than an ambiguous clock comparison.
_STALE_STAMP = "1999-01-01T00:00:00+00:00"

#: The logger the subject run emits through, so the capture is scoped to it.
_SUBJECT_LOGGER = f"{__name__}.subject"


class _EntryPoint(NamedTuple):
    """One public index entry point located in package source."""

    module: str
    cls: str
    method: str
    node: ast.FunctionDef

    @property
    def label(self) -> str:
        return f"{self.cls}.{self.method}"


def _package_sources() -> list[pathlib.Path]:
    """Return every module file in the indexer package."""
    root = pathlib.Path(str(indexer_package.__file__)).parent
    return sorted(root.glob("*.py"))


def _called_names(node: ast.AST) -> set[str]:
    """Return every bare function name called anywhere beneath ``node``."""
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        target = child.func
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def _discover_entry_points() -> list[_EntryPoint]:
    """Locate every public index entry point by parsing package source.

    Deliberately source-driven rather than import-driven: the property under
    test is about what the code says, an import would pull the whole indexer
    dependency chain into a unit test, and a hand-maintained list of classes
    is the exact failure mode - something present but unlisted - that this
    file exists to prevent.
    """
    found: list[_EntryPoint] = []
    for path in _package_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Indexer"):
                continue
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name in _ENTRY_POINTS:
                    found.append(_EntryPoint(path.name, node.name, member.name, member))
    return found


def _modules_calling(name: str) -> set[str]:
    """Return the package modules containing a call to ``name``."""
    return {
        path.name
        for path in _package_sources()
        if name
        in _called_names(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
    }


def _modules_with_string(literal: str) -> set[str]:
    """Return the package modules using ``literal`` as a live string constant.

    Matched through the AST rather than the raw text, and with bare string
    statements excluded, so naming the namespace in a comment or a docstring
    is not miscounted as a second implementation of it.
    """
    hits: set[str] = set()
    for path in _package_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        documentation = {
            id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and node.value == literal
                and id(node) not in documentation
            ):
                hits.add(path.name)
    return hits


# --------------------------------------------------------------------------
# Structural half: the shared wrapper is the only implementation, and every
# entry point reaches it.
# --------------------------------------------------------------------------


def test_entry_point_discovery_covers_every_content_kind() -> None:
    """The discovery finds all three kinds, so the parity test is not vacuous.

    Without this, a discovery that silently matched nothing would make
    ``test_every_entry_point_delegates_to_shared_lifecycle`` pass over an
    empty parameter set while the regression it guards sat in the tree.
    """
    found = {(entry.cls, entry.method) for entry in _discover_entry_points()}
    assert found == {
        ("CodebaseIndexer", "full_index"),
        ("CodebaseIndexer", "incremental_index"),
        ("VaultIndexer", "full_index"),
        ("VaultIndexer", "incremental_index"),
        ("DocumentIndexer", "full_index"),
        ("DocumentIndexer", "incremental_index"),
    }


@pytest.mark.parametrize(
    "entry",
    _discover_entry_points(),
    ids=lambda entry: entry.label,
)
def test_every_entry_point_delegates_to_shared_lifecycle(entry: _EntryPoint) -> None:
    """Each public entry point runs its pass inside the shared wrapper.

    An entry point that stamps and emits by hand passes every functional test
    it has - and diverges the first time the shared decision changes. This is
    the assertion that makes divergence impossible rather than unlikely.
    """
    called = _called_names(entry.node)
    assert _LIFECYCLE_CALL in called, (
        f"{entry.label} does not delegate to {_LIFECYCLE_CALL}; the activity "
        "clock and the service.index events are decided in one place and every "
        "entry point must route through it"
    )


def test_activity_stamp_has_exactly_one_call_site() -> None:
    """The activity clock is stamped from the shared wrapper and nowhere else."""
    assert _modules_calling(_STAMP_CALL) == {_LIFECYCLE_MODULE}


def test_index_event_namespace_has_exactly_one_call_site() -> None:
    """The index event namespace is spelled in the shared wrapper and nowhere else."""
    assert _modules_with_string(INDEX_EVENT_NAMESPACE) == {_LIFECYCLE_MODULE}


def test_incremental_mode_labels_scope() -> None:
    """Scoped and unscoped incremental runs report distinguishable modes."""
    assert incremental_mode(None) == "incremental"
    assert incremental_mode(()) == "scoped_incremental"


# --------------------------------------------------------------------------
# Behavioural half: the shared wrapper really advances the real persisted
# clock and really emits the real events.
# --------------------------------------------------------------------------


@pytest.fixture
def stamped_store(tmp_path: pathlib.Path) -> Generator[tuple[VaultStore, str]]:
    """Yield a real server-mode store and this root's manifest prefix.

    Server mode is what makes the stamp observable at all - the local backend
    keeps no manifest - and a ``VaultStore`` reaches the manifest without ever
    contacting the configured URL, so no server is needed to prove the write.
    The managed dir and the Qdrant storage dir are both relocated: the manifest
    resolves under the former and the identity sidecar and machine lock under
    the latter, and isolating only one writes into the operator's real state.
    """
    from ..config import EnvVar

    root = tmp_path / "root"
    root.mkdir()
    with managed_env(
        **{
            EnvVar.STATUS_DIR.value: str(tmp_path / "managed"),
            EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant"),
            # A port nothing is listening on: the manifest write under test
            # is pure filesystem, and a reachable URL would only add a
            # dependency the assertion does not need.
            EnvVar.QDRANT_URL.value: "http://127.0.0.1:1",
        }
    ):
        store = VaultStore(root)
        try:
            yield store, root_collection_prefix(root)
        finally:
            store.close()


def _seed_stale(store: VaultStore, prefix: str) -> None:
    """Record this root with an obviously stale stamp."""
    record_root(store.root_dir, backend="server", last_indexed=_STALE_STAMP)
    assert load_manifest()[prefix].last_indexed == _STALE_STAMP


def _stamp(prefix: str) -> str:
    """Return the currently persisted stamp for ``prefix``."""
    return load_manifest()[prefix].last_indexed


def _result() -> IndexResult:
    """A result shaped like a real run's, for the completion event fields."""
    return IndexResult(
        total=7,
        added=3,
        updated=2,
        removed=1,
        duration_ms=11,
        device="cuda",
        files=5,
        preprocess_ok=4,
        preprocess_skipped=0,
    )


def _run(
    store: VaultStore,
    body: Callable[[], IndexResult],
    *,
    source: str = "document",
    mode: str = "full",
) -> IndexResult:
    """Drive the real lifecycle around ``body``."""
    return run_index_lifecycle(
        clock=store,
        event_logger=logging.getLogger(_SUBJECT_LOGGER),
        source=source,
        mode=mode,
        clean=False,
        root=store.root_dir,
        run_control=NO_RUN_CONTROL,
        body=body,
    )


def test_clock_is_stamped_before_the_body_runs(
    stamped_store: tuple[VaultStore, str],
) -> None:
    """A run advances the persisted clock before it starts doing work.

    Read from inside the body, which is the only vantage point where the
    property matters: a reclaim evaluation landing mid-write sees whatever the
    manifest holds at that instant, and a run that stamped only on completion
    would present an hours-old clock for its entire duration.
    """
    store, prefix = stamped_store
    _seed_stale(store, prefix)
    observed: list[str] = []

    def body() -> IndexResult:
        observed.append(_stamp(prefix))
        return _result()

    _run(store, body)

    assert observed, "the lifecycle never called the body"
    assert observed[0] != _STALE_STAMP, (
        "the persisted clock was still the pre-run stamp while the run was "
        "mid-flight; a maintenance tick landing here would evaluate this root "
        "as idle while it is being written"
    )


def test_clock_is_stamped_again_on_completion(
    stamped_store: tuple[VaultStore, str],
) -> None:
    """A run advances the persisted clock again when its work finishes.

    The body pushes the stamp back to the stale sentinel, so the assertion
    turns on a write actually happening after the body rather than on two
    timestamps a second apart - which the second-resolution stamp could not
    distinguish.
    """
    store, prefix = stamped_store
    _seed_stale(store, prefix)

    def body() -> IndexResult:
        record_root(store.root_dir, backend="server", last_indexed=_STALE_STAMP)
        return _result()

    _run(store, body)

    assert _stamp(prefix) != _STALE_STAMP, (
        "the persisted clock was not refreshed after the run completed"
    )


def test_failed_run_still_leaves_the_clock_advanced(
    stamped_store: tuple[VaultStore, str],
) -> None:
    """A run that raises still leaves the clock advanced by its start stamp.

    The work happened, and it held the writer lock while it did; a failure
    must not present the root as untouched since before the run began.
    """
    store, prefix = stamped_store
    _seed_stale(store, prefix)

    def body() -> IndexResult:
        raise RuntimeError("index run failed")

    with pytest.raises(RuntimeError, match="index run failed"):
        _run(store, body)

    assert _stamp(prefix) != _STALE_STAMP


def _index_events(caplog: LogCaptureFixture) -> list[str]:
    """Return the index-event messages captured, in emission order."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith(INDEX_EVENT_NAMESPACE)
    ]


def test_successful_run_emits_started_then_completed(
    stamped_store: tuple[VaultStore, str],
    caplog: LogCaptureFixture,
) -> None:
    """A run is visible to the operator log surface at both of its edges."""
    store, prefix = stamped_store
    _seed_stale(store, prefix)

    with caplog.at_level(logging.INFO, logger=_SUBJECT_LOGGER):
        _run(store, _result, source="document", mode="incremental")

    events = _index_events(caplog)
    assert len(events) == 2, events
    assert "event=started" in events[0]
    assert "source=document" in events[0]
    assert "mode=incremental" in events[0]
    assert "event=completed" in events[1]
    assert "source=document" in events[1]
    assert "added=3" in events[1]
    assert "removed=1" in events[1]


def test_failing_run_emits_failed_and_no_completed(
    stamped_store: tuple[VaultStore, str],
    caplog: LogCaptureFixture,
) -> None:
    """A failed run reports the failure, and never also reports success."""
    store, prefix = stamped_store
    _seed_stale(store, prefix)

    def body() -> IndexResult:
        raise RuntimeError("index run failed")

    with (
        caplog.at_level(logging.INFO, logger=_SUBJECT_LOGGER),
        pytest.raises(RuntimeError, match="index run failed"),
    ):
        _run(store, body)

    events = _index_events(caplog)
    assert len(events) == 2, events
    assert "event=started" in events[0]
    assert "event=failed" in events[1]
    assert not any("event=completed" in event for event in events)
