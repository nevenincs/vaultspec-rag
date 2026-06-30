---
tags:
  - '#adr'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-06-30'
related:
  - "[[2026-06-18-storage-lifecycle-research]]"
  - "[[2026-06-13-server-first-default-adr]]"
  - "[[2026-06-12-qdrant-server-provisioning-adr]]"
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-04-12-store-eviction-log-rotation-adr]]"
---

# `storage-lifecycle` adr: `server-authoritative storage lifecycle surface` | (**status:** `accepted`)

## Problem Statement

The RAG index grows without bound. Indexing is additive across every update, and there
is no operator-facing way to see what storage exists, reclaim space, or remove the index
of a project/worktree that no longer exists. Two linked defects express the same gap at
two granularities:

- **#192** - incremental/partial reindex evicts added and modified files correctly but
  leaves deleted files in the store; search returns stale results until a full rebuild.
- **#193** - there is no surface to survey, prune, migrate, or delete the per-resolved-root
  (per-worktree) RAG namespaces, and namespaces orphaned by a removed worktree or vanished
  source root persist forever.

This ADR decides the architecture of a storage-lifecycle surface that closes both. The
surface manipulates and destroys user data, so its safety model is part of the decision,
not an implementation detail.

## Considerations

- **The server is the authority on stored data.** In the server-first default backend one
  managed Qdrant server owns one shared storage tree under the managed service directory;
  every root's data lives there as collections namespaced by a stable per-root prefix
  (`r{12-hex}_`, a one-way hash of the resolved root path). Only the daemon that supervises
  that server can enumerate every root's namespaces and read on-disk footprint. Storage
  lifecycle is therefore a service-domain responsibility executed in the daemon, with the
  CLI and MCP as thin adapters over one shared JSON contract.
- **Local mode is the degenerate, daemon-less case.** The `--local-only` opt-out remains
  first-class, but a local store is a single root's on-disk directory with no shared tree
  and no other namespaces to reconcile. Cross-root survey and orphan reconciliation are
  inherently a server-mode capability; in local mode the surface degrades to in-process
  operations on the one store. (Local-mode scope is called out for sign-off below.)
- **The namespacing hash is one-way.** A collection name cannot be reversed to its source
  path, and the in-memory project registry holds only currently-leased roots, not a durable
  record of every indexed root. Safe orphan detection requires a new persisted
  prefix->root manifest.
- **qdrant-client 1.18.0 has no size API.** Footprint must be computed from the filesystem,
  which only the daemon can see for the server tree. Making points invisible (delete by
  id/filter, `wait=True`) does not reclaim disk; reclamation needs drop+recreate or the
  vacuum optimizer. "Reclaimed" must mean physically reclaimed, not merely hidden.
- **#192's logic is already correct and locally tested; the gap is server-mode coverage.**
  The watcher forwards deletions, the scoped reconcile computes the delete set, and path
  normalisation matches between index and delete time. Every deletion test forces local
  mode, so the server-first delete path ships unprotected.
- **Slot eviction is not data deletion.** The existing registry eviction and
  `evict_project` only release in-memory handles; no verb removes a root's server-mode
  collections. That is the genuinely new work.

## Constraints

- **Backend-aware locking and lock ordering** must be honoured: per-collection reentrant
  locks plus a lifecycle lock in local mode, no client-side point locks in server mode,
  lifecycle-before-collection ordering; never a store-wide mutex. Collection drop is
  lifecycle-lock territory; point delete is collection-lock territory.
- **GPU lock wraps forward passes only**; all storage I/O runs outside it. A migrate that
  re-embeds reuses the single dedicated GPU consumer and keeps index workers CPU-only.
- **No background sweeper.** Reclamation is operator-invoked or lazy; new tuning ships as
  `VAULTSPEC_RAG_*` env with CLI translation.
- **Pinned-binary integrity and daemon ownership.** Destructive ops on shared server-mode
  collections go through the running server's collection API while the daemon is alive;
  deleting storage files under a live server corrupts the engine. A prune that touches the
  managed binary tree must never leave an unverifiable binary.
- **Real-backend tests only** (no mocks/fakes/skips), Windows primary, GPU run locally.
- **Frontier risk - migrate tooling.** The ultrafast bulk-data-movement path for `migrate`
  depends on a C-backed Python tooling choice that does not yet exist in the project and
  must be settled by a bounded research spike before the migrate wave; until then migrate
  is unimplementable to the required performance bar.
- **Parent-feature stability.** Builds on the server-first default backend and the managed
  Qdrant server provisioning, both shipped (0.2.21) and stable, and on the service
  concurrency lock model. No unstable parent.

## Implementation

A new service-domain storage module owns survey/prune/delete/migrate; the daemon exposes
them as gated HTTP endpoints (`GET /storage`, `POST /storage/prune`, `POST /storage/delete`,
`POST /storage/migrate`) and the CLI adds a `server storage` group (`survey`, `prune`,
`delete`, `migrate`) that adapts over the existing CLI->service HTTP client. MCP exposes
the read-only survey only; control-plane verbs are CLI-only.

