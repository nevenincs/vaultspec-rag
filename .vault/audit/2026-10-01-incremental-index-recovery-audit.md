---
tags:
  - '#audit'
  - '#incremental-index-recovery'
date: '2026-10-01'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:f8f78fcabcec3175315271f5e3cc17fc2af9978843c6521821aea3e832495d79'
related:
  - "[[2026-09-30-incremental-index-recovery-plan]]"
---

# `incremental-index-recovery` audit: `Integrated incremental indexing recovery review`

## Scope

Review all four closed Steps against base `14269e8e` on branch `fix/incremental-index-recovery`, including committed S01, S02 and S04 and the completed stable S03 working tree. Trace publication receipts, explicit rebuild admission, route cleanup, service job completion, durable watcher recovery and canonical vault audits together. The accepted decisions linked by the plan govern this review. The independent reviewer reused completed traces and checked every corrective interaction; the supervisor owned shared verification and all records. Source remained unchanged between final gates and the final review.

The 2026-10-04 integration review covers S01 through S04 on `feature/monitor` against checkpoint `4d871170`, including merge resolutions and the portable storage-survey CLI test fixture. The current user authorizes consolidation of local branch work into the monitor PR, verification, and a push to that feature branch. Earlier implementation-only restrictions remain part of the historical record; this integration does not deploy the installed service.

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

### historical-publication-truth | high | Failed persisted incremental attempts could consume captured scope

Final S03 review found that an old document incremental attempt could also mark its generation FAILED and return a result. Its persisted job could therefore say SUCCEEDED with an explicitly failed per-attempt resilience outcome. The restart owner then recorded successful captured-scope consumption. The watcher owner is applying a typed failed/refused interpretation for the document and vault paths that always open a current checkpoint, while preserving valid unchanged code attempts that can reuse an older owner. The canonical FULL_REINDEX_REQUIRED failure owner must also restore pending and captured exact paths before clearing the attempt identity, keeping newer unknown scope refused. Real persisted restart regressions, valid code no-op coverage and scoped mutation evidence are required before S03 closes.

### historical-recovery-order | high | Restart-time refusal could outlive a later covering rebuild

The final historical recovery trace identified an ordering facet of `historical-publication-truth`: when restart first discovers an old falsely successful incremental job, recording its failure at the current restart time can make a later certified successful rebuild look too old to cover it. The first history scan may already have skipped that rebuild because no refusal existed yet. S03 must use the persisted terminal outcome's time, reconcile certified rebuild history after recovered-attempt settlement, and preserve genuinely newer unknown observations. A real persisted restart regression and uninterrupted mutation proof are required before closure.

### watcher-admission-resolution | low | Settlement preserves execution ownership and root identity

The state-only policy loader settles an obsolete refusal without adopting an abandoned admission reservation a second time. Restart reuses its existing execution-owning policy, and completion preserves the existing callback while waking the scheduler. Legacy dead attempt fences are released only with positive owner identity, proved death and an attempt older than the certified rebuild. Constructor recovery retains original refusal timestamps. Windows unregister and join use the same normalized resolved root identity. Real persisted policy and scheduler regressions and their restored guard sequences cover these interactions.

### watcher-unknown-scope-resolution | low | Lost observations and exact paths remain durable

Cancellation recovery markers retain unknown pending intent through marker consumption, later exact batches and captured-attempt settlement. Successful rebuilds clear only the refusal they cover and preserve pending, captured and newer dirty scope. Canonical FULL_REINDEX_REQUIRED failure restores pending and captured exact paths before closing the attempt identity, retaining convergence work and newer unknown metadata. Historical document and vault jobs with explicitly failed current-attempt outcomes are refused even if their old job state says SUCCEEDED; valid unchanged code attempts can retain prior-owner telemetry. The restart ordering facet recorded above remains pending separately.

### rebuild-publication-truth-resolution | low | Completion and rebuild settlement require actual publication

