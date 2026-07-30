"""One owner for same-root store construction, and an honest lock refusal.

A local-file store keeps an exclusive OS lock on its storage directory for as
long as it is open, and that lock is per open handle rather than per process.
Two stores opened on one root inside a single process therefore refuse each
other exactly as a foreign holder would - so the registry must admit only one
of them at a time, and a refusal must not name a holder it never established.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from .._store_locks import VaultStoreLockedError
from ..service import ServiceRegistry
from ..store_runtime import VaultStore

if TYPE_CHECKING:
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


def _project_root(tmp_path: Path, name: str) -> Path:
    """Return a resolved, existing workspace root the store can open."""
    root = (tmp_path / name).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


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
