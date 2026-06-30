---
tags:
  - '#research'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
related:
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
  - '[[2026-06-12-qdrant-server-provisioning-adr]]'
  - '[[2026-06-12-service-concurrency-adr]]'
  - '[[2026-06-13-server-first-default-adr]]'
---

# `storage-lifecycle` research: `service storage lifecycle management`

Research grounding two linked GitHub issues against the live code, the qdrant-client
1.18.0 API, and the binding prior decisions:

- **#192** - incremental/partial reindex does not evict deleted files; search returns
  stale results until a full rebuild.
- **#193** - no CLI/service surface exists to survey, prune, migrate, or delete the
  per-project / per-worktree RAG indexes, which grow unbounded.

The two are the same storage-lifecycle concern at two granularities: #192 is per-file
eviction correctness during incremental indexing; #193 is the operator-facing lifecycle
surface for whole per-root namespaces (survey + prune + migrate + delete), including
namespaces orphaned when a worktree is removed or a source root vanishes. The surface
manipulates and destroys stored data, so data safety and adversarial robustness are
first-class deliverables, not afterthoughts.

## Findings

### F1 - Storage is per-resolved-root, namespaced; "per-worktree" is just per-root

In server mode (the default since 0.2.21) one shared Qdrant server hosts every root's
data under one managed storage tree (default `~/.vaultspec-rag/qdrant-server/storage`,
snapshots under `~/.vaultspec-rag/qdrant-server/snapshots`). Each root's collections are
namespaced by `root_collection_prefix()` in `src/vaultspec_rag/store.py`: a prefix of
the form `r{12-hex}_` where the hex is a `blake2b(digest_size=6)` of the
case-normalised, `resolve()`-d root path. Collections are `{prefix}vault_docs` and
`{prefix}codebase_docs`. Local mode uses the bare names with an empty prefix and stores
on disk per project at `{root}/.vault/data/search-data/qdrant/`, guarded by an
`exclusive.lock` file (`VaultStoreLockedError` if held).

A worktree receives no special treatment: each worktree is a distinct resolved root path
and therefore gets its own `r{hash}_` prefix automatically. "Per-worktree" survey and
prune are identical to per-root. There is no shared-collection-across-worktrees
mechanism to reason about.

### F2 - The namespacing hash is one-way: orphan detection needs a persisted manifest

Because the prefix is a hash of the resolved path, a collection name cannot be reversed
to its source root. The in-memory `ServiceRegistry._projects` dict holds only the
*currently-leased* roots (LRU-capped, idle-TTL evicted) - not a durable record of every
root ever indexed. Consequently the service today has no way to map a stored
`r{hash}_codebase_docs` collection back to a filesystem path, and therefore no safe way
to classify a namespace as "live" (source path still exists) versus "orphaned" (source
gone / worktree removed). **This is the central new design problem for #193**: a safe
survey/prune almost certainly requires introducing a persisted prefix->root manifest,
written at index time, that the storage surface consults. Any collection whose prefix is
not reverse-mappable is an "unknown" that must be handled conservatively (never
blind-deleted) - an explicit data-safety boundary.

### F3 - qdrant-client 1.18.0 exposes no storage-size API; footprint comes from the filesystem

Confirmed pin: `qdrant-client>=1.16.0` floor in `pyproject.toml`, resolved to **1.18.0**
in `uv.lock`. Capability summary across both backends:

- List collections: `get_collections()` returns names only (both modes); per-collection
  count needs a follow-up `count(...).count` (exact) or `get_collection(...).points_count`
  (approximate in server mode, exact in local). This is an N+1 per collection.
- `CollectionInfo` carries `status`, `optimizer_status`, counts, `segments_count`,
  `config`, and `payload_schema` - but **no byte/size field in either mode**. Footprint
  must be derived from the filesystem: local = sum the files under
  `{path}/collection/{name}/` (essentially `storage.sqlite`); server = requires
  filesystem access to the server's storage dir, which an HTTP client does not have. The
  only client-visible byte figure is `SnapshotDescription.size`, and snapshots raise
  `NotImplementedError` in local mode.
