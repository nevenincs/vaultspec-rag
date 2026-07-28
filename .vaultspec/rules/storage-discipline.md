---
name: storage-discipline
---

# Storage discipline

## Rule

- Local mode: one reentrant lock per collection, plus one lifecycle lock for
  open, close, and collection create or drop.
- Server mode: no point-operation locks.
- Never reintroduce a store-wide mutex across collections.
- Acquire the lifecycle lock before any collection lock, never the reverse.
- Keep maintenance read-and-drop only. Never reach a stop, terminate or reclaim
  helper from it. Never import the CLI from a maintenance module.
- Require classification AND a persisted continuous grace window before any
  automatic deletion.
- Archive data-bearing namespaces successfully before destroying them.
- Never auto-touch an unknown or unverifiable namespace.
- Reset the grace clock on any live or unverifiable observation, and persist it
  across restarts.
- Point the Qdrant storage-dir environment variable at a temp path in any test
  that writes the identity sidecar or takes the machine lock.

## Why

- Collections are independent locally, and a remote server handles its own
  concurrency; client-side locking there only caps throughput.
- A store-wide lock sharing a mutex with unrelated scans collapses search
  latency by more than an order of magnitude.
- Maintenance sharing a process with lifecycle verbs reads as the cause whenever
  a daemon dies in the same window.
- A valid root can transiently not exist: an unplugged drive, an offline share,
  a rename, a worktree being recreated.
- Resetting the clock on any contrary observation means races can only extend
  protection, never shorten it.
- The identity sidecar and the machine lock derive from the storage-dir knob,
  not the status-dir knob. Isolating the wrong one writes into the operator's
  real managed directory and contends for the real lock.

## How

- Good: a per-collection lock accessor returning that collection's reentrant
  lock locally and a null context in server mode.
- Good: a fresh-interpreter test asserts no CLI module loads from the
  maintenance modules; a source scan asserts none names a terminate, reclaim or
  stop helper.
- Good: orphaned-only input, per-tier grace windows, riskless empty namespaces
  first under a per-cycle cap, points re-counted immediately before the drop.
- Good: raise on any snapshot failure so the delete is never reached for
  unarchived data.
- Good: a fixture points the storage dir at a temp path, resets config, runs,
  then releases the lock and restores the environment.
- Bad: a store method taking a global lock around a point operation.
- Bad: dropping a namespace on one survey saying its root was missing.
- Bad: destroying a point-bearing namespace after a failed archive.
- Bad: a restart-if-degraded branch in a maintenance cycle.
