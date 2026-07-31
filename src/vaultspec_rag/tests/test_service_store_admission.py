"""One owner for same-root store construction, and an honest lock refusal.

A local-file store keeps an exclusive OS lock on its storage directory for as
long as it is open, and that lock is per open handle rather than per process.
Two stores opened on one root inside a single process therefore refuse each
other exactly as a foreign holder would - so the registry must admit only one
of them at a time, and a refusal must not name a holder it never established.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import pytest

from .._store_locks import VaultStoreLockedError
from ..service import ProjectBusyError, ServiceRegistry
from ..store_runtime import VaultStore

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ..service import ProjectSlot

pytestmark = [pytest.mark.unit]

# Long enough that a thread which is genuinely blocked stays blocked, short
# enough to keep the module fast. The defect these tests cover raises
# immediately rather than waiting, so no larger value buys any confidence.
_BLOCKED_SECONDS = 0.5
_RESUMED_SECONDS = 30.0


def _finished(thread: threading.Thread, timeout: float) -> bool:
    """Return whether *thread* completed within *timeout* seconds."""
    thread.join(timeout=timeout)
    return not thread.is_alive()


def _join_started(thread: threading.Thread) -> None:
    """Join *thread* if it was ever started, so cleanup survives an early failure."""
    if thread.ident is not None:
        thread.join(timeout=_RESUMED_SECONDS)


def _project_root(tmp_path: Path, name: str) -> Path:
    """Return a resolved, existing workspace root the store can open."""
    root = (tmp_path / name).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _wait_for_project_admission(registry: ServiceRegistry, root: Path) -> None:
    """Wait until *root* owns its real registry construction seat."""
    deadline = time.monotonic() + _RESUMED_SECONDS
    while time.monotonic() < deadline:
        with registry._lock:
            if root in registry._project_admissions:
                return
        time.sleep(0.01)
    msg = f"project admission for {root} was never recorded"
    raise AssertionError(msg)


class _TeardownRendezvous:
    """Pause the eviction teardown of one root inside the real teardown.

    Wired through the registry's production ``_on_close_project`` hook - the
    same callback the server uses to stop a watcher - so the pause lands
    between the victim's slot leaving ``_projects`` and its store closing.
    That is exactly the window in which the slot is invisible while its
    storage lock is still held, and it cannot be reached from outside without
    stopping the teardown thread inside it.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, root: Path) -> object:
        """Pause the first teardown of the tracked root; pass everything else."""
        if root == self._root and not self.entered.is_set():
            self.entered.set()
            if not self.release.wait(timeout=_RESUMED_SECONDS):  # pragma: no cover
                msg = "teardown rendezvous was never released"
                raise AssertionError(msg)
        return None


def _force_evict(registry: ServiceRegistry, victim: Path, _spare: Path) -> None:
    """Evict *victim* through the explicit admin eviction path."""
    assert registry.try_evict(victim) == (True, "forced")


def _lru_evict(registry: ServiceRegistry, _victim: Path, spare: Path) -> None:
    """Evict the only resident slot by admitting *spare* over a one-slot cap."""
    registry._idle_ttl_seconds = 0
    registry._max_projects = 1
    with registry.lease(spare):
        pass


def _idle_evict(registry: ServiceRegistry, victim: Path, spare: Path) -> None:
    """Evict *victim* by ageing it past the idle TTL, then leasing *spare*."""
    registry._max_projects = 0
    registry._idle_ttl_seconds = 0.01
    registry._projects[victim].last_access = time.monotonic() - 60.0
    with registry.lease(spare):
        pass


_EVICTION_TRIGGERS = [
    pytest.param(_force_evict, id="forced"),
    pytest.param(_lru_evict, id="lru"),
    pytest.param(_idle_evict, id="idle"),
]


