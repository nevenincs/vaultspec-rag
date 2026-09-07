---
tags:
  - '#research'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:1eed00b0fcc066de0d35b67bdd14ca569030c979dbe2f293339f7282a87867e5'
related:
  - "[[2026-07-25-index-completeness-guard-research]]"
  - "[[2026-07-28-convergence-cost-research]]"
---

# `explicit-reindex-authority` research: `Prevent automatic incremental work from escalating to full reindex`

On 2026-09-07 a managed-Qdrant startup failure was followed by a local-backend service start, a watcher-labelled incremental request, two full-corpus code reconciliations, and severe search latency. Service, watcher, integrity, timeout, and recovery paths can authorize full-corpus work without an explicit full-reindex request: backend-neutral evidence, default-on integrity repair, scope-loss recovery, compatibility fallback, and configuration drift all let incremental work silently change cost class. The evidence favors explicit full-corpus authority at admission, a typed actionable refusal when it is absent, and detection which preserves published data without automatic repair.

## Findings

### The production incident was an incremental-to-full escalation, not an operator rebuild

Managed Qdrant exceeded its 300-second readiness deadline twice. The replacement daemon opened the project-local Qdrant store; its log compared zero local code points with a sidecar claim of 131,481 points, admitted an incremental job, and discovered 14,949 files for full reconciliation. That run processed the corpus but failed publication after 900.111 seconds without a recognized durable-progress event; retry state admitted another unscoped attempt. Raw evidence is retained under the current user's `.vaultspec-rag/service.log*`; defaults are at `src/vaultspec_rag/config/_settings.py:296` and `:300`.

The job record continued to describe the request as incremental. `JobSpec` has no effective operation or escalation authority, and dispatch hands incremental execution to the indexer without a cost-class guard (`src/vaultspec_rag/job_models.py:346`, `src/vaultspec_rag/job_dispatch.py:250`).

### Backend-neutral evidence turns a backend switch into apparent loss

Code and document sidecars record generation, content identity, and breadth without recording the physical backend (`src/vaultspec_rag/indexer/_code_meta.py:248`, `src/vaultspec_rag/indexer/_document_meta.py:127`). Run signatures identify a logical collection but not local versus managed storage (`src/vaultspec_rag/indexer/_run_checkpoint.py:102`, `src/vaultspec_rag/indexer/_document_checkpoint.py:98`), although the stores are distinct (`src/vaultspec_rag/store_runtime.py:298`, `:407`).

The managed-startup error recommends `server start --local-only` (`src/vaultspec_rag/server/_lifespan.py:468`) without explaining that local mode opens a distinct index. Tests verify local-only selection and the recommendation, but not a transition carrying published evidence (`src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py:649`, `:698`).

### Incremental entry points contain multiple silent full-work transitions

Code indexing enters `_full_index_locked` when published storage is absent or short, embedding format changes, content-shaping policy changes, or the ledger lacks a compatible parent (`src/vaultspec_rag/indexer/_codebase_indexer.py:916`, `:927`, `:943`, `:1004`, `:1231`). Membership drift removes watcher scope and forces whole-tree discovery (`src/vaultspec_rag/indexer/_codebase_indexer.py:332`).

Document indexing discards prior evidence on policy incompatibility or storage shortfall and calls `full_index` when no checkpoint remains (`src/vaultspec_rag/indexer/_document_indexer.py:1296`, `:1321`, `:1332`). The shared checkpoint deliberately rejects a parentless incremental so callers can escalate (`src/vaultspec_rag/indexer/_checkpoint_common.py:131`). Vault indexing clean-rebuilds for point-layout or chunk-boundary drift (`src/vaultspec_rag/indexer/_vault_indexer.py:500`, `:512`). A justified rebuild requirement and authority to execute it are currently the same decision.

### A normal search can initiate full-corpus work

Every successful daemon search evaluates collection breadth and sends `shrunken` to remediation (`src/vaultspec_rag/server/_routes_search.py:294`). Automatic repair defaults on (`src/vaultspec_rag/config/_settings.py:112`). It starts an incremental job specifically because the indexer will promote the shortfall to full reconciliation (`src/vaultspec_rag/_integrity_remediation.py:11`, `:116`). Tests pin the enabled default and recurring 600-second admission window (`src/vaultspec_rag/tests/test_integrity_remediation.py:66`, `:127`). Request spacing does not bound corpus cost.

### Recovery preserves the obligation but discards its scope

Changed paths live in memory, while persisted retry state stores only generations and unscoped flags (`src/vaultspec_rag/watcher_runtime.py:144`, `src/vaultspec_rag/watcher_retry.py:98`). Reloaded pending state, a dead attempt owner, or a recovery marker sets `unscoped_required=True` (`src/vaultspec_rag/watcher_retry.py:241`, `:248`, `:736`). Execution converts that to `paths=None` and full discovery (`src/vaultspec_rag/watcher_execution.py:581`). Tests assert this promotion (`src/vaultspec_rag/tests/test_watcher_retry.py:610`). Under restart or timeout, uncertainty about a small dirty set becomes authority to inspect the corpus.

