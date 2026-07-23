---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S28'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Bound the daemon shutdown store teardown so a wedged consumer's writer lock cannot hold the daemon in an unbounded shutdown: acquire the store's collection locks under a finite deadline at shutdown and force-close the client past a lock still held past that deadline

## Scope

- `src/vaultspec_rag/store.py`
- `src/vaultspec_rag/_store_locks.py`
- `src/vaultspec_rag/service.py`

## Description

- Add a deadline-bounded collection-lock acquisition that acquires in the same
  fixed name order but abandons a lock it cannot take in time
  (`src/vaultspec_rag/_store_locks.py:31`).
- Give the store's ``close`` an opt-in shutdown force mode that bounds the
  collection-lock wait and closes the client anyway past a still-held lock,
  leaving normal close unbounded (`src/vaultspec_rag/store.py:349`).
- Have only the registry shutdown's force-close path pass the bound
  (`src/vaultspec_rag/service.py:841`).
- Cover the bound end to end: a collection lock held by another thread must not
  block a bounded close (`src/vaultspec_rag/tests/test_store.py`).

## Outcome

The daemon can no longer be held in an unbounded shutdown by a wedged consumer's
writer lock. This is the Cluster-B remediation, surfaced from the same
end-to-end lifecycle gate as the Cluster-A cleanup work.

The unbounded wait was in the store, not the consumer drain. The consumer drains
are finite - one bounds on the no-progress budget and raises when it expires,
the other on a fixed cleanup deadline. The store close was not: it took the
lifecycle lock and then every collection lock through a plain unbounded
acquisition, so if an index consumer held a collection lock during an in-flight
upsert, close blocked on it forever. The registry's graceful drain waits only on
search-lease reference counts, not on that writer lock, so its five-second
deadline elapsed and it went on to force-close the busy store - and the
"force" was not forceful, because the very next call blocked on the held lock.
The daemon never reached its shutdown-complete log and never exited.

The fix bounds that acquisition, and does so only at shutdown. The ordinary
close is unchanged: it still acquires every collection lock with no time bound,
so a legitimate slow point operation is always awaited rather than abandoned -
abandoning a lock aborts a holder's in-flight write, which would risk data loss
on a healthy store. The bounded-force mode is opt-in and reached only from the
registry's shutdown force-close, where the abort is correct because the daemon
is discarding state to complete a bounded shutdown. The lock order is preserved
exactly: lifecycle lock first, then collection locks in the same fixed name
order, with only the collection-lock waits abandoned past the deadline, never
reordered and never force-broken. And the client close still runs on the
force path, so a forced teardown does not leak the Qdrant or sqlite handle.

The safety line is sharp: shutdown bounds-and-forces; normal teardown never
abandons a lock. One deadline conveys the difference, and only the shutdown
caller supplies it.

## Notes

Diagnosed by inspection, because a live stack of the wedged daemon could not be
captured - the sandbox terminates the process before a dump lands. The chain was
traced statically from the failing acceptance test through the registry shutdown
to the unbounded store-close acquisition, and the bound was proven at the unit
level: a collection lock held by a second thread no longer blocks a bounded
close, which waits its deadline and then force-closes. Reverting the bound makes
that test fail, so it guards the property rather than merely exercising it.

The acceptance test is the running-phase rollback lifecycle test: post-fix the
daemon should roll back and exit within its thirty-second window and log the
shutdown-complete boundary. That real-daemon verification belongs to the harness
operator; the store-level behaviour is what this record confirms.

One open question is recorded honestly. The mid-index shutdown case fits this
root cause exactly - a wedged consumer holds the writer lock and store close
blocks on it. The idle running-phase rollback case was observed idle just before
its trigger, so whether its hang is this same store-close wait or a distinct
unbounded wait in the rollback orchestration was not confirmable without the
stuck frame. This fix bounds a genuine unbounded wait that is correct on its own
merits under the single-consumer shutdown rule; if the idle rollback proves to
hang elsewhere, that is a separate bound, and the acceptance run will show it.

The storage-locks-are-backend-aware rule needs a bounded-shutdown-close
carve-out to match this code: close acquires all collection locks in fixed order
for a normal teardown, and additionally may bound those waits and force-close
past a wedged holder at shutdown. That amendment is deferred deliberately - it
means editing the rule seed and re-syncing, which should not be tangled into
this fix while the tree carries provider-mirror churn. The rule owner will
ratify and apply the seed amendment separately; no rule file was edited here.

Follow-up completion (same shutdown force-close path): the first cut bounded only the collection-lock waits and still acquired the lifecycle lock through a plain unbounded acquisition, so a force-close could block forever on an in-flight open/create/drop that held the lifecycle lock, before the bounded collection-lock section was ever reached. The force path now runs under one shared deadline: the lifecycle-lock wait is bounded too and abandoned past the deadline (the client is force-closed without it), and the collection locks then get only the time that remains, so the whole force-close is bounded end to end. Order is still lifecycle-first-then-collections, and no store-wide mutex is introduced - each collection lock stays its own guard taken in name order. A second guard test covers it: the lifecycle lock held by another thread no longer blocks a bounded close, and reverting the bound to the unconditional lifecycle acquisition makes that test hang past its deadline and fail. `src/vaultspec_rag/store.py` (a new `_force_close` helper under `close`) and `src/vaultspec_rag/tests/test_store.py` carry the change.