class TestSameRootStoreAdmission:
    """Slot creation and cold store leases never open one root twice at once."""

    def test_cold_store_lease_blocks_slot_creation_on_the_same_root(
        self,
        tmp_path: Path,
    ) -> None:
        """A warming slot waits for a cold lease instead of being refused.

        This is the daemon racing itself: a search on an unbuilt index takes a
        cold store lease to count it, while the watcher warm for the same root
        creates that root's slot on another thread. Both open a store on one
        root, and whichever loses used to fail with a lock refusal blaming a
        process that was never involved.
        """
        registry = ServiceRegistry()
        root = _project_root(tmp_path, "warming")
        slots: list[ProjectSlot] = []
        errors: list[BaseException] = []

        def create_slot() -> None:
            try:
                slots.append(registry.peek_project(root))
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        thread = threading.Thread(target=create_slot, name="slot-creation")
        try:
            with registry.lease_store(root) as store:
                thread.start()
                assert not _finished(thread, _BLOCKED_SECONDS), (
                    "slot creation did not wait for the cold store lease"
                )
                assert store._client is not None
            assert _finished(thread, _RESUMED_SECONDS), (
                "slot creation never resumed after the lease closed"
            )
        finally:
            thread.join(timeout=_RESUMED_SECONDS)
            registry.close_all()

        assert errors == []
        assert len(slots) == 1

    def test_slot_creation_blocks_a_cold_store_lease_on_the_same_root(
        self,
        tmp_path: Path,
    ) -> None:
        """A cold lease waits for an in-flight slot creation on its root.

        Holding the admission directly is what a slot creation holds while it
        builds its store, so this exercises the same guard from the other side
        without having to win a race against the build.
        """
        registry = ServiceRegistry()
        root = _project_root(tmp_path, "cold-behind-warm")
        stores: list[VaultStore] = []
        errors: list[BaseException] = []

        def cold_lease() -> None:
            try:
                with registry.lease_store(root) as store:
                    stores.append(store)
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        thread = threading.Thread(target=cold_lease, name="cold-store-lease")
        try:
            with registry._root_store_admission(root):
                thread.start()
                assert not _finished(thread, _BLOCKED_SECONDS), (
                    "a cold lease opened a store under a held root admission"
                )
            assert _finished(thread, _RESUMED_SECONDS), (
                "the cold lease never resumed after admission was released"
            )
        finally:
            thread.join(timeout=_RESUMED_SECONDS)
            registry.close_all()

        assert errors == []
        assert len(stores) == 1

    def test_concurrent_cold_leases_on_one_root_never_open_two_stores(
        self,
        tmp_path: Path,
    ) -> None:
        """Model-free count probes on one cold root serialize instead of racing."""
        registry = ServiceRegistry()
        root = _project_root(tmp_path, "concurrent-cold")
        worker_count = 6
        barrier = threading.Barrier(worker_count)
        opened: list[Path] = []
        errors: list[BaseException] = []

        def probe() -> None:
            try:
                barrier.wait(timeout=_RESUMED_SECONDS)
                with registry.lease_store(root) as store:
                    opened.append(store.root_dir)
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [
            threading.Thread(target=probe, name=f"cold-probe-{index}")
            for index in range(worker_count)
        ]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=_RESUMED_SECONDS)
        finally:
            registry.close_all()

        assert all(not thread.is_alive() for thread in threads)
        assert errors == []
        assert opened == [root] * worker_count

    def test_cold_leases_on_different_roots_stay_concurrent(
        self,
        tmp_path: Path,
    ) -> None:
        """Two roots hold their stores open at the same instant.

        The rendezvous completes only if both leases are live together, so a
        store-wide guard - one shared across roots rather than one per root -
        breaks the barrier instead of passing it.
        """
        registry = ServiceRegistry()
        roots = [_project_root(tmp_path, "root-a"), _project_root(tmp_path, "root-b")]
        rendezvous = threading.Barrier(len(roots))
        errors: list[BaseException] = []
        overlapped: list[Path] = []

        def lease(root: Path) -> None:
            try:
                with registry.lease_store(root):
                    rendezvous.wait(timeout=_RESUMED_SECONDS)
                    overlapped.append(root)
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [
            threading.Thread(target=lease, args=(root,), name=f"lease-{root.name}")
            for root in roots
        ]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=_RESUMED_SECONDS)
        finally:
            registry.close_all()

        assert errors == []
        assert sorted(overlapped) == sorted(roots)


