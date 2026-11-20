---
tags:
  - '#adr'
  - '#auto-update-opt-out'
date: '2026-11-20'
modified: '2026-11-20'
body_schema: 'body-v2'
body_hash: 'sha256:23e73a891d62d69cc3d0b4d8818139214fe9f241f7efdfe486562660f8a22720'
related:
  - "[[2026-09-08-adaptive-watcher-control-adr]]"
  - "[[2026-10-26-stale-search-hits-adr]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
  - '[[2026-09-08-adaptive-watcher-control-reference]]'
  - '[[2026-10-26-stale-search-hits-reference]]'
  - '[[2026-06-01-service-operability-adr]]'
---

# `auto-update-opt-out` adr: `persisted per-root automatic update opt-out` | (**status:** `accepted`)

## Problem Statement

An operator cannot keep automatic updates off for one root. `server updates stop` removes the watcher only from process memory (`src/vaultspec_rag/server/_watcher.py:1003`, `src/vaultspec_rag/server/_routes_registry.py:234`). The next search or reindex for that root calls `_ensure_watcher_soon` unconditionally and starts it again (`src/vaultspec_rag/server/_routes_search.py:306`, `src/vaultspec_rag/server/_routes_reindex.py:307`). Repository enrolment does the same (`src/vaultspec_rag/server/_routes_operator.py:261`). A service restart also forgets the stop. The only lasting control is the global `watch_enabled` switch (`src/vaultspec_rag/server/_watcher.py:656`), which turns updates off for every root. A decision is needed because the opt-out is persisted operator intent that every implicit enrolment path must honour.

## Considerations

- Implicit enrolment has one seam. Search, reindex and enrolment all reach `_ensure_watcher_soon` (`src/vaultspec_rag/server/_watcher.py:645`). Explicit start and timing changes reach `_ensure_watcher` (`src/vaultspec_rag/server/_routes_registry.py:223`, `src/vaultspec_rag/server/_routes_registry.py:268`).
- `_ensure_watcher_soon` runs on the event loop and is a dict probe when the watcher exists. The opt-out check must not add file I/O per request.
- Missing-root retirement already returns early for a deleted root (`src/vaultspec_rag/server/_watcher.py:663`). Its stale-root records are process-local and bounded (`src/vaultspec_rag/_root_presence.py:41`, `src/vaultspec_rag/_root_presence.py:96`). Pruning releases watcher ownership only and leaves retry history and indexes for a returning root (`src/vaultspec_rag/server/_watcher_stale.py:1`).
- The storage manifest (`src/vaultspec_rag/storage_manifest.py:244`) is storage-lifecycle bookkeeping. Its loader treats a malformed file as empty (`src/vaultspec_rag/storage_manifest.py:335`). Its writer rewrites every entry from the typed model (`src/vaultspec_rag/storage_manifest.py:370`). Storage reconcile and prune remove entries. An opt-out stored there would be lost on any of these paths, and a new field would change its versioned shape.
- The preprocess approval store is the existing pattern for per-root operator intent: one JSON sidecar in the managed status directory, keyed by canonical root, that refuses to write when it could not read (`src/vaultspec_rag/indexer/_preprocess_approval.py:49`, `src/vaultspec_rag/indexer/_preprocess_approval.py:82`).
- Confirmed stale search hits may request an incremental job for the root (`2026-10-26-stale-search-hits-adr`; `src/vaultspec_rag/_search_drift.py:123`). That is automatic index mutation outside the watcher.
- Lifecycle verbs emit one envelope and treat an already-satisfied request as success.
- `2026-06-01-service-operability-adr` keeps lazy per-root start as the default, gated only by the global `watch_enabled`, and deferred per-project overrides. This record adds the first per-root override, for enablement only. Timing stays global.

## Considered options

- **Keep `watch_enabled` as the only control.** Rejected: it is global and cannot express one root's intent.
- **Add `auto_update` to the storage manifest entry.** Rejected: the manifest's owner, loader, writer and pruning serve storage lifecycle, and its malformed-as-empty load would silently re-enable updates.
- **Make `updates stop` suppress re-arm only until restart.** Rejected: it fixes the search-time re-arm but not the restart.
- **A dedicated per-root opt-out sidecar in the managed status directory, checked at the one implicit-enrolment seam.** Chosen.

## Constraints

- The opt-out is keyed by canonical root key (`src/vaultspec_rag/_root_identity.py:16`). It lives in the managed status directory, never in the repository.
- Absence of a record means automatic updates are enabled, as today.
- Only `server updates stop` sets the opt-out. Only `server updates start` clears it. Search, reindex, enrolment, timing changes, prune, storage operations and restart never set or clear it.
- While a root is opted out:
  - search, reindex and enrolment do not start its watcher;
  - `server updates timing` does not start it and reports the opt-out with the start command;
  - the stale-hit drift auditor does not request an incremental job for it and records the audit as `deferred` with reason `auto_update_disabled`;
  - explicit index requests run normally. The opt-out governs automatic work only.