### Useful finalization work is invisible to the no-progress clock

The 900-second clock advances only after a store-plus-ledger commit or a completed finalization phase (`src/vaultspec_rag/indexer/_run_policy.py:45`, `:167`). Route reconciliation scrolls pages, performs ledger lookups, journals migration state, and deletes rows but only calls `checkpoint()` (`src/vaultspec_rag/indexer/_route_migration.py:464`, `:554`, `:708`). The incident's approximately 1.5 GB ledger let useful work exceed 900 seconds; the next checkpoint failed before its labelled lookup because the clock had already expired.

### Health and logs conceal the transition and early degradation

Job summaries calculate degraded count, but `/health` reacts only to stalled count and latest failure (`src/vaultspec_rag/server/_routes_jobs.py:827`, `src/vaultspec_rag/server/_lifespan.py:1169`). Compatibility exceptions are caught without detail (`src/vaultspec_rag/indexer/_codebase_indexer.py:1016`, `:1243`, `src/vaultspec_rag/indexer/_document_indexer.py:1321`). Raw log rotation includes multiline subprocess tracebacks in a 2 MiB generation (`src/vaultspec_rag/logging_config.py:10`, `src/vaultspec_rag/config/_settings.py:301`), which evicted and split incident records.

### Prior remediation retained automatic escalation

GitHub issue #274 documented unattended incremental-to-rebuild behavior on 0.3.9. Its closure correctly records generation-safe publication, but also records default-on serve-time repair as the rehash-latch remedy. The current incident shows the residual failure: non-destructive full reconciliation can still consume the service, time out, and loop. https://github.com/nevenincs/vaultspec-rag/issues/274

### Detection, authorization, and execution need separate contracts

Keeping self-heal preserves unattended convergence but violates cost authority. Adding only backend identity leaves compatibility, configuration, scope-loss, and genuine-shortfall triggers. Increasing timeouts preserves unasked work and does not scale.

The evidence favors one indexer-boundary invariant: incremental entry points may detect and describe why full reconciliation is required but may not execute it. A typed terminal outcome can preserve the published index, degrade health, stop watcher retry loops, and direct an operator to an explicit full-reindex verb. Backend identity should distinguish foreign evidence from loss; finalization progress and health propagation make explicitly requested work reliable and visible.

Vector migration between backends and Qdrant recovery algorithms were not investigated because neither changes the authorization conclusion.

## Sources

- Current-user `.vaultspec-rag/service.log*`
- `src/vaultspec_rag/config/_settings.py:112`, `:296`, `:300`, `:301`
- `src/vaultspec_rag/job_models.py:346`
- `src/vaultspec_rag/job_dispatch.py:250`
- `src/vaultspec_rag/indexer/_code_meta.py:248`
- `src/vaultspec_rag/indexer/_document_meta.py:127`
- `src/vaultspec_rag/indexer/_run_checkpoint.py:102`
- `src/vaultspec_rag/indexer/_document_checkpoint.py:98`
- `src/vaultspec_rag/store_runtime.py:298`, `:407`
- `src/vaultspec_rag/server/_lifespan.py:468`, `:1169`
- `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py:649`, `:698`
- `src/vaultspec_rag/indexer/_codebase_indexer.py:332`, `:916`, `:927`, `:943`, `:1004`, `:1016`, `:1231`, `:1243`
- `src/vaultspec_rag/indexer/_document_indexer.py:1296`, `:1321`, `:1332`
- `src/vaultspec_rag/indexer/_checkpoint_common.py:131`
- `src/vaultspec_rag/indexer/_vault_indexer.py:500`, `:512`
- `src/vaultspec_rag/server/_routes_search.py:294`
- `src/vaultspec_rag/_integrity_remediation.py:11`, `:116`
- `src/vaultspec_rag/tests/test_integrity_remediation.py:66`, `:127`
- `src/vaultspec_rag/watcher_runtime.py:144`
- `src/vaultspec_rag/watcher_retry.py:98`, `:241`, `:248`, `:736`
- `src/vaultspec_rag/watcher_execution.py:581`
- `src/vaultspec_rag/tests/test_watcher_retry.py:610`
- `src/vaultspec_rag/indexer/_run_policy.py:45`, `:167`
- `src/vaultspec_rag/indexer/_route_migration.py:464`, `:554`, `:708`
- `src/vaultspec_rag/server/_routes_jobs.py:827`
- `src/vaultspec_rag/logging_config.py:10`
- https://github.com/nevenincs/vaultspec-rag/issues/274
