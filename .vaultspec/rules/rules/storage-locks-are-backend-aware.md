---
name: storage-locks-are-backend-aware
---

# Storage locks are backend-aware

## Rule

Store-layer locking must distinguish local mode (one reentrant lock per
collection, plus a lifecycle lock for open/close and collection create/drop)
from server mode (no point-operation locks at all); never reintroduce a single
store-wide mutex across collections.

## Why

The `2026-06-12-service-concurrency-adr` and the saturation baseline in its
research showed one store-wide lock dragging 4-second vault searches to a
95-second p50 purely because they shared a mutex with code-collection scans -
the collections are independent inside the local engine, and a remote Qdrant
server handles its own concurrency, so client-side locking there only caps
throughput. Lock ordering is part of the contract: the lifecycle lock is always
acquired before any collection lock, and collection locks stay reentrant
because scan helpers re-enter them.

## How

- Good: `_point_lock(collection)` returning the collection's own RLock in local
  mode and a null context in server mode; `close()` taking the lifecycle lock
  then every collection lock in fixed order
  (`src/vaultspec_rag/store.py`).
- Bad: adding a new store method that takes one global client lock around a
  point operation, or acquiring the lifecycle lock while already holding a
  collection lock.