- The opt-out survives service restart, root deletion and `server updates prune`. A deleted root that returns keeps its opt-out. Missing-root retirement is unchanged and is checked first.
- Fail closed toward operator intent. If the sidecar is unreadable or malformed, implicit enrolment starts no new watcher for any root, status reports `unverifiable` with the sidecar path, and a write refuses rather than replace the unread file. Watchers already running are not stopped. Resolved at acceptance: an unreadable sidecar fails closed as stated here.
- The request-path check reads a process-local copy. The service is the only writer, so the copy is loaded at startup and replaced on each successful write.
- `server updates stop` succeeds when no watcher is running. It still records the opt-out and reports `already_stopped`. `server updates start` on a root that is not opted out behaves as today.
- `watch_enabled=false` still disables every watcher and wins over a cleared opt-out.
- No version bump. This decision changes no storage schema, storage manifest version, policy or content fingerprint, or package version, and needs no release. The new sidecar is a new file carrying its own format field. Wire responses gain fields additively.
- Scoped refinement of `2026-06-01-service-operability-adr`: its lifecycle decision gains the per-root opt-out as a second gate after `watch_enabled`. That record carries the dated amendment.
- Scoped refinement of `2026-10-26-stale-search-hits-adr`: confirmed stale hits on an opted-out root are verified and reported as before, but do not request repair. Resolved at acceptance: the opt-out also defers stale-hit drift repair, and that record carries the dated amendment.
- Resolved at acceptance: repository enrolment with `watch: false` does not set the opt-out. Only `server updates stop` sets it.

## Authorization

User instructed on 2026-11-20 that every identified backlog issue lands in one PR; open questions resolved with the drafted recommendations by the coordinating session.

## Implementation

We will persist a per-root automatic-update opt-out, honour it at the implicit-enrolment seam and in the drift auditor, set and clear it only through the explicit updates verbs, and report it on every status surface.

- New module `src/vaultspec_rag/watcher_intent.py`, torch-free. It owns the sidecar `auto-update.json` under `managed_status_dir()`: a format field plus records keyed by canonical root key, each holding the root path, `auto_update: false`, the time set and the initiator. Writes use `write_json_atomically` (`src/vaultspec_rag/_atomic_write.py:195`) under a process lock. It exposes one predicate returning `enabled`, `disabled` or `unverifiable` for a root, plus `disable(root, initiator)` and `enable(root)`. Module, file and field names may change within these constraints.
- `src/vaultspec_rag/server/_watcher.py`: `_ensure_watcher_soon` returns without starting when the predicate is not `enabled`, after the `watch_enabled` and missing-root checks. `_ensure_watcher` gains no branch; the start route clears the opt-out before calling it.
- `src/vaultspec_rag/server/_routes_registry.py`: `stop_watcher_route` records the opt-out, then stops, and returns `status` (`stopped` or `already_stopped`) and `auto_update`. `start_watcher_route` clears the opt-out, then starts, and reports `auto_update`. `reconfigure_watcher_route` refuses to start an opted-out root and says so. `get_watcher_state_route` adds a root-filtered `auto_update_disabled` list and total, bounded by the existing limit.
- `src/vaultspec_rag/server/_lifespan.py`: load the sidecar into the process-local copy at startup.
- `src/vaultspec_rag/_search_drift.py`: in `_diagnose`, before incremental admission, return `deferred` with reason `auto_update_disabled` for an opted-out root.
- `src/vaultspec_rag/operator_state/_models.py`: `RootFeatures` gains `auto_update`. `src/vaultspec_rag/api.py` fills it beside `watcher_running` (`src/vaultspec_rag/api.py:1362`). MCP `get_index_status` inherits it.
- `src/vaultspec_rag/server/_routes_operator.py`: enrolment of an opted-out root reports `watcher_status: disabled_by_operator` with the start command.
- `src/vaultspec_rag/cli/_service_watcher.py`: `updates stop`, `start` and `status` render the new fields and emit exactly one envelope on every JSON exit path. `src/vaultspec_rag/_operator_commands.py` supplies the `server updates start` command string beside `server_updates_prune_command`.
- Docs: `docs/cli.md`, `docs/automatic-convergence.md`, `docs/service-mode.md`.
- Tests: on a real service, stop updates, search, and assert no watcher starts; repeat across a restart; start clears it; an unreadable sidecar starts no watcher and refuses a write; prune and root deletion keep the record; the drift auditor defers. Prove each guard can fail by mutation.

No listed file is under `src/vaultspec_rag/indexer/`, so this work does not overlap the lane editing `indexer/_document_indexer.py` and the preprocess hook modules.

## Rationale

The opt-out is operator intent, so it takes the properties of preprocess approval: per root, outside the repository, durable, and fail-closed on an unreadable store. A separate sidecar keeps one owner per fact and leaves the storage manifest to storage lifecycle. One predicate at `_ensure_watcher_soon` covers every implicit path. Making explicit start the only way to clear it means search, reindex and restart cannot undo it. Suppressing drift repair too keeps the name honest: an opted-out root receives no automatic index mutation.

## Consequences

- An operator can keep one root's index unchanged across searches and restarts without disabling updates elsewhere.
- An opted-out root drifts from disk until the operator starts updates or runs an explicit index. Per-hit freshness still reports the drift.
- A corrupt sidecar pauses new automatic enrolment for every root until repaired. Status names the file. This is the accepted cost of never overriding intent.
- A deleted root's opt-out stays until `server updates start` clears it. The sidecar is not bounded by count. Reconsider if operators opt out of large numbers of short-lived worktrees.