class TestProjectAdmissionReservations:
    """Bounded cold starts account for a seat before a store is constructed."""

    def test_different_roots_never_construct_beyond_the_capped_seat(
        self,
        tmp_path: Path,
    ) -> None:
        """A second root waits while the first root owns the sole cold seat."""
        registry = ServiceRegistry()
        registry._max_projects = 1
        first_root = _project_root(tmp_path, "first")
        second_root = _project_root(tmp_path, "second")
        first_slots: list[ProjectSlot] = []
        second_slots: list[ProjectSlot] = []
        errors: list[BaseException] = []

        def admit(root: Path, slots: list[ProjectSlot]) -> None:
            try:
                slots.append(registry.peek_project(root))
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        first = threading.Thread(
            target=admit,
            args=(first_root, first_slots),
            name="first-capped-admission",
        )
        second = threading.Thread(
            target=admit,
            args=(second_root, second_slots),
            name="second-capped-admission",
        )
        try:
            with registry._root_store_admission(first_root):
                first.start()
                _wait_for_project_admission(registry, first_root)
                second.start()
                assert not _finished(second, _BLOCKED_SECONDS), (
                    "a second root constructed while the sole admission seat was held"
                )
                with registry._lock:
                    occupied = len(registry._projects) + len(
                        registry._project_admissions
                    )
                    assert occupied <= registry.max_projects
                    assert registry._project_admissions == {first_root}
                assert not (second_root / ".vault" / "data").exists(), (
                    "the blocked root reached real store construction"
                )
            assert _finished(first, _RESUMED_SECONDS)
            assert _finished(second, _RESUMED_SECONDS)
        finally:
            _join_started(first)
            _join_started(second)
            registry.close_all()

        assert errors == []
        assert [slot.store.root_dir for slot in first_slots] == [first_root]
        assert [slot.store.root_dir for slot in second_slots] == [second_root]

    def test_lru_replacement_keeps_the_outgoing_slot_and_incoming_seat_atomic(
        self,
        tmp_path: Path,
    ) -> None:
        """A paused LRU teardown exposes exactly one accounted seat, never two."""
        registry = ServiceRegistry()
        registry._max_projects = 1
        victim = _project_root(tmp_path, "victim")
        incoming = _project_root(tmp_path, "incoming")
        registry.peek_project(victim)
        rendezvous = _TeardownRendezvous(victim)
        registry._on_close_project = rendezvous
        admitted: list[ProjectSlot] = []
        errors: list[BaseException] = []

        def replace_lru() -> None:
            try:
                admitted.append(registry.peek_project(incoming))
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        thread = threading.Thread(target=replace_lru, name="lru-seat-replacement")
        try:
            thread.start()
            assert rendezvous.entered.wait(timeout=_RESUMED_SECONDS), (
                "the LRU replacement did not enter guarded teardown"
            )
            with registry._lock:
                occupied = len(registry._projects) + len(registry._project_admissions)
                assert victim not in registry._projects
                assert registry._project_admissions == {incoming}
                assert occupied == registry.max_projects
            assert not (incoming / ".vault" / "data").exists(), (
                "the incoming store was constructed before the victim closed"
            )
            rendezvous.release.set()
            assert _finished(thread, _RESUMED_SECONDS), (
                "the LRU replacement did not resume after teardown"
            )
        finally:
            rendezvous.release.set()
            registry._on_close_project = None
            _join_started(thread)
            registry.close_all()

        assert errors == []
        assert [slot.store.root_dir for slot in admitted] == [incoming]

    def test_same_root_callers_share_the_one_reserved_construction_seat(
        self,
        tmp_path: Path,
    ) -> None:
        """Concurrent same-root callers publish and receive one real slot object."""
        registry = ServiceRegistry()
        root = _project_root(tmp_path, "shared")
        slots: list[ProjectSlot] = []
        errors: list[BaseException] = []

        def admit() -> None:
            try:
                slots.append(registry.peek_project(root))
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        owner = threading.Thread(target=admit, name="same-root-owner")
        joiner = threading.Thread(target=admit, name="same-root-joiner")
        try:
            with registry._root_store_admission(root):
                owner.start()
                _wait_for_project_admission(registry, root)
                joiner.start()
                assert not _finished(joiner, _BLOCKED_SECONDS), (
                    "the same-root joiner did not wait for the existing seat"
                )
                with registry._lock:
                    assert registry._project_admissions == {root}
                assert not (root / ".vault" / "data").exists(), (
                    "a same-root joiner opened its own store"
                )
            assert _finished(owner, _RESUMED_SECONDS)
            assert _finished(joiner, _RESUMED_SECONDS)
        finally:
            _join_started(owner)
            _join_started(joiner)
            registry.close_all()

        assert errors == []
        assert len(slots) == 2
        assert slots[0] is slots[1]

    def test_failed_constructor_releases_its_seat_for_another_root(
        self,
        tmp_path: Path,
    ) -> None:
        """A real filesystem constructor failure wakes the blocked next root."""
        registry = ServiceRegistry()
        registry._max_projects = 1
        failed_root = (tmp_path / "not-a-directory").resolve()
        failed_root.write_text("this root is intentionally a regular file")
        succeeding_root = _project_root(tmp_path, "succeeds-after-failure")
        failures: list[BaseException] = []
        succeeding_slots: list[ProjectSlot] = []

        def fail_constructor() -> None:
            try:
                registry.peek_project(failed_root)
            except BaseException as exc:  # pragma: no cover - reported below
                failures.append(exc)

        def admit_after_failure() -> None:
            try:
                succeeding_slots.append(registry.peek_project(succeeding_root))
            except BaseException as exc:  # pragma: no cover - reported below
                failures.append(exc)

        failing = threading.Thread(target=fail_constructor, name="failing-admission")
        succeeding = threading.Thread(
            target=admit_after_failure,
            name="admission-after-failure",
        )
        try:
            with registry._root_store_admission(failed_root):
                failing.start()
                _wait_for_project_admission(registry, failed_root)
                succeeding.start()
                assert not _finished(succeeding, _BLOCKED_SECONDS), (
                    "a second root bypassed the failed constructor's reserved seat"
                )
            assert _finished(failing, _RESUMED_SECONDS)
            assert _finished(succeeding, _RESUMED_SECONDS)
        finally:
            _join_started(failing)
            _join_started(succeeding)
            registry.close_all()

        assert len(failures) == 1
        # Naming both errnos rather than the OSError base keeps the claim that
        # the constructor died on the filesystem refusing a regular file as a
        # root, not on our own RuntimeError from the shutdown path. Which of
        # the two arrives is the platform's choice: Windows reports EEXIST for
        # the directory it cannot create, POSIX reports ENOTDIR for the file it
        # cannot descend into.
        assert isinstance(failures[0], FileExistsError | NotADirectoryError)
        assert [slot.store.root_dir for slot in succeeding_slots] == [succeeding_root]
        with registry._lock:
            assert registry._project_admissions == set()


