---
tags:
  - '#audit'
  - '#incremental-index-recovery'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:6cebf066392594a218b1bba1646cda1aa60ed906512ff235339072ce823bbf8a'
related:
  - "[[2026-09-30-incremental-index-recovery-plan]]"
---

# `incremental-index-recovery` audit: `Integrated incremental indexing recovery review`

## Scope

Review the approved four-Step plan against base `14269e8e`, including its committed and uncommitted repairs. Trace publication receipts, explicit rebuild admission, route cleanup, service job completion, durable watcher recovery and canonical vault audits together. The accepted decisions linked by the plan govern this review. Independent preparation is PENDING while S01 and S03 corrections finish; the supervisor owns shared verification and all records.

## Findings

### receipt-delta-cost | medium | Broad receipt sealing still rescanned all mutations per path

Independent review identified quadratic iteration in `src/vaultspec_rag/indexer/_checkpoint_common.py`. The receipt owner grouped upsert units once by path. A deterministic traversal guard uses a real sealed receipt and observes its input without replacing production behavior; its mutation proof is pending.

### origin-collection | high | New route options could select a private origin but delete served rows

`src/vaultspec_rag/indexer/_route_migration.py` accepted a private code collection through general scan options while its migration journal deleted canonical served origins. The supervisor added an entry refusal. A real-store regression retained shared and unique logical IDs in both collections; removing the guard failed the intended raises assertion and restoration passed.

### watcher-admission | high | Settlement could adopt an abandoned admission token twice

Independent review identified that `src/vaultspec_rag/watcher_retry_policy.py` constructed a new execution-owning policy during settlement, after restart had already adopted the token. This could block fenced-attempt recovery or strand an ephemeral completion callback's reservation. The watcher owner is implementing a canonical state-only settlement path and persisted dead-owner regressions.

### watcher-unknown-scope | high | New lost observations could be cleared despite retained exact paths

A newer cancellation recovery marker could retain older failure timestamps and exact path sets. Rebuild settlement and ordinary scoped success could then clear unknown pending intent. The watcher owner is preserving the existing unscoped flag through marker consumption, later exact batches and captured-attempt success, with real marker regressions.

### inherited-complexity | low | An untouched search handler exceeds the configured complexity limit

An additional package complexity check reported `src/vaultspec_rag/server/_routes_search.py` function `_execute_search_request` at 21 against a limit of 20. Its diff against `14269e8e` is empty. This is an inherited gate limitation. The expanded receipt commit also exceeded the limit and is being refactored within S01; no threshold or suppression changes are authorized.

### receipt-recovery-resolution | low | Exact receipt recovery and crash continuation verified

S01 now recognizes only an exact mutation-free rolled-back reservation against its unchanged direct parent. Explicit FULL plus REBUILD authority can close confirmed SEALED work through the canonical receipt commit, with exact projection, parent revision, reservation and file-state readiness checks, without reactivating or rewriting terminal generation history. Unsealed, unconfirmed, malformed and foreign work remains refused. The canonical finalization owner requires committed proof before generation publication. A real private code collection test covers proof commit before pointer publication, old served rows remaining present, replacement pointer publication and subsequent cross-kind cleanup. Independent follow-up review found no further defect in these changed interactions.

The final CPU publication command selected all unit ledger, publication, checkpoint and new recovery modules: 169 tests passed in 67.95 seconds. The earlier 177-case combined command had one obsolete fixture failure; seeding its proof before publication corrected it, and both affected read-path tests passed. The narrowed lifecycle branch also passed its three cases and both type checkers. Logs are in the local temporary files `incremental-recovery-final-publication-tests.log` and `incremental-recovery-shared-ledger-tests.log`.

### receipt-delta-cost-resolution | low | Delta derivation uses one grouped traversal

The 1,000-unit real sealed-receipt guard passed. Reinstating the old per-path journal filter failed the intended traversal-budget assertion; immediate restoration passed. Exact rebuild authority, stable projection fields, readiness, committed-proof continuation and private collection preservation also have uninterrupted red/restored-green evidence in `incremental-recovery-new-receipt-guard-evidence.json`. All temporary production mutations were restored before shared verification.