The source/job boundary checks the actual returned checkpoint's terminal publication outcome rather than treating a nonthrowing IndexResult as success. Real JobManager dispatch cases cover full and incremental code, document and vault failures, plus successful code no-op and safe skip diagnostics. Removing each of the six production call-site validations failed its exact persisted job-state assertion before immediate byte restoration passed. Completion callbacks and bounded restart history additionally require the exact per-attempt succeeded generation, canonical source/root/backend/collection compatibility, FULL mode, clean VERIFIED proof, published owner and valid publication token. Foreign, unpublished, pruned and superseded proof cannot settle a refusal. Vault resilience exposes its canonical checkpoint identity and retains observed peak telemetry even when no owner is present.

The S03 local evidence file `.pytest-tmp/watcher-mutation-evidence.json` currently contains 96 uninterrupted intended-red/restored-green records. These include historical outcomes, failure precedence, exact dirty-scope preservation, valid code prior-owner no-op handling, all six actual dispatch validation call sites and vault peak telemetry. The eight real dispatch orchestration cases and the preceding 165-case affected watcher/job command passed. The final ordering regression and combined supervisor gates are pending; no final verdict is implied by this intermediate evidence.

### historical-recovery-order-follow-up | high | Truthfully failed historical attempts also need the covering rebuild pass

Independent review of the first ordering correction found that its second bounded history pass was limited to the legacy SUCCEEDED document/vault case with an unpublished per-attempt outcome. A genuinely FAILED incremental job with FULL_REINDEX_REQUIRED can also be persisted before its policy callback runs, followed by a later certified rebuild before restart. Recovering that terminal attempt creates the same old refusal. S03 must reconcile covering rebuild history after terminal recovery whenever a canonical full refusal exists, including this modern failed-job case, with persisted regression and omission guard evidence. The original historical-order finding remains open until both terminal-state variants pass final review.

### historical-outcome-unknown | high | Missing document or vault outcome cannot prove captured-scope success

The complete terminal-state matrix trace found that old SUCCEEDED document/vault jobs can lack resilience or a terminal outcome: historical resilience projection could fail silently, and the previous vault owner did not expose its checkpoint. These always-opening sources cannot prove successful publication from the job state alone. S03 must retain their captured paths as a typed recovery refusal, using recorded terminal time when available so a later certified full rebuild can cover it. Missing resilience and missing terminal outcome need both no-cover and covering-rebuild regressions. Valid code no-owner and unchanged prior-owner successes must retain their explicit exception. The canonical JobManager attempt join will replace the focused test fixture's vulnerable five-second event-only wait, with a bounded timeout and outcome diagnostics while preserving terminal and callback assertions.

### historical-publication-truth-resolution | low | Recovery preserves unproved scope and reconciles covering rebuilds in order

S03 now restores captured and pending paths for failed or unproved always-opening document/vault attempts. Missing resilience, missing outcome and explicit non-success outcomes are refused rather than inferred successful. CODE retains valid unchanged prior-owner and no-owner successes. Recovery carries the persisted terminal job time into canonical durable failure settlement, retains the newest observation, refusal time and stronger refusal detail, and retries bounded certified-full history after every terminal settlement. This includes modern FAILED/FULL_REINDEX_REQUIRED jobs for all three sources, as well as legacy SUCCEEDED attempts. Missing or foreign identity and absent terminal timing remain conservative.

The expanded real persisted historical matrix passed all 52 cases. Fifteen additional uninterrupted mutations cover modern FAILED second-history omission for all sources, missing/non-success document/vault outcomes, captured-scope retention after a covering full rebuild and code no-owner exceptions. Sixteen earlier ordering proofs cover timestamp propagation, the second history pass and newer unknown/refusal/capacity evidence in both document and vault paths. The final S03 evidence contains 127 valid red/restored-green records for 125 distinct mutations, with zero invalid records; all temporary bytes are restored and the canonical ledger acquisition owner has no final diff. Independent final trace and the combined supervisor test run remain pending.