class TestMaintenanceStoreLease:
    """Registry-owned maintenance never shares or escapes a live store owner."""

    def test_maintenance_rejects_a_live_slot_then_accounts_its_replacement(
        self,
        tmp_path: Path,
    ) -> None:
        """A busy warm slot remains untouched; an idle one is guarded and replaced."""
        registry = ServiceRegistry()
        root = _project_root(tmp_path, "maintained")
        warm_slot = registry.peek_project(root)
        maintained: VaultStore | None = None
        try:
            with (
                registry.lease(root),
                pytest.raises(ProjectBusyError) as excinfo,
                registry.lease_maintenance_store(root),
            ):
                pass
            assert excinfo.value.root == root
            assert registry._projects[root] is warm_slot
            assert warm_slot.store._client is not None

            with registry.lease_maintenance_store(root) as store:
                maintained = store
                assert root not in registry._projects
                assert warm_slot.store._client is None
                with registry._lock:
                    assert store in registry._transient_stores
                assert store._client is not None
            assert maintained._client is None
        finally:
            registry.close_all()

    def test_maintenance_waits_for_a_same_root_cold_store_lease(
        self,
        tmp_path: Path,
    ) -> None:
        """The cleanup lease cannot open its store until the cold reader closes."""
        registry = ServiceRegistry()
        root = _project_root(tmp_path, "maintenance-after-cold")
        maintained: list[VaultStore] = []
        errors: list[BaseException] = []

        def maintain() -> None:
            try:
                with registry.lease_maintenance_store(root) as store:
                    maintained.append(store)
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        thread = threading.Thread(target=maintain, name="maintenance-after-cold")
        try:
            with registry.lease_store(root) as cold_store:
                thread.start()
                assert not _finished(thread, _BLOCKED_SECONDS), (
                    "maintenance opened a same-root store beside a cold lease"
                )
                assert cold_store._client is not None
            assert _finished(thread, _RESUMED_SECONDS), (
                "maintenance did not resume after the cold lease closed"
            )
        finally:
            _join_started(thread)
            registry.close_all()

        assert errors == []
        assert len(maintained) == 1
        assert maintained[0]._client is None


