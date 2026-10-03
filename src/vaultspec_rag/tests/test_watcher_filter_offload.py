"""CPU watcher intake keeps filtering off the serving loop."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self, cast

import pytest
import watchfiles.main as watchfiles_main
from watchfiles import Change

from .. import watcher_intake
from ..graph_cache import GraphCache
from ..indexer._content_policy import ContentKind
from ..job_models import JobSource
from ..service import ServiceRegistry
from ..watcher_intake import _ControllerBinding, _WatcherEventBatch
from ..watcher_retry import WatcherSource
from ..watcher_retry_policy import WatcherRetryPolicy
from ..watcher_runtime import (
    WatcherChangeRouting,
    WatcherConfiguration,
    WatcherConvergenceSlot,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from types import TracebackType

pytestmark = pytest.mark.unit


@dataclass
class _NativeWatch:
    batches: deque[set[tuple[int, str]]]
    before_batch: Callable[[int], None] | None = None
    delivered: int = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        pass

    def watch(self, *_args: object) -> set[tuple[int, str]] | Literal["stop"]:
        if not self.batches:
            return "stop"
        if self.before_batch is not None:
            self.before_batch(self.delivered)
        self.delivered += 1
        return self.batches.popleft()


@dataclass(frozen=True)
class _Intake:
    configuration: WatcherConfiguration
    routing: WatcherChangeRouting
    bindings: tuple[_ControllerBinding, ...]
    native: _NativeWatch


def _configure_intake(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    batches: Iterable[set[tuple[Change, str]]],
    *,
    before_batch: Callable[[int], None] | None = None,
) -> _Intake:
    root = root.resolve()
    registry = ServiceRegistry()
    bindings: list[_ControllerBinding] = []
    for source in (WatcherSource.VAULT, WatcherSource.CODE, WatcherSource.DOCUMENT):
        retry = WatcherRetryPolicy.for_root(root, source)
        slot = WatcherConvergenceSlot(JobSource(source.value), root, registry, retry)
        bindings.append(
            _ControllerBinding(watcher_intake._new_controller(retry), slot, retry)
        )
    routing = WatcherChangeRouting(
        root,
        root / ".vault",
        None,
        bindings[0].slot,
        bindings[1].slot,
        bindings[2].slot,
    )
    configuration = WatcherConfiguration(
        root, routing.vault_dir, asyncio.Event(), GraphCache(), registry=registry
    )
    native = _NativeWatch(
        deque({(int(change), path) for change, path in batch} for batch in batches),
        before_batch,
    )

    def native_factory(*_args: object, **_kwargs: object) -> _NativeWatch:
        return native

    async def initialize(
        _configuration: WatcherConfiguration,
    ) -> tuple[WatcherChangeRouting, tuple[_ControllerBinding, ...]]:
        return routing, tuple(bindings)

    def unregister(_root: Path) -> None:
        pass

    monkeypatch.setattr(watchfiles_main, "RustNotify", native_factory)
    monkeypatch.setattr(watcher_intake, "_initialize_watcher_bindings", initialize)
    monkeypatch.setattr(
        "vaultspec_rag.server._watcher._unregister_watcher_controllers",
        unregister,
    )
    monkeypatch.setattr(
        "vaultspec_rag.server._watcher._wake_watcher_scheduler", lambda: None
    )
    return _Intake(configuration, routing, tuple(bindings), native)


@pytest.mark.parametrize("stage", ["filter", "classification"])
async def test_intake_batch_work_leaves_event_loop_responsive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    # Mutation: running either batch operation inline prevents the scheduled
    # callback from executing until the barrier's worker has been released.
    intake = _configure_intake(
        tmp_path, monkeypatch, [{(Change.modified, str(tmp_path / ".gitignore"))}]
    )
    entered = threading.Event()
    loop_progress = threading.Event()
    released = threading.Event()
    progressed_while_blocked: list[bool] = []
    call_threads: list[int] = []
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()

    def wait_at_barrier() -> None:
        call_threads.append(threading.get_ident())
        entered.set()
        assert released.wait(5.0), "batch barrier release must remain bounded"

    original_filter = watcher_intake._filter_watcher_changes
    original_classifier = watcher_intake._classify_watcher_changes

    def filter_batch(
        changes: Iterable[tuple[Change, str]], *, routing: WatcherChangeRouting
    ) -> set[tuple[Change, str]]:
        wait_at_barrier()
        return original_filter(changes, routing=routing)

    def classify_batch(
        changes: Iterable[tuple[Change, str]], *, routing: WatcherChangeRouting
    ) -> _WatcherEventBatch:
        wait_at_barrier()
        return original_classifier(changes, routing=routing)

    if stage == "filter":
        monkeypatch.setattr(watcher_intake, "_filter_watcher_changes", filter_batch)
    else:
        monkeypatch.setattr(watcher_intake, "_classify_watcher_changes", classify_batch)

    def release_after_loop_observation() -> None:
        if entered.wait(5.0):
            loop.call_soon_threadsafe(loop_progress.set)
            progressed_while_blocked.append(loop_progress.wait(1.0))
        released.set()

    observer = threading.Thread(target=release_after_loop_observation, daemon=True)
    observer.start()
    try:
        await watcher_intake.watch_and_reindex(intake.configuration)
    finally:
        released.set()
        await asyncio.to_thread(observer.join, 5.0)
    assert progressed_while_blocked == [True], (
        f"{stage} must release the serving loop before its worker returns"
    )
    assert call_threads == [call_threads[0]] and call_threads[0] != loop_thread
    assert intake.bindings[1].retry_policy.state.pending_paths


async def test_raw_watch_batches_keep_the_application_filter_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mutation: omitting watch_filter=None reintroduces watchfiles' default
    # exclusions before the canonical application's path filter can run.
    intake = _configure_intake(
        tmp_path,
        monkeypatch,
        [{(Change.modified, str(tmp_path / ".git" / ".gitignore"))}],
    )
    await watcher_intake.watch_and_reindex(intake.configuration)
    assert [
        item.relative_path
        for item in intake.bindings[1].retry_policy.state.pending_paths
    ] == [".git/.gitignore"], (
        "raw event batches must reach the canonical application filter"
    )


@pytest.mark.parametrize("stage", ["initial", "control"])
async def test_policy_discovery_leaves_event_loop_responsive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    # Mutation: running either production refresh inline holds the serving
    # loop while actual policy discovery waits at its filesystem-read boundary.
    ignore_file = tmp_path / ".gitignore"
    ignore_file.write_text("ignored.py\n", encoding="utf-8")
    block_next_read = threading.Event()
    if stage == "initial":
        block_next_read.set()

    def before_batch(_index: int) -> None:
        if stage == "control":
            block_next_read.set()

    intake = _configure_intake(
        tmp_path,
        monkeypatch,
        [{(Change.modified, str(ignore_file))}],
        before_batch=before_batch,
    )
    actual_read_text = Path.read_text
    entered = threading.Event()
    loop_progress = threading.Event()
    released = threading.Event()
    progressed_while_blocked: list[bool] = []
    read_threads: list[int] = []
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()

    def read_text(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> str:
        if path == ignore_file and block_next_read.is_set():
            block_next_read.clear()
            read_threads.append(threading.get_ident())
            entered.set()
            assert released.wait(5.0), "policy-read barrier must remain bounded"
        return actual_read_text(path, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "read_text", read_text)

    def release_after_loop_observation() -> None:
        if entered.wait(5.0):
            loop.call_soon_threadsafe(loop_progress.set)
            progressed_while_blocked.append(loop_progress.wait(1.0))
        released.set()

    observer = threading.Thread(target=release_after_loop_observation, daemon=True)
    observer.start()
    try:
        await watcher_intake.watch_and_reindex(intake.configuration)
    finally:
        released.set()
        await asyncio.to_thread(observer.join, 5.0)
    assert progressed_while_blocked == [True], (
        f"{stage} policy refresh must release the serving loop during discovery"
    )
    assert read_threads == [read_threads[0]] and read_threads[0] != loop_thread
    assert [
        item.relative_path
        for item in intake.bindings[1].retry_policy.state.pending_paths
    ] == [".gitignore"]


async def test_control_change_preserves_prefilter_and_new_policy_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mutations: bypassing the prefilter, refreshing it early, or retaining the
    # old policy for classification changes this first batch's exact scope.
    (tmp_path / ".gitignore").write_text("blocked.py\n", encoding="utf-8")
    initial = {
        (Change.modified, str(tmp_path / ".gitignore")),
        (Change.modified, str(tmp_path / "blocked.py")),
        (Change.modified, str(tmp_path / "newly_blocked.py")),
    }
    next_batch = {(Change.modified, str(tmp_path / "blocked.py"))}

    def change_policy(index: int) -> None:
        if index == 0:
            (tmp_path / ".gitignore").write_text("newly_blocked.py\n", encoding="utf-8")

    intake = _configure_intake(
        tmp_path, monkeypatch, [initial, next_batch], before_batch=change_policy
    )
    actual_persist = watcher_intake._persist_and_observe_batch
    accepted_batches: list[frozenset[str]] = []

    async def persist(
        batch: _WatcherEventBatch,
        bindings: tuple[_ControllerBinding, ...],
        *,
        root_dir: Path,
    ) -> bool:
        accepted_batches.append(
            frozenset(
                change.path.relative_to(root_dir).as_posix() for change in batch.changes
            )
        )
        return await actual_persist(batch, bindings, root_dir=root_dir)

    monkeypatch.setattr(watcher_intake, "_persist_and_observe_batch", persist)
    await watcher_intake.watch_and_reindex(intake.configuration)
    assert "blocked.py" not in accepted_batches[0], (
        "previous policy must reject blocked paths before control-file advancement"
    )
    assert "newly_blocked.py" not in accepted_batches[0], (
        "control-file policy must advance before accepted paths are classified"
    )
    assert accepted_batches == [frozenset({".gitignore"}), frozenset({"blocked.py"})], (
        "prefilter must use the previous snapshot before control-file policy advances"
    )
    assert {
        item.relative_path
        for item in intake.bindings[1].retry_policy.state.pending_paths
    } == {
        ".gitignore",
        "blocked.py",
    }
    assert {
        item.relative_path
        for item in intake.bindings[2].retry_policy.state.pending_paths
    } == {".gitignore"}


async def test_filtered_intake_keeps_sources_and_deleted_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / ".vaultragpreprocess.toml").write_text(
        'version = 2\n[[rule]]\npattern = "docs/*.pdf"\ntarget = "document"\n'
        'extractor_version = "1.0.0"\ncommand = "extract {path}"\non_error = "skip"\n',
        encoding="utf-8",
    )
    files = {
        (Change.modified, str(tmp_path / ".vault" / "note.md")),
        (Change.added, str(tmp_path / "src" / "source.py")),
        (Change.modified, str(tmp_path / "docs" / "guide.pdf")),
        (Change.deleted, str(tmp_path / "deleted.py")),
        (Change.modified, str(tmp_path / "ignored.py")),
        (Change.modified, str(tmp_path.parent / "outside.py")),
        (Change.modified, str(tmp_path / "image.jpg")),
    }
    intake = _configure_intake(tmp_path, monkeypatch, [files])
    ownership_reads: list[str] = []

    def owners(_root: Path, rel_path: str) -> frozenset[ContentKind]:
        ownership_reads.append(rel_path)
        return frozenset({ContentKind.DOCUMENT})

    monkeypatch.setattr(watcher_intake, "prior_stored_owners", owners)
    await watcher_intake.watch_and_reindex(intake.configuration)
    scopes = {
        binding.retry_policy.state.source: {
            item.relative_path for item in binding.retry_policy.state.pending_paths
        }
        for binding in intake.bindings
    }
    assert scopes[WatcherSource.VAULT] == {".vault/note.md"}
    assert scopes[WatcherSource.DOCUMENT] == {"docs/guide.pdf", "deleted.py"}, (
        "admitted deletion must retain its stored source ownership"
    )
    assert scopes[WatcherSource.CODE] == {"src/source.py"}
    assert ownership_reads == ["deleted.py"]


async def test_ignored_deletion_never_reaches_prior_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mutation: bypassing the intake prefilter widens deletion inputs even
    # though the subsequent classifier still uses the correct current policy.
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    intake = _configure_intake(
        tmp_path, monkeypatch, [{(Change.deleted, str(tmp_path / "ignored.py"))}]
    )
    ownership_reads: list[str] = []

    def owners(_root: Path, rel_path: str) -> frozenset[ContentKind]:
        ownership_reads.append(rel_path)
        return frozenset({ContentKind.DOCUMENT})

    monkeypatch.setattr(watcher_intake, "prior_stored_owners", owners)
    await watcher_intake.watch_and_reindex(intake.configuration)
    assert ownership_reads == [], (
        "ignored deletion must be rejected before any prior-owner read"
    )
    assert intake.bindings[2].retry_policy.state.pending_paths == ()


class _InvalidChange(Enum):
    modified = "invalid"


def test_classifier_still_rejects_unknown_change_kinds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mutation: removing the accepted-kind check would turn this foreign enum
    # into an ordinary MODIFIED observation because its name is valid.
    intake = _configure_intake(tmp_path, monkeypatch, [])
    batch = watcher_intake._classify_watcher_changes(
        [(cast("Change", _InvalidChange.modified), str(tmp_path / ".gitignore"))],
        routing=intake.routing,
    )
    assert batch.changes == (), "unknown event kinds must never become durable scope"
    assert all(
        binding.retry_policy.state.pending_paths == () for binding in intake.bindings
    )