The earlier six-module test run passed 180 cases and failed one five-second event-only fixture wait. Seven affected waits now join the real canonical JobManager attempt with a 30-second bound and diagnostic outcomes while retaining their callback, terminal-state and settlement assertions. That earlier run is retained as failure evidence and is not presented as a passing gate.

### final-static-gates | low | Required static checks pass on the completed implementation

The supervisor reran `python -m ruff check src dev tools conftest.py`, `python -m ruff format --check src dev tools conftest.py` and both `python -m ty check --python <main .venv interpreter>` and strict `python -m basedpyright --pythonpath <main .venv interpreter>` over every Python file changed from `14269e8e`, including newly added files. All four commands exited zero on the final stable source; formatting checked 921 files and Basedpyright reported zero errors, warnings or notes. The additional full-package `complexipy src/vaultspec_rag --failed` command still exits one solely for the untouched search handler recorded above at 21 versus 20. Every changed production function passes the configured complexity limit. No threshold, suppression, dependency or baseline search change was introduced.

### final-integration-review | low | PASS for all four completed Steps

The final independent integrated review reports PASS against `14269e8e`. All reported functional findings are resolved and all four Steps are closed. Receipt recovery, bounded cleanup, actual publication outcomes, historical restart ordering, exact and unknown scope preservation, Windows root identity and canonical payload audits satisfy the governing accepted decisions. The final supervisor watcher/job command passed 751 tests in 124.79 seconds with process exit zero; its result is in `incremental-recovery-final-watcher-job-tests.log` under the local temporary directory. Applicable earlier publication, real-storage and audit verification remains valid, including the 169-case publication suite, eight real-store route cases, the final 37-case receipt/checkpoint suite and 41 audit/adjacent cases. S03's 127 uninterrupted restored guard proofs supplement the receipt, route, candidate-query and audit mutation evidence already recorded above.

Package Ruff and formatting, both strict type checkers over every changed Python file, plan validation and all 20 feature health checks pass with no diagnostics. There are no required verification gaps. The inherited search-handler complexity limitation remains disclosed; changed production functions meet the configured limit. The running installed service was not changed during implementation, and this local branch is not pushed, merged or deployed.

### monitor-receipt-compatibility | low | Current publication and recovery fences are preserved

The integration keeps the current checkpoint progress observer and pending-publication recovery owners. Receipt recovery requires the exact explicit full-rebuild projection and confirmed recorded units. Empty rollback also requires zero committed units. Operation-neutral no-op recognition preserves FULL PUBLICATION compatibility while retaining exact parent, compatibility key, revision, reservation sequence and journal-free fences. Compaction fixtures publish on a separate backend without finalizing an open receipt. The receipt worker reports 35 receipt cases, 23 checkpoint interaction cases and seven final recovery cases passing, plus Ruff, formatting and strict Basedpyright. New guard tests record intended assertion failures and immediate restored passes.

### monitor-watcher-ordering | low | Historical outcome time preserves the rebuild observation cutoff

Independent review identified a restart ordering issue: settling an old successful CODE attempt at restart wall time made older unknown intent appear newer than a covering certified rebuild. Historical terminal time now reaches successful, interrupted and failed settlements; the policy retains the maximum of existing observation time and recorded outcome time. The persisted regression covers both pre-rebuild unknown intent and genuinely newer intent. Current checkpoint observation drives truthful dispatch results and exact generation/proof certification. Final guard evidence and shared gates remain pending.

### monitor-route-audit-integration | low | Modern storage owners and canonical audit identities remain intact

Bounded changed-path reconciliation retains the current raw audit projection, root-owned origin deletion, destination geometry verification and bounded classification cache. All 50 route, storage, scaling, compaction and generation cases passed in the supervisor command. Omitting the raw projection path filter failed the intended scope assertion; byte restoration passed. The seven older real-store integration cases already exist in the canonical CPU test module and are not duplicated. S04 source and regression tests match the previously reviewed recovery branch; its guard evidence remains applicable and the integrated audit/checkpoint/integrity/schema command passed 42 cases.