- Deletion: `delete_collection(name)` - local does `shutil.rmtree` (disk freed
  synchronously); server removes the collection but disk reclaim is eventual, not
  guaranteed immediate (upstream qdrant#4204). `delete(points_selector=...)` by filter or
  id with `wait=True` (the client default) makes points immediately invisible to
  search/scroll, but **does not reclaim disk**: local sqlite never shrinks without
  `VACUUM` (the client never issues it); server reclaims only when the vacuum optimizer
  runs (threshold-driven). To reliably reclaim local disk, drop+recreate rather than
  delete points.

Design consequence: a `survey` that reports footprint must compute it from the
filesystem and must run where it can see the storage dir - i.e. **in the service/daemon
that owns the server's storage tree**, not in a remote CLI. "Reclaimed space" reporting
must distinguish logical eviction (points invisible) from physical reclamation (disk
freed after vacuum / drop+recreate), or it will lie to operators.

### F4 - #192: the eviction logic is correct and local-tested; the gap is server-mode coverage

The full delete path is wired correctly end to end. The watcher
(`src/vaultspec_rag/watcher.py`) admits `Change.deleted` events (its `watch_filter` and
`_is_vault_change` / `_is_code_change` are path/suffix based, so a now-missing path still
classifies), batches them into pending sets, and forwards them to
`incremental_index(changed_paths=...)`. The scoped reconcile computes the delete set
(`_process_changed_path` adds a vanished `rel` to `delete_files` when `rel in prev_meta`;
the vault twin builds `delete_ids`) and calls `store.delete_code_chunks(...)` /
`store.delete_documents(...)`. Path normalisation matches byte-for-byte between index
time (`_chunk_worker` writes `path` as `relative_to(root).replace("\\","/")`) and delete
time (the identical transform), so a Windows separator mismatch is not the cause.
`wait=True` is the client default, so a naive "delete not flushed" theory does not hold
at the client surface.

What is missing is **test coverage of the eviction path in server mode**. Every existing
deletion test (`test_targeted_reindex_integration.py`, `test_store_integration.py`)
forces local mode via `reset_config()` clearing `QDRANT_URL`, so
`store._server_mode is False`. The one server-mode test only indexes and searches; it
never deletes and re-asserts absence. So the exact failing flow - scoped reindex
eviction under the managed server - has zero regression protection, which is the
structural reason #192 shipped.

Ranked hypotheses for the observed server-mode leak (to confirm with a real-backend
test, not to assume):

- **H1 (most likely):** the bug reproduces only under server mode and is unprotected by
  tests; a server-only semantic difference in the delete path is the carrier. Highest
  value action: add a real server-mode regression test that indexes two files, deletes
  one, runs the scoped `incremental_index(changed_paths={deleted})`, and asserts both
  store-level eviction *and* that a real hybrid search no longer surfaces the file (the
  search assertion is what the issue actually observes).
- **H2 (server-only):** code-chunk deletion depends on `get_code_ids_by_paths` returning
  the complete id set via a paged `MatchAny(path)` scroll (server page limit 1000); the
  paging loop looks correct but is the concrete server-vs-local code difference worth
  proving/disproving.
- **H4 (vault-specific):** `delete_documents` deletes by `FilterSelector(doc_id MatchAny)`
  rather than point id - correct in both modes locally, but the only filter-based delete;
  if the leak is vault-only this asymmetry is where to look.
- **H5 (watcher batching, low):** the cooldown carry-forward of a delete; no code drops a
  missing path, but it lacks an explicit test assertion.
- **H3 (downgraded):** `wait=` not passed - the client defaults to `True`, so this is
  latent fragility (an explicit `wait=True` would be defensive/self-documenting) rather
  than a probable root cause.

If the server-mode delete tests pass, the defect localises upstream (watcher batching) or
to a stale `VaultSearcher` graph/result cache rather than the store/indexer layer.

### F5 - Slot eviction is not data deletion; releasing the slot must precede deleting data

The existing `ServiceRegistry` eviction (idle TTL + LRU cap, skip-busy refcount, lazy,
no background thread) and the `evict_project` MCP/route only release in-memory handles -
the on-disk / server-mode data survives. Confirmed by the provisioning ADR's own
consequence: cleaning a project's data dir no longer removes its server-mode
collections. There is therefore **no existing verb that deletes a root's server-mode
collections** - that is the genuinely new work (GAP-1). A real `delete <root>` must (a)
release the in-memory slot via the existing evict path, (b) verify no live store / held
`exclusive.lock`, then (c) drop collections / delete on-disk data. If the slot is busy it
must return `busy` and not block, never deleting data out from under a live `VaultStore`
(the failure class the refcount discipline exists to prevent).

### F6 - Binding constraints from prior decisions and rules

The surface inherits hard constraints (each cited to its source decision):

- **Backend-aware locking** (rule `storage-locks-are-backend-aware`,
  service-concurrency ADR D2): survey/prune/delete route through `_point_lock(collection)`
  in local mode and take no client-side lock in server mode; never add a store-wide
  mutex. Lock ordering is part of the contract - lifecycle lock before any collection
  lock; collection drop is lifecycle-lock territory, point delete is collection-lock
  territory; collection locks stay reentrant.
- **GPU lock holds forward passes only** (rule `gpu-lock-wraps-forward-passes-only`):
  storage I/O never runs inside `gpu_lock`. If `migrate` re-embeds, only the forward pass
  is inside the lock.
- **Single GPU consumer / CPU-only index workers** (rules `gpu-consumer-single-thread`,
  `index-workers-stay-cpu-only`): a migrate that rebuilds must reuse the single-consumer
  pipeline, keep worker torch imports lazy, and time-bound/liveness-guard any shutdown
  wait so it cannot wedge the writer lock.
- **Service domain owns operability** (rule `service-domain-owns-operability`): implement
  survey/prune/migrate/delete as service-domain functions first (in the `api.py` / service
  layer, alongside the established `get_readiness` precedent), with the CLI `storage`
  group and any MCP tool as thin adapters over one shared JSON contract. Do not compute
  prune candidates or footprint independently in the CLI.
- **Operator views are bounded** (rule `operator-views-are-bounded`): `survey` defaults to
  a bounded, filterable result biased to actionable state (`--orphaned`, `--root`,
  `--stale`, `--since`), never an unbounded inventory.
- **Dry-run discipline** (rule `vaultspec-dry-run-discipline`): every destructive verb
  takes `--dry-run` as the canonical preview listing exactly what would be removed,
  `--yes`/`-y` to apply, `--json` (with the json-requires-yes guard), and reports through
  the shared sync vocabulary (`removed`/`unchanged`/`skipped`-with-reason/`failed`). An
  empty preview on a side-effecting verb is a finding, not a green light.
- **Pinned-binary integrity** (rule `pinned-binaries-verify-before-execute`): a prune that
  touches the managed `bin/qdrant/{version}/` tree must never leave a partial or
  unverifiable binary the resolver would then run; binary tree, storage tree, and
  snapshots tree are distinct sub-concerns.
- **Daemon owns the supervised server** (provisioning ADR): destructive ops on shared
  server-mode collections must go through the running server's collection API while the
  daemon is alive; deleting storage files under a live server corrupts the engine. An
  offline on-disk storage wipe is safe only when the server is confirmed stopped.
- **No background sweeper** (eviction ADR D10, concurrency ADR): reclamation is
  operator-invoked or lazy/traffic-driven; new tuning ships as `VAULTSPEC_RAG_*` env with
  CLI translation, default-on-disable-with-0.
- **Real-backend tests only** (every ADR; project mandate): drive real service + real
  Qdrant (both backends) + real GPU via subprocess fixtures; no mocks/fakes/skips;
  Windows is the primary platform; GPU CI does not exist (run locally before merge).

### F7 - Existing conventions the new surface must mirror

- CLI Typer groups are declared in `src/vaultspec_rag/cli/_app.py` and nested with
  `add_typer`; a new `storage` group nests under `server` (the `server qdrant` / `server projects` precedent), with a `@callback(invoke_without_command=True)` help shim, and is
  imported in `cli/__init__.py` before any command decorator runs.
- Destructive-verb exemplars are `server qdrant clean`, `install uninstall`, and the
  index `clean` (a required positional scope `vault|code|all` "so nothing is deleted by
  accident"). The blast-radius preview is the computed target list; preview-without-confirm
  exits non-zero; destructive OSError exits 1 with remediation, never a traceback.
- The JSON envelope is owned by `_emit_json` in `cli/_render.py`
  (`{"ok","command","data"|("error","message")}`); the not-running exit code is 3
  everywhere.
- Service routes live in `server/_routes.py` as
  `async def name(request) -> JSONResponse`, registered in the `ROUTES` table and splatted
  in `server/_main.py`; gated routes call `require_token` first, resolve roots via
  `_resolve_root`, run blocking work via `_run_in_thread`, and reach the store through
  `with _m._registry.lease(root) as slot: slot.store...` catching `RegistryFullError` /
  `VaultStoreLockedError` via the `_utils` structured-error helpers. `drop_table` /
  `drop_code_table` already exist on the store, lifecycle+point-lock guarded.
- The only CLI->service HTTP adapter is `cli/_http_search.py` (`_do_http_call`,
  `_try_http_admin`, `_route_admin_tool`); connection-refused returns `None`
  (not-running -> exit 3), a live-but-broken service returns a structured error dict. New
  commands add `_try_http_storage_*` helpers / a `_route_admin_tool` branch and reuse this
  discipline rather than hand-rolling HTTP.

### F8 - Adversarial / data-safety surface (must be a dedicated implementation wave)

The verbs delete user data; the threat model must be designed in, not bolted on:

- **Out-of-scope destruction:** a `delete <root>` must operate only on the resolved
  root's namespaced collections (server) or its own `.vault/data/search-data/qdrant/`
  tree (local). It must never accept or follow a path outside the managed storage tree,
  never `rmtree` a path it did not itself namespace, and must reject path traversal
  (`..`), symlink escapes, and roots resolving outside an allowed base.
- **Unknown-namespace conservatism:** collections whose prefix cannot be reverse-mapped
  to a known root (F2) are reported, never auto-pruned, unless an explicit, separately
  gated "force unknown" path is invoked with full preview.
- **Live-data races:** honour the refcount/`exclusive.lock`/`busy` discipline (F5); never
  delete under a live store or a running server's storage files (F6).
- **Confirmation integrity:** `--json` requires `--yes`; dry-run is the default-safe
  posture; the preview must enumerate the exact collections/paths/points and the
  distinction between logical eviction and physical reclamation (F3).
- **Auth boundary:** the destructive routes are loopback + token gated like every other
  mutating route; control-plane verbs (prune/delete/migrate) should default to CLI only,
  with MCP limited to the read-only survey unless the service-domain owner decides
  otherwise.

## Open questions for the ADR

- Where does the persisted prefix->root manifest live, what writes it (index path?), and
  how is it reconciled when a root is renamed/moved (F2)?
- Is footprint reporting in-scope for v1, given there is no size API and it requires
  daemon-side filesystem access (F3)? If yes, server-side only.
- Does `migrate` mean backend conversion (local\<->server), version/schema migration of
  collections, or both - and does it re-embed (GPU pipeline reuse) or copy vectors (F6)?
- Verb taxonomy and nesting: `vaultspec-rag storage ...` vs `server storage ...`; which
  verbs are control-plane (CLI-only) vs observable (MCP survey).
- Scope of #192's fix: ship the server-mode regression test + any minimal durability fix
  with this feature, or as an independent precursor PR.

## Next step

Define the ADR: `vaultspec-core vault add adr --feature storage-lifecycle --related 2026-06-18-storage-lifecycle-research`.
