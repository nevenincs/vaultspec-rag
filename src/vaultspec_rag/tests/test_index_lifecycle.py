"""Unit tests for the one index-run lifecycle every indexer shares.

Two concerns live here. The behavioural tests drive the shared wrapper
against a real store and the real storage manifest - no GPU, no Qdrant
server, nothing stubbed - and pin that a run stamps the persisted
activity clock at both edges and emits the operator index events.

The guard tests pin that every indexer's run entry points reach that
behaviour through the shared wrapper rather than carrying their own copy,
so a newly added content domain cannot silently ship without either.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pathlib
import pkgutil
from typing import TYPE_CHECKING, cast

import pytest

from .. import indexer as indexer_package
from ..indexer._index_lifecycle import (
    INDEX_EVENT_NAMESPACE,
    run_index_lifecycle,
)
from ..indexer._vault_prep import IndexResult
from ..job_control import NO_RUN_CONTROL
from ..storage_manifest import load_manifest, record_root
from ..store import root_collection_prefix

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from ..store import VaultStore

pytestmark = [pytest.mark.unit]

logger = logging.getLogger(__name__)

#: Nothing listens here. The stamp path never needs the server, and a real
#: client against a dead port keeps the store real rather than stubbed.
_DEAD_QDRANT_URL = "http://127.0.0.1:59997"

#: A stamp no clock would ever produce, written from inside the body so the
#: post-body stamp is provable without depending on clock resolution.
_BODY_SENTINEL = "1999-01-01T00:00:00+00:00"

#: The run entry points every indexer exposes to callers.
_RUN_ENTRY_POINTS = ("full_index", "incremental_index")


def _result() -> IndexResult:
    return IndexResult(
        total=7,
        added=3,
        updated=2,
        removed=1,
        duration_ms=11,
        device="cuda",
        files=4,
    )


@pytest.fixture
def server_mode_store(
    isolated_status_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[VaultStore]:
    """A real store in server mode over a temp manifest directory.

    The activity clock is a server-mode concern - it no-ops against a
    local on-disk store - so these tests need the URL knob set. The
    manifest it writes resolves under the managed dir, hence the
    isolation fixture.
    """
    del isolated_status_dir
    from ..config import reset_config
    from ..store import VaultStore

    monkeypatch.setenv("VAULTSPEC_RAG_QDRANT_URL", _DEAD_QDRANT_URL)
    reset_config()
    root = tmp_path / "root"
    root.mkdir()
    store = VaultStore(root)
    try:
        yield store
    finally:
        store.close()
        reset_config()


def _run(
    store: VaultStore,
    body: Callable[[], IndexResult],
    *,
    mode: str = "full",
    clean: bool = False,
) -> IndexResult:
    return run_index_lifecycle(
        body,
        event_logger=logger,
        store=store,
        source="document",
        mode=mode,
        clean=clean,
        root=store.root_dir,
        run_control=NO_RUN_CONTROL,
    )


def _stamp_of(store: VaultStore) -> str:
    entry = load_manifest().get(root_collection_prefix(store.root_dir))
    return "" if entry is None else entry.last_indexed


def _index_events(
    caplog: pytest.LogCaptureFixture,
) -> list[tuple[str, dict[str, object]]]:
    """The index events captured, as ``(event name, structured fields)``.

    Read off the structured attributes the event helper attaches rather
    than the rendered message, so the assertions pin the contract and not
    the formatting.
    """
    events: list[tuple[str, dict[str, object]]] = []
    for record in caplog.records:
        if getattr(record, "vaultspec_event_namespace", None) != INDEX_EVENT_NAMESPACE:
            continue
        name = cast("str", getattr(record, "vaultspec_event", ""))
        fields = cast(
            "dict[str, object]", getattr(record, "vaultspec_event_fields", {})
        )
        events.append((name, fields))
    return events


class TestActivityClock:
    def test_the_clock_is_stamped_before_the_body_runs(
        self,
        server_mode_store: VaultStore,
    ) -> None:
        """A run that outlives a maintenance tick must not look idle."""
        seen: list[str] = []

        def body() -> IndexResult:
            seen.append(_stamp_of(server_mode_store))
            return _result()

        _run(server_mode_store, body)

        assert seen, "the body never ran"
        assert seen[0], (
            "the activity clock carried no stamp when the body started, so a "
            "long run reads as idle for its whole duration"
        )

    def test_the_clock_is_stamped_again_after_the_body_returns(
        self,
        server_mode_store: VaultStore,
    ) -> None:
        """Completion refreshes the clock the run's own work may have aged."""

        def body() -> IndexResult:
            record_root(
                server_mode_store.root_dir,
                backend="server",
                last_indexed=_BODY_SENTINEL,
            )
            return _result()

        _run(server_mode_store, body)

        assert _stamp_of(server_mode_store) != _BODY_SENTINEL, (
            "the stamp written inside the body survived the run, so completion "
            "never refreshed the activity clock"
        )

    def test_a_failed_run_leaves_the_start_stamp_behind(
        self,
        server_mode_store: VaultStore,
    ) -> None:
        """A crash mid-write still proves the root was recently active."""

        def body() -> IndexResult:
            raise OSError("storage went away")

        with pytest.raises(OSError, match="storage went away"):
            _run(server_mode_store, body)

        assert _stamp_of(server_mode_store), (
            "a run that failed mid-write left no stamp, so an interrupted "
            "root looks idle to the reclaim tier"
        )