class TestEvictionHoldsAdmissionUntilTheStoreCloses:
    """A root's guard outlives the store it admitted, eviction included."""

    @pytest.mark.parametrize("trigger", _EVICTION_TRIGGERS)
    def test_an_arrival_waits_for_an_evicted_store_to_finish_closing(
        self,
        tmp_path: Path,
        trigger: Callable[[ServiceRegistry, Path, Path], None],
    ) -> None:
        """Every eviction path keeps the root shut to openers until close returns.

        A store keeps its exclusive storage lock until ``close()`` completes,
        so the interval between the slot leaving ``_projects`` and that return
        is the one an arrival must not be admitted into: it opens a second
        store and is refused by this daemon's own handle, blaming a process
        that was never involved.
        """
        registry = ServiceRegistry()
        victim = _project_root(tmp_path, "victim")
        spare = _project_root(tmp_path, "spare")
        registry.peek_project(victim)
        rendezvous = _TeardownRendezvous(victim)
        registry._on_close_project = rendezvous

        evict_errors: list[BaseException] = []
        arrival_errors: list[BaseException] = []
        arrived: list[ProjectSlot] = []

        def evict() -> None:
            try:
                trigger(registry, victim, spare)
            except BaseException as exc:  # pragma: no cover - reported below
                evict_errors.append(exc)

        def arrive() -> None:
            try:
                arrived.append(registry.peek_project(victim))
            except BaseException as exc:  # pragma: no cover - reported below
                arrival_errors.append(exc)

        evictor = threading.Thread(target=evict, name="evictor")
        arrival = threading.Thread(target=arrive, name="arrival")
        try:
            evictor.start()
            assert rendezvous.entered.wait(timeout=_RESUMED_SECONDS), (
                "the eviction never reached its teardown"
            )
            assert victim not in registry._projects, (
                "the teardown rendezvous ran before the slot was removed"
            )
            arrival.start()
            assert not _finished(arrival, _BLOCKED_SECONDS), (
                "an arrival was admitted while the evicted store was still closing"
            )
            rendezvous.release.set()
            assert _finished(arrival, _RESUMED_SECONDS), (
                "the arrival never resumed after the evicted store closed"
            )
        finally:
            rendezvous.release.set()
            registry._on_close_project = None
            _join_started(evictor)
            _join_started(arrival)
            registry.close_all()

        assert evict_errors == []
        assert arrival_errors == []
        assert [slot.store.root_dir for slot in arrived] == [victim]

    @pytest.mark.parametrize("trigger", _EVICTION_TRIGGERS)
    def test_eviction_keeps_the_evicted_root_s_guard_object(
        self,
        tmp_path: Path,
        trigger: Callable[[ServiceRegistry, Path, Path], None],
    ) -> None:
        """The next opener of an evicted root contends for the same lock object.

        Presence is not the property that matters: two threads serialize only
        when they resolve to the *same* object, so an entry dropped on
        eviction and re-minted by the next arrival serializes nothing at all -
        which is why no eviction path removes one.
        """
        registry = ServiceRegistry()
        victim = _project_root(tmp_path, "victim")
        spare = _project_root(tmp_path, "spare")
        registry.peek_project(victim)
        guard = registry._root_locks[victim]
        try:
            trigger(registry, victim, spare)
            assert victim not in registry._projects
            assert registry._root_locks.get(victim) is guard, (
                "eviction replaced or removed the evicted root's store guard"
            )
            registry.peek_project(victim)
            assert registry._root_locks[victim] is guard, (
                "reopening the root minted a guard its evictor never held"
            )
        finally:
            registry.close_all()

        # Shutdown is the one place entries are dropped, and it drops all of
        # them: prepare_startup() reads a leftover as an incomplete shutdown.
        assert registry._root_locks == {}

    def test_evicting_one_root_never_blocks_an_arrival_on_another(
        self,
        tmp_path: Path,
    ) -> None:
        """A paused teardown leaves every other root open for business.

        The guard held across a close is per root. A store-wide one - a single
        mutex shared by every root - would queue this unrelated arrival behind
        a teardown it has nothing to do with, and the arrival never completes.
        """
        registry = ServiceRegistry()
        victim = _project_root(tmp_path, "victim")
        other = _project_root(tmp_path, "other")
        registry.peek_project(victim)
        rendezvous = _TeardownRendezvous(victim)
        registry._on_close_project = rendezvous

        evict_errors: list[BaseException] = []
        arrival_errors: list[BaseException] = []
        arrived: list[ProjectSlot] = []

        def evict() -> None:
            try:
                assert registry.try_evict(victim) == (True, "forced")
            except BaseException as exc:  # pragma: no cover - reported below
                evict_errors.append(exc)

        def arrive() -> None:
            try:
                arrived.append(registry.peek_project(other))
            except BaseException as exc:  # pragma: no cover - reported below
                arrival_errors.append(exc)

        evictor = threading.Thread(target=evict, name="evictor")
        arrival = threading.Thread(target=arrive, name="unrelated-arrival")
        try:
            evictor.start()
            assert rendezvous.entered.wait(timeout=_RESUMED_SECONDS), (
                "the eviction never reached its teardown"
            )
            arrival.start()
            assert _finished(arrival, _RESUMED_SECONDS), (
                "an unrelated root's arrival waited on another root's teardown"
            )
        finally:
            rendezvous.release.set()
            registry._on_close_project = None
            _join_started(evictor)
            _join_started(arrival)
            registry.close_all()

        assert evict_errors == []
        assert arrival_errors == []
        assert [slot.store.root_dir for slot in arrived] == [other]


class TestLockRefusalNamesOnlyWhatItEstablished:
    """The refusal reports the holder it can verify, and no holder otherwise."""

    def test_refusal_names_this_process_when_this_process_holds_it(
        self,
        tmp_path: Path,
    ) -> None:
        """An in-process double open says so, and releases cleanly afterwards."""
        root = _project_root(tmp_path, "double-open")
        first = VaultStore(root)
        try:
            with pytest.raises(VaultStoreLockedError) as excinfo:
                VaultStore(root)
        finally:
            first.close()

        message = str(excinfo.value)
        assert excinfo.value.held_in_process is True
        assert "already open in this process" in message
        # The exact wording that made this defect expensive to diagnose. A
        # looser matcher here passes on the message it was written to reject.
        assert "another process" not in message

        # A refused open registers nothing, and a released one unregisters, so
        # the root reopens rather than staying permanently "held".
        reopened = VaultStore(root)
        reopened.close()

    def test_refusal_names_no_holder_when_none_was_established(self) -> None:
        """With no holder in this process, the message asserts no holder at all."""
        exc = VaultStoreLockedError("/storage/qdrant")

        message = str(exc)
        assert exc.held_in_process is False
        assert "holder is unidentified" in message
        assert "another process" not in message
