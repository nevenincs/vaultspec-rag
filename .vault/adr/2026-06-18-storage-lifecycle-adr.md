---
tags:
  - '#adr'
  - '#storage-lifecycle'
date: '2026-06-18'
modified: '2026-10-01'
body_hash: 'sha256:54d0c0ff30d65dc9aef2974359701893b952d192de02efcb7deb927755f3f2a7'
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
  lifecycle is therefore a service-domain responsibility. The accepted reconciliation
  keeps the read-only survey daemon-owned and runs destructive CLI verbs through shared
  storage-domain functions against the managed loopback server; MCP remains read-only.
- **Local mode is the degenerate, daemon-less case.** The `--local-only` opt-out remains
  first-class, but a local store is a single root's on-disk directory with no shared tree
  and no other namespaces to reconcile. Cross-root survey and orphan reconciliation are
  inherently a server-mode capability. The original single-store local maintenance
  proposal is retained in the historical sign-off below; the accepted reconciliation
  retires local-mode survey and requires server mode for the storage CLI surface.
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
- **GPU lock wraps forward passes only**; all storage I/O runs outside it. The accepted
  migrate is copy-only: it preserves vectors and payloads without re-embedding, so it
  neither consumes the GPU pipeline nor acquires the GPU lock.
- **No background sweeper.** Reclamation is operator-invoked or lazy; new tuning ships as
  `VAULTSPEC_RAG_*` env with CLI translation.
- **Pinned-binary integrity and daemon ownership.** Destructive ops on shared server-mode
  collections go through the running server's collection API while the daemon is alive;
  deleting storage files under a live server corrupts the engine. A prune that touches the
  managed binary tree must never leave an unverifiable binary.
- **Real-backend tests only** (no mocks/fakes/skips), Windows primary, GPU run locally.
- **Historical frontier risk - migrate tooling.** The original proposal required a
  bounded tooling research spike before migration. The accepted reconciliation delivers
  copy-only vector/payload movement; the previous conditional re-embedding requirement
  does not apply to that operation.
- **Parent-feature stability.** Builds on the server-first default backend and the managed
  Qdrant server provisioning, both shipped (0.2.21) and stable, and on the service
  concurrency lock model. No unstable parent.

## Implementation

The original accepted proposal put survey and destructive storage operations behind
daemon HTTP routes. That proposal is retained here as history; the later user-directed
reconciliation recorded in Git commit `d3be70d0` and the shared
`2026-06-18-storage-lifecycle-W02-P03-S13` execution record replaces that control plane
with the CLI-direct architecture.

Shared service-domain storage functions own survey/prune/delete/migrate. The read-only
`GET /storage/survey` route, service-first CLI survey, and read-only MCP tool are the
daemon-owned surface. Destructive `server storage delete`, `prune`, and `migrate` verbs
open their own client to the managed loopback Qdrant server and call those functions
in-process. There are no destructive daemon HTTP routes or corresponding CLI HTTP
adapters. The same recorded reconciliation retires local-mode survey and the proposed
GPU-consumer migration because migration copies existing vectors and payloads unchanged.

**Manifest (D2).** The daemon maintains a persisted prefix->root manifest (resolved root
path, backend, last-indexed time), written/updated whenever a root is indexed. Survey
reverse-maps each `r{hash}_` collection through it. A collection whose prefix is absent
from the manifest is reported `unknown` and never auto-pruned.

**Survey (D3, D8).** Bounded, filterable, biased to actionable state
(`--orphaned`, `--unknown`, `--root`, `--since`). Reports per-namespace point counts and
live/orphaned/unknown status in both backends now; daemon-side byte footprint from the
server storage tree where available. Output distinguishes logical occupancy from
physically reclaimable space. Cross-root maintenance and the CLI storage surface require
server mode; local-only survey is retired by the recorded reconciliation.

**Prune / delete (D5, D6).** Both are destructive and follow the project discipline:
`--dry-run` is the canonical preview rendering the exact target namespaces; `--yes`
applies; `--json` requires `--yes`; not-running exits 3; results report through the sync
vocabulary. `prune` targets orphaned namespaces; `delete` takes an explicit required
target so nothing is removed by accident. Removing a root's data first releases its
in-memory slot through the existing evict path (skip-busy refcount - a busy root returns
`busy`, never blocks), confirms no live store or held lock, then drops the namespaced
collections via the live server's API. The original local-only maintenance surface is
retired; this is not authorization to remove an open local store or storage files beneath
a running server.

**#192 eviction (D7).** A real server-mode regression test indexes two files, deletes one,
runs the scoped incremental index, and asserts both store-level eviction and that hybrid
search no longer surfaces the file. Any minimal durability fix the test demands lands with
it; eviction remains an incremental-index concern reusing the existing delete primitives.

**Migrate (D9).** `migrate` relocates/converts a root's existing index between backends
(local\<->server) through the CLI-direct storage-domain function. It copies vectors and
payloads unchanged, rather than re-embedding. The maintenance command requires server
mode, and all storage I/O stays outside the GPU lock.

**Data safety (D10) - dedicated wave.** A threat-model wave hardens every destructive path:
operate only on the resolved root's own namespaces / the managed storage tree; reject path
traversal, symlink escape, and roots resolving outside the allowed base; never delete a
path the surface did not itself namespace; treat unknown namespaces conservatively; honour
the live-data refcount/lock discipline; keep the loopback+token auth boundary on
the exposed daemon survey and the managed-loopback boundary for CLI-direct operations.

## Rationale

The original daemon control-plane proposal followed the service-domain operability
discipline. The subsequent user-directed reconciliation preserves the shared storage-domain
owner and daemon-authoritative read-only survey and footprint while explicitly choosing
CLI-direct destructive operations through the managed server's collection API. The persisted manifest is
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
- Footprint reporting remains server-authoritative and filesystem-derived. The CLI storage
  maintenance surface requires server mode; local-only survey is retired.
- Migration copies stored vectors and payloads without re-embedding, so the earlier
  conditional GPU-consumer requirement does not apply.

## Codification candidates

- **Rule slug:** `storage-authority-is-the-server`.
  **Rule:** Storage-lifecycle logic (survey, prune, delete, migrate, footprint) is
  service-domain behaviour. Read-only survey and footprint remain daemon-owned, destructive
  CLI operations use the shared storage-domain functions, and MCP remains read-only.
  Destructive operations on server-mode collections go through the live server's API -
  never by deleting storage files under a running server.

- **Rule slug:** `namespace-deletion-needs-manifest-attribution`.
  **Rule:** Never delete or prune a namespaced collection whose prefix cannot be attributed
  to a known root through the persisted prefix->root manifest; unattributable namespaces are
  reported as unknown and require explicit, separately gated operator action.

## Decided sign-offs

- **Original local-mode sign-off (historical):** the earlier proposal supported
  single-root, in-process survey/delete and server-only cross-root prune. The later
  user-directed reconciliation explicitly retired local-mode survey because storage
  maintenance requires server mode and a local store has no cross-root namespaces to
  reconcile. The incremental deleted-file eviction contract remains separate and applies
  to both backends. The prior sign-off is preserved as decision history, not current
  authorization for a local-only maintenance command.

## Considered options

Evidence gap: the retained document body has no separately labelled Considered options section.