### route-cost-resolution | low | Incremental reconciliation and candidate reads stay bounded

S02 reloads the durable sealed receipt and reconciles only its changed paths in batches of at most 256; mutation-free completion performs no collection scans. FULL rebuild retains its complete cleanup. Real local SQLite/Qdrant tests cover destination-confirmed migration, unchanged and unrelated row preservation, filtered code/document scrolling and multi-batch coverage. All eight cases passed in the combined command, and eight red/restored-green guard sequences are recorded in `incremental-route-guard-evidence.jsonl`.

Candidate membership now seeks publication-point indexes with the requested candidate page as the outer SQL loop. The previous join order grew from roughly 22,000 to over two million SQLite VM operations between 10 and 1,000 receipt paths. Both canonical and local receipt guards now meet the fixed-page budget, and restoring the old query failed the intended cost assertions before immediate restoration passed. Evidence is in `incremental-candidate-guard-evidence.json`. Route replay records progress only after acknowledged deletion and durable journal completion.

### origin-collection-resolution | low | Private origins are refused before mutation

The new cross-kind options guard is covered by a real-store test retaining shared and unique IDs in served, private and destination collections. Removing the entry refusal failed its exact raises assertion; restoration passed. Independent follow-up review confirmed that the guard protects the canonical served-origin journal contract.

### recovery-progress | low | Receipt recovery did not record its actual durable completion

Follow-up review identified that explicit rebuild recovery consumed the attempt's liveness budget without recording its completed canonical receipt transaction. The receipt owner is adding progress only after successful rollback or confirmed receipt commit, with no reset during reads, integrity verification, absent work or refused recovery. Real-ledger coverage and mutation evidence are pending integration.

### rebuild-publication-truth | high | A failed document generation could appear as a successful job

`src/vaultspec_rag/indexer/_document_indexer.py` can mark its checkpoint FAILED for path failures and return an `IndexResult`. The existing dispatch converted every nonthrowing result into successful job completion. The new settlement callback and historical restart scan could therefore clear a refusal for a rebuild that never published. The shared source/job boundary must report the actual checkpoint outcome, and both settlement paths must require the exact successfully published canonical generation and proof. Preprocessing skip diagnostics alone are insufficient evidence of either failure or publication. Vault jobs also need their existing checkpoint identity exposed to the canonical job projection; the receipt and watcher owners are implementing these repairs within S01 and S03.

### recovery-progress-resolution | low | Only completed recovery advances liveness

S01 records durable progress after the canonical receipt commit or empty rollback returns successfully. Six real-ledger cases cover sealed and empty success, absent receipt, unsafe unsealed work, failed readiness and refused rollback; both successful paths advance once, and all refused or absent paths retain the original progress state. All six guard mutations failed their intended progress assertion and passed after immediate restoration. Evidence is in `incremental-recovery-receipt-progress-guard-evidence.json`.

### vault-checkpoint-resolution | low | Vault jobs can identify their canonical owner

The existing `VaultRunCheckpoint` is exposed through `VaultIndexer.last_checkpoint`, initialized empty and assigned at all three actual open sites in the full, incremental and payload owners. Four CPU cases use real temporary storage and ledger state for empty full, ordinary and scoped incremental, and a metadata-only refresh with manually seeded vectors. Five guard mutations cover initial state and each opening path. The final affected S01 command passed 37 cases; both strict type checkers and package Ruff/format passed after a mixed-line-ending correction. Evidence is in `incremental-recovery-vault-exposure-guard-evidence.json` and `incremental-recovery-progress-exposure-final-unit.log`.

## Recommendations

Finish the in-scope corrections and required checks, then append the final integrated verdict and applicable evidence. Preserve these findings and append their resolutions. Keep ordinary commit authority strict, protect concurrent unknown scope, and verify private code pointer recovery with real temporary storage. Do not deploy, push or merge this implementation branch.