class TestIndexEvents:
    def test_a_successful_run_emits_started_then_completed(
        self,
        server_mode_store: VaultStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO):
            _run(server_mode_store, _result, mode="scoped_incremental")

        events = _index_events(caplog)
        assert [name for name, _ in events] == ["started", "completed"]
        started_fields = events[0][1]
        assert started_fields["source"] == "document"
        assert started_fields["mode"] == "scoped_incremental"
        assert started_fields["clean"] is False
        completed_fields = events[1][1]
        assert completed_fields["source"] == "document"
        assert completed_fields["mode"] == "scoped_incremental"
        assert completed_fields["total"] == 7
        assert completed_fields["added"] == 3
        assert completed_fields["updated"] == 2
        assert completed_fields["removed"] == 1
        assert completed_fields["duration_ms"] == 11

    def test_completion_extras_ride_the_completed_event(
        self,
        server_mode_store: VaultStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO):
            run_index_lifecycle(
                _result,
                event_logger=logger,
                store=server_mode_store,
                source="code",
                mode="full",
                clean=True,
                root=server_mode_store.root_dir,
                run_control=NO_RUN_CONTROL,
                completion_fields=lambda result: {"files": result.files},
            )

        completed_fields = _index_events(caplog)[-1][1]
        assert completed_fields["files"] == 4
        assert completed_fields["clean"] is True

    def test_a_failing_run_emits_failed_and_re_raises(
        self,
        server_mode_store: VaultStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def body() -> IndexResult:
            raise RuntimeError("chunker died")

        with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
            _run(server_mode_store, body)

        events = _index_events(caplog)
        assert [name for name, _ in events] == ["started", "failed"]
        assert "chunker died" in str(events[1][1]["error"])


def _indexer_run_entry_points() -> list[tuple[str, Callable[..., object]]]:
    """Every ``full_index`` / ``incremental_index`` the indexer package defines.

    Enumerated rather than listed: a fourth content domain has to be
    discovered by this test, not remembered by whoever adds it.
    """
    found: list[tuple[str, Callable[..., object]]] = []
    for info in pkgutil.iter_modules(indexer_package.__path__):
        module = importlib.import_module(f"{indexer_package.__name__}.{info.name}")
        for class_name, candidate in vars(module).items():
            if not inspect.isclass(candidate):
                continue
            if candidate.__module__ != module.__name__:
                continue
            for entry_point in _RUN_ENTRY_POINTS:
                method = candidate.__dict__.get(entry_point)
                if inspect.isfunction(method):
                    found.append((f"{info.name}:{class_name}.{entry_point}", method))
    return found


class TestNoIndexerCarriesItsOwnCopy:
    def test_the_package_still_exposes_every_known_run_entry_point(self) -> None:
        """Guards the enumeration itself: a silent empty sweep proves nothing."""
        names = {name for name, _ in _indexer_run_entry_points()}
        assert {
            "_codebase_indexer:CodebaseIndexer.full_index",
            "_codebase_indexer:CodebaseIndexer.incremental_index",
            "_document_indexer:DocumentIndexer.full_index",
            "_document_indexer:DocumentIndexer.incremental_index",
            "_vault_indexer:VaultIndexer.full_index",
            "_vault_indexer:VaultIndexer.incremental_index",
        } <= names

    def test_every_run_entry_point_routes_through_the_shared_lifecycle(self) -> None:
        """The wrapper is the only way in, so parity is structural."""
        off_path = [
            name
            for name, method in _indexer_run_entry_points()
            if "run_index_lifecycle" not in method.__code__.co_names
        ]
        assert not off_path, (
            f"these run entry points bypass the shared index lifecycle and so "
            f"stamp no activity clock and emit no index events: {off_path}"
        )

    def test_no_run_entry_point_stamps_the_activity_clock_itself(self) -> None:
        """A pasted-back stamp is the second implementation, not the fix."""
        direct = [
            name
            for name, method in _indexer_run_entry_points()
            if "touch_manifest_last_indexed" in method.__code__.co_names
        ]
        assert not direct, (
            f"these run entry points stamp the activity clock directly instead "
            f"of through the shared index lifecycle: {direct}"
        )

    def test_only_the_shared_lifecycle_names_the_index_event_namespace(self) -> None:
        """One emitter, so the event shape cannot fork per domain."""
        package_dir = pathlib.Path(next(iter(indexer_package.__path__)))
        emitters = sorted(
            path.name
            for path in package_dir.glob("*.py")
            if f'"{INDEX_EVENT_NAMESPACE}"' in path.read_text(encoding="utf-8")
        )
        assert emitters == ["_index_lifecycle.py"], (
            f"index events are emitted from more than the shared lifecycle: {emitters}"
        )