The previous Linux 3.14 CI failures exposed a storage-survey test fixture under the OS temporary root. A synthetic read-only root now lets simulated server and client temp environments disagree on every platform. The existing assertions remain; all 22 module cases passed. Dropping the published temp-root fact failed the exact CLI assertion and immediate restoration passed. Production survey and CLI code are unchanged.

### monitor-integration-verification | low | PENDING final shared verification

The independent code trace found no remaining high or critical program defect in S01 through S04 after the compatibility and historical-timing corrections. Required final evidence remains with the supervisor: repository-wide lint, formatting, both type checks, vault checks, full CPU tests, builds and dependency audit. Worker guard mutations must be restored before those gates run. This intermediate review does not claim final verification or authorize default-branch changes.

### monitor-integration-final-verification | low | PASS on the final executable tree

The final canonical `just test-all` completed with 7,110 passes, seven platform-specific skips and eight warnings in 486.57 seconds on executable tree `72edafee9920894b50d39bffddb518f25570a1ac`. Windows uses the supported xdist worker budget of four, reserving scheduling headroom for native monitors, browsers and owner-witness subprocesses. The complete CPU selection, strict network/startup assertions and all existing deadlines remain unchanged. Earlier default-auto scheduling failures and unchanged isolated passes remain in the ledger and temporary logs. GPU, MPS and the quiet-machine performance lane explicitly reported unavailable-environment skips; no accelerator acceptance is claimed.

Repository-wide `just check-all` and `just build-all` exited zero on tree `947c0513099ac639060f9fd2805db71f199cb8d9`. Python, frontend and dependency inputs remained unchanged afterward. The only executable change was the independently reviewed Windows worker environment budget; fresh `just check-workflow` and the complete CPU workflow guards passed on the final tree. Both Python type checkers, formatting, frontend build, both configured complexity limits, canonical CLI parity and vault checks passed. The earlier inherited search complexity finding is superseded by the current passing gate without threshold or suppression changes. `just audit-deps` and `just dev check` also passed with unchanged applicable inputs. The verified native Windows monitor build was supplied to actual browser and lifecycle cases.

Receipt, route, watcher, storage-survey CLI and substitution guards have intended assertion failures followed by immediate byte-restored passes. Independent integrated review found no remaining high or critical defect in S01 through S04. Final evidence is recorded in `TEMP/vaultspec-monitor-push-test-all-four-workers-20261004.log`, `vaultspec-monitor-push-check-all-20261004.log`, `vaultspec-monitor-push-build-all-20261004.log` and `vaultspec-monitor-worker-budget-workflow-20261004.log`. Metadata-only verification records receive fresh markdown and vault checks before commit.

### monitor-branch-history-integration | low | Preserve reconciled local work in the monitor PR

The supervisor checked all local branch tips and registered worktree heads against the monitor integration. Missing recovery code is included through the ordinary incremental-recovery merge. Security and canonical code-file changes were checkpointed in `4d871170`; resident recovery, diagnostics, cache/release handling and other overlapping changes already have their current implementations in monitor. The seven reconciled branch histories will be preserved with a history-only merge that retains the verified source tree. The obsolete shutdown diagnostic workflow remains in history because its own CI failed canonical workflow guards; the current canonical workflow provides the active coverage. The missing incident checkout's recorded commit is preserved without pruning the worktree registration.

## Recommendations

Implementation and required verification are complete. Preserve the strict canonical commit and certified rebuild gates, newer unknown intent and non-destructive private code publication during release. Keep the inherited search complexity limitation visible rather than changing its threshold or adding a suppression. Any installation into the running service belongs to the ordinary release flow; do not push or merge this implementation branch.
