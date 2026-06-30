---
tags:
  - '#research'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
related: []
---

# `qdrant-store-resilience` research: `Corrupt-collection resilience for the shared Qdrant store`

The machine-singleton service supervises one managed Qdrant server over a single
shared on-disk store. That store holds every project root's collections side by
side - one machine had ~45 roots, each contributing a `vault_docs` and a
`codebase_docs` collection. Qdrant cold-loads every collection during startup
before answering `/readyz`. If a single collection's segment files are corrupt,
the Rust process aborts during load and the server never becomes ready - so a
defect localized to one root's index takes down search for every root on the
machine. This research characterizes that failure mode from the supervision code
and the on-disk layout, and scopes a detect-quarantine-retry recovery so one bad
collection degrades to one stale root instead of a total brick.

## Findings

### 1. The failure mode: one corrupt collection bricks the shared store

The store is machine-global and multi-tenant: collections are namespaced per
root by a short blake2b hash of the resolved root path
(`store.root_collection_prefix`), so the live store directory holds many
`collections/r<hash>_vault_docs/` and `collections/r<hash>_codebase_docs/`
subdirectories under one Qdrant data dir (alongside `aliases/` and
`raft_state.json`). Because Qdrant loads all collections before serving, a
corrupt segment in any one of them aborts the whole process at startup. The
blast radius is therefore the entire machine's search surface, not the one
affected root - the asymmetry this feature targets.

### 2. The failure is already observable, not yet recoverable

The supervisor (`qdrant_runtime/_supervise.py`) captures the child's combined
stdout/stderr through a drained pipe specifically so a non-ready exit reports its
*cause* - a Rust panic, a bind error, a storage-lock error - rather than an
opaque timeout. On a failed `start()`, `wait_ready()` returns False and the code
raises a `RuntimeError` carrying `recent_output_tail()` (the captured panic) and
the log path. So the diagnostic signal already exists: when a corrupt collection
aborts load, Qdrant's output names the failing collection/segment, and that tail
is in hand at the failure point. What is missing is the *recovery*: the
supervisor reports the panic and gives up; nothing quarantines the offending
collection or retries.

### 3. The recovery primitive: quarantine, not delete

Each collection is a self-contained directory under `collections/<name>/`.
Moving that one directory aside (to a sibling `collections/.quarantine/<name>.<ts>/`)
removes the corrupt collection from the set Qdrant loads, so a restart succeeds
and every other root is served again. The quarantined root simply has no index
until its next search/index touch re-creates and re-populates it (the store
already creates collections on demand via `_ensure_collection`). Quarantine
(move) over delete preserves the corrupt files for forensics and makes the
operation reversible. This is a pure filesystem operation, independent of Qdrant
internals, and is the load-bearing recovery action.

### 4. Detection is the uncertain part; design defensively

Mapping a startup abort to *which* collection is corrupt depends on Qdrant's
error text, which is version-dependent and not a stable contract. The robust,
format-tolerant signal is: when the start fails, scan the captured tail for any
collection name that actually exists on disk - a known `r<hash>_..._docs`
directory under `collections/` - appearing alongside a failure marker (panic,
abort, error, segment, load). A name from the real on-disk set is a high-
confidence match regardless of the surrounding message format. When the tail
yields no on-disk collection name, the system must NOT guess and quarantine a
healthy collection (that would silently drop a good index); it surfaces the
captured panic and defers to an explicit operator action.

### 5. Bounding and safety

A retry loop must be bounded: quarantine at most a small number of collections
per recovery pass and cap total restart attempts, so a pathological store (many
corrupt collections, or a non-collection panic the parser misreads) degrades to
a clear failure rather than quarantining the whole store in a loop. Every
quarantine is logged loudly with the collection name and destination. The
recovery must respect the existing managed-storage isolation discipline so tests
never move a real collection: the storage dir is the `VAULTSPEC_RAG_QDRANT_STORAGE_DIR`
anchor, isolated to a temp path in tests.

### 6. Fix space for the ADR

Two surfaces, not exclusive. (a) Automatic, in the supervised start path: on a
readiness failure whose tail names an on-disk collection, quarantine it and retry
under a bound, so the common single-corrupt-collection case self-heals without an
operator. (b) An explicit operator escape hatch: a CLI verb under `server qdrant`
to list collections and quarantine a named one, plus surfacing the captured panic
when auto-detection cannot identify the culprit. The ADR must decide whether
auto-quarantine is on by default (resilience) or opt-in (caution against a false
positive dropping a good index), and the exact bound. The pure functions -
parse-tail-for-known-collection and quarantine-collection-dir - are testable
without a live corrupt store; the integration is the bounded retry around the
existing `start()`/`restart()`.
