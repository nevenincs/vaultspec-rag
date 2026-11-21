"""A reset takes its locks in order, waits holding nothing, and starves for no one.

Every case runs against a real local store under the test's temporary root,
with real threads holding the same reentrant locks a search or a write holds.
Nothing here loads a model or touches a GPU.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from .._source_types import PublicSourceType
from ..indexer._rebuild_lifecycle import reset_selected_sources
from ..indexer._run_ledger_models import SourceResetPhase
from .test_rebuild_lifecycle import (
    _park_reset,
    _points,
    _state,
    local_config,
    store,
)

if TYPE_CHECKING:
    from .._store_locks import ReentrantLock
    from ..store_runtime import VaultStore

pytestmark = [pytest.mark.unit]

__all__ = ["local_config", "store"]


def _free_in_another_thread(executor: ThreadPoolExecutor, lock: ReentrantLock) -> bool:
    """Whether *lock* can be taken at once by a thread that does not hold it."""

    def take() -> bool:
        taken = lock.acquire(timeout=0.0)
        if taken:
            lock.release()
        return taken

    return executor.submit(take).result(timeout=5.0)


@pytest.mark.parametrize("busy", ["lifecycle", "collection"])
def test_a_reset_waiting_on_a_busy_lock_holds_no_other_lock(
    store: VaultStore, busy: str
) -> None:
    """A parked reset keeps the lifecycle and collection locks free to others.

    The lifecycle lock is taken before a collection lock and never the other
    way round, and a reset that cannot take the next lock waits holding
    nothing, so whichever lock another holder keeps, the other stays takeable
    by anyone else throughout the wait.

    Mutation: waiting on the busy collection lock while still holding the
    lifecycle lock left the lifecycle lock taken for the whole wait and
    failed this test on the free-sample count for ``collection``-busy;
    restoring the release-then-wait order passed.
    """
    from ..indexer._run_policy import RunPolicy
    from ..job_control import CancelRequested, RunControlToken

    token = RunControlToken()
    policy = RunPolicy(no_progress_timeout_seconds=30.0, run_control=token)
    lifecycle = store._lifecycle_lock
    collection = store._lock_for(store.TABLE_NAME)
    held, other = (
        (lifecycle, collection) if busy == "lifecycle" else (collection, lifecycle)
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        held.acquire()
        try:
            resetting = _park_reset(
                executor,
                store,
                PublicSourceType.VAULT,
                run_control=policy,
                write_policy=policy.store_write_policy,
            )
            samples = 100
            free = 0
            for _ in range(samples):
                free += _free_in_another_thread(executor, other)
                time.sleep(0.005)
            token.request_cancel()
        finally:
            held.release()
        with pytest.raises(CancelRequested):
            resetting.result(timeout=10.0)

    assert free >= samples * 0.9, f"the {busy}-parked reset held the other lock"
    assert _state(store, PublicSourceType.VAULT) is None


def test_a_reset_completes_within_its_budget_beside_continuous_local_searches(
    store: VaultStore,
) -> None:
    """Steady search load on a collection cannot starve a reset of its lock.

    Local searches take the collection's non-fair reentrant lock for every
    query, and sixteen threads searching back to back keep it held at every
    instant a timed zero-timeout probe looks. The reset waits on that lock
    while holding nothing instead, so it gets the lock between queries and
    finishes inside its no-progress budget.

    Mutation: reverting the wait to a pause followed by a zero-timeout
    re-probe left every probe landing inside a search's hold, and the reset
    failed with its no-progress timeout on the ``reset_selected_sources``
    call; restoring the wait on the busy lock passed.
    """
    from qdrant_client import models

    from .. import store_schema
    from .._store_search import HybridSearchRequest
    from ..indexer._run_policy import RunPolicy
    from ..job_control import RunControlToken

    store.client.upsert(
        store.TABLE_NAME,
        points=[
            models.PointStruct(
                id=point_id,
                vector={store_schema.DENSE_VECTOR_NAME: [1.0, (point_id % 7) / 7.0]},
                payload={"content": f"content {point_id}", "doc_id": f"d{point_id}"},
            )
            for point_id in range(1, 2001)
        ],
        wait=True,
    )
    policy = RunPolicy(no_progress_timeout_seconds=5.0, run_control=RunControlToken())
    request = HybridSearchRequest(
        query_vector=[1.0, 0.0], query_text="content", limit=1
    )
    stop = threading.Event()
    searches = [0] * 16

    def search_continuously(index: int) -> None:
        while not stop.is_set():
            store.hybrid_search(request)
            searches[index] += 1

    with ThreadPoolExecutor(max_workers=len(searches)) as executor:
        workers = [
            executor.submit(search_continuously, index)
            for index in range(len(searches))
        ]
        try:
            while min(searches) == 0:
                time.sleep(0.01)
            before = sum(searches)
            (state,) = reset_selected_sources(
                store,
                PublicSourceType.VAULT,
                generation_id="under-load",
                run_control=policy,
                write_policy=policy.store_write_policy,
            )
            during = sum(searches) - before
        finally:
            stop.set()
        for worker in workers:
            worker.result(timeout=10.0)

    assert state.phase is SourceResetPhase.COMPLETE
    assert during > 0, "no search ran beside the reset"
    assert _points(store, store.TABLE_NAME) == 0