**Manifest (D2).** The daemon maintains a persisted prefix->root manifest (resolved root
path, backend, last-indexed time), written/updated whenever a root is indexed. Survey
reverse-maps each `r{hash}_` collection through it. A collection whose prefix is absent
from the manifest is reported `unknown` and never auto-pruned.

**Survey (D3, D8).** Bounded, filterable, biased to actionable state
(`--orphaned`, `--unknown`, `--root`, `--since`). Reports per-namespace point counts and
live/orphaned/unknown status in both backends now; daemon-side byte footprint from the
server storage tree where available. Output distinguishes logical occupancy from
physically reclaimable space.

**Prune / delete (D5, D6).** Both are destructive and follow the project discipline:
`--dry-run` is the canonical preview rendering the exact target namespaces; `--yes`
applies; `--json` requires `--yes`; not-running exits 3; results report through the sync
vocabulary. `prune` targets orphaned namespaces; `delete` takes an explicit required
target so nothing is removed by accident. Removing a root's data first releases its
in-memory slot through the existing evict path (skip-busy refcount - a busy root returns
`busy`, never blocks), confirms no live store or held lock, then drops the namespaced
collections via the live server's API (server) or removes the local store tree only when
the store is confirmed closed (local).

**#192 eviction (D7).** A real server-mode regression test indexes two files, deletes one,
runs the scoped incremental index, and asserts both store-level eviction and that hybrid
search no longer surfaces the file. Any minimal durability fix the test demands lands with
it; eviction remains an incremental-index concern reusing the existing delete primitives.

**Migrate (D9) - last wave.** `migrate` relocates/converts a root's index between backends
(local\<->server) and is implemented last, after a bounded research spike selects the most
capable C-backed Python tooling for ultrafast bulk vector/payload movement. If re-embedding
is required it reuses the single GPU consumer pipeline; all storage I/O stays outside the
GPU lock.

**Data safety (D10) - dedicated wave.** A threat-model wave hardens every destructive path:
operate only on the resolved root's own namespaces / the managed storage tree; reject path
traversal, symlink escape, and roots resolving outside the allowed base; never delete a
path the surface did not itself namespace; treat unknown namespaces conservatively; honour
the live-data refcount/lock discipline; keep the loopback+token auth boundary.

## Rationale

Centring authority on the daemon follows the established service-domain-owns-operability
discipline and the physical reality that only the daemon can see the shared storage tree
and its footprint - the research showed a remote client cannot. The persisted manifest is
the minimum mechanism that makes orphan detection safe given a one-way namespacing hash;
without it, pruning server collections is guessing. Sequencing #192 first de-risks the
whole feature: it closes a shipped correctness bug and produces the real server-mode test
scaffolding the destructive verbs reuse. Making migrate last isolates its frontier tooling
risk from the survey/prune/delete value that addresses the immediate unbounded-growth pain.
Treating data safety as its own wave reflects that these verbs destroy user data and a
single out-of-scope deletion is unacceptable.

## Consequences

- Operators gain visibility into stored namespaces and a safe, preview-first way to reclaim
  space and remove dead worktrees' indexes without a full rebuild; #192's stale-result class
  is closed and regression-protected in server mode.
- A new persisted manifest becomes part of the service's durable state and must be kept
  consistent with reality (rename/move of a root needs reconciliation) - a maintenance
  surface that did not exist before.
- "Unknown" namespaces (pre-manifest data, or data from another tool) will exist after
  rollout and are deliberately not auto-cleaned; operators must reconcile them explicitly,
  which is safe but not fully automatic.
- Footprint reporting is server-authoritative and filesystem-derived; in local mode it is
  limited to the single store and cross-root features are unavailable - a deliberate
  asymmetry that needs clear documentation.
- The migrate wave carries unresolved tooling risk until its research spike lands; the
  feature delivers value before migrate exists.

## Codification candidates

- **Rule slug:** `storage-authority-is-the-server`.
  **Rule:** Storage-lifecycle logic (survey, prune, delete, migrate, footprint) is
  service-domain behaviour executed in the supervising daemon; CLI and MCP only adapt to it,
  and destructive operations on server-mode collections go through the live server's API -
  never by deleting storage files under a running server.

- **Rule slug:** `namespace-deletion-needs-manifest-attribution`.
  **Rule:** Never delete or prune a namespaced collection whose prefix cannot be attributed
  to a known root through the persisted prefix->root manifest; unattributable namespaces are
  reported as unknown and require explicit, separately gated operator action.

## Decided sign-offs

- **Local-mode scope (decided):** local mode is supported as single-root, in-process
  survey/delete operating on the one local store; #192 eviction applies there too.
  Cross-root orphan reconciliation (prune) is a server-mode-only capability by design,
  because a daemon-less local install has no shared tree to reconcile. This asymmetry is
  documented, not a gap.
