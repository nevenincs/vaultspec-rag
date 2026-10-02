---
tags:
  - '#audit'
  - '#resident-service-recovery'
date: '2026-10-02'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:76c9a35f7d79bff4ea495582f25c7bb3024a963baa8444b13de2d75e50b23c6f'
related:
  - "[[2026-10-02-resident-service-recovery-plan]]"
---

# `resident-service-recovery` audit: `resident incident diagnosis and integrated recovery review`

## Scope

Investigate the 2026-10-02 resident-service degradation and disappearance, repair the approved plan on feature/resident-service-recovery from base 29a148a0, and verify rollout from the current checkout. The original machine logs, registry, manifests, and job state were copied before intervention to C:/Users/hello/AppData/Local/Temp/vaultspec-rag-incident-20261002-203057. Registry copies contain credentials and must remain local. Formal review is pending stable completed code and rollout evidence.

## Findings

### terminal-refusal | high | New file events repeatedly reopened structural rebuild refusal

The last 256 jobs at the incident snapshot contained 217 full_reindex_required failures, six other failures, and 33 successes. TUI and MCP code membership policies differed from their canonical proofs. `src/vaultspec_rag/watcher_retry_policy.py` cleared refusal, circuit, failure history, and retry time on new scope intake; an isolated production-class reproduction admitted again before its existing retry deadline. Failed controller settlement also projected converged after scope was cleared. S01 owns persistent refusal, truthful settlement, precreation failure classification, and verified operator rebuild reconciliation.

### abandoned-receipt | high | Proof certification ran before abandoned writer recovery

MCP vault receipt 60edffd3bb7d473a832344cd8564e91e remained reserved from 2026-10-01 20:22:49 local with a running ingest generation and no mutation units. Scoped vault indexing acquired a fenced proof before its checkpoint recovery could run, yielding repeated open-receipt errors. Code and document entrypoints shared the ordering gap. S02 owns canonical recovery under source writer leases, exact confirmed-delta replay, and explicit rebuild replacement for partial evidence that cannot be safely reconstructed.

### unreachable-policy-input | medium | Excluded nested ignore files changed membership identity

The previous collector pruned fixed exclusions but walked project-excluded and RAG-excluded trees. MCP policy discovery collected 727 patterns, including 476 beneath var; corrected reachable discovery collects 243 at inspection. These files cannot affect admitted membership. S03 prunes with effective parent rules before descent, preserving directory negation and always-excluded rules. Legitimate ignore changes still require explicit rebuild when proof membership differs.

### stale-feedback | medium | A removed recommendation anchor failed hybrid and fallback search

The retained log records Qdrant's missing point 5605631922811243205 at 18:22:32 local. Both query paths reused its recommendation and returned service failure. This was a missing point, not evidence that a collection disappeared. S05 filters only absent feedback anchors under the point lock and retains surviving positive/negative feedback plus the original query vector.

### lifecycle-attribution | low | The latest disappearance was explicitly requested shutdown

The old daemon PID 59068 received attributed stop requests at 18:26:04 and 18:26:05 UTC (20:26 local), from a CLI in the CI fleet worktree and the scheduled resident stop task. The fleet deliberately stops this resident while Windows native tests own host capacity and restarts after completion. Retained fatal log is empty; Qdrant logs have no panic/error or OOM evidence. Subsequent daemon PID 28196 was stopped by this session only after confirming zero active jobs. Native CI admission 664 then became granted. Do not classify these explicit stops as proven native crashes.

### controller-retry-projection | medium | Successful recovery can retain stale open-circuit status

Preparatory independent review found empty-scope convergence and successful controller completion retaining circuit_state OPEN and old retry_at after the retry authority has recovered. The same applies when verified rebuild clears refusal. This is assigned back to S01 for canonical projection and regression coverage before final review.

### document-writer-lease | high | Recovery could mistake a live document reservation for abandoned work

Preparatory integrated review traced `src/vaultspec_rag/indexer/_document_indexer.py` releasing its source writer lease after the parent snapshot, reserving the next receipt outside that lease, then reacquiring for ingestion. With pre-certification recovery, a concurrent caller could roll back that live empty reservation. S02 remains open for a continuous writer lease through reservation, execution, and settlement plus a two-caller regression. Code and vault already retain the lease continuously.

### rebuild-attempt-ownership | high | One-shot rebuild reconciliation could retain abandoned attempt ownership

Preparatory review found `src/vaultspec_rag/watcher_runtime.py` constructing a temporary retry-policy owner during completion. Construction can adopt a dead process's abandoned attempt token, while rebuild reconciliation rejects a still-fenced attempt. Discarding that temporary owner without settling or releasing the reservation can block the later canonical watcher start. S01 remains open for non-owning completion reconciliation or canonical ownership settlement and a dead-owner fence to completion to watcher-start regression.

### newer-scope-loss | high | Successful captured work could erase a newer structural refusal timestamp

Preparatory review traced mid-attempt scope overflow or recovery-marker refusal through `src/vaultspec_rag/watcher_retry_policy.py` successful settlement: success cleared failure classification/time while retaining scope_refusal. If the attempt was unchanged, an older verified proof and old rebuild history could then falsely clear the newer lost scope. S01 remains open to preserve structural refusal evidence across captured success and verify that old rebuilds are rejected while a later explicit verified rebuild can reconcile.

### durable-scope-bound | high | Intake could persist a scope that the durable reader rejects

S01 temporal regression work found intake checking pending paths alone while durable reload bounds pending plus captured paths. An event arriving during an active attempt could therefore write state that cannot be reloaded. S01 now uses the reader's combined bound and verifies reload after overflow; captured success, failure, and interruption must all preserve a newer structural refusal.

### collection-refusal-classification | high | Stored sparse model mismatch was reported as a generic retryable fault

The first checkout MCP vault incremental job 79f3dda0-5567-4c04-8d0b-d7c7b6676782 refused stored naver/splade-v3 vectors against the accepted replacement Linkup-Platform/linkup-sparseup-embed-v1, but persisted error_kind other. StorageModelError and its geometry base lacked the canonical explicit-rebuild classification. S06 supplies that typed terminal refusal; S04 must rebuild populated affected domains under the replacement identity.

### backend-capability-projection | medium | Managed server health and root status identify the local engine

Live health and all four root statuses report backend_capabilities.backend qdrant-local while their Qdrant lifecycle and storage path correctly report the managed server at port 8765. BackendCapabilities hard-codes its only backend literal. S06 must reflect the configured backend through the existing capability owner and preserve the supported local mode.

### rebuild-observation-cutoff | high | Verification time cannot prove a sweep observed newer lost scope

The rollout interruption prompted review of a full sweep that reads file A, then loses A's later event during scope overflow, then commits a verified proof. S01 checks proof verification after refusal but not sweep start or generation creation after refusal. The verified proof certifies indexed ledger/storage evidence; it does not re-read all source bytes after the lost event. A newly admitted resume can also reuse a pre-refusal generation. S07 must require both the job start and full generation creation after the structural refusal cutoff and retain refusal for the in-flight and old-generation resume cases.

### Code repair review through 888e809b

Independent integrated review passes all code Steps. S01 preserves terminal refusal, bounded durable scope, captured-attempt evidence, retry projections, and canonical attempt ownership. S02 recovers safe abandoned publication evidence before certification, keeps the document writer lease continuous, and requires committed proof before generation publication. S03 excludes unreachable policy inputs while retaining legitimate invalidation. S05 filters absent relevance anchors and retains surviving feedback. S06 classifies incompatible collections as explicit-rebuild refusal and reports the actual managed-server backend. S07 requires job start, generation creation, and proof verification after structural scope refusal; an older resumed generation retains refusal until a fresh explicit rebuild observes that scope.

Applicable suites passed: S03 91 tests, S05 77 tests, S02 112 tests, S01 138 watcher tests plus 67 adjacent checks and 36 job/lifecycle tests, S06 227 tests, and S07 141 tests. Each Step also passed package lint and format and changed-path typing. Intended production mutations failed their guard assertions and restored executions passed, including 37 watcher guard sequences and three real-ledger observation cutoff cases. Source findings are resolved. S04 remains open for live sparse-model migration, publication verification, search, and controller convergence.

### starting-daemon-port-stop | high | Explicit-port stop reports stopped while an owned startup still holds resources

During rollout, a scheduled checkout startup spawned daemon PID 61428 and Qdrant PID 49636 before port 8766 opened. `server stop --port 8766 --json` returned already_stopped while both processes remained alive; canonical default-port `server stop --json` then identified and stopped PID 61428. The explicit-port branch only probes health before deciding absence, bypassing durable service ownership for an owned starting daemon. S08 must share existing process identity and termination guards for a matching persisted port, and preserve other-port and foreign PID refusals. Fleet startup/admission raced while its listener-only resident check still observed absence. Rollout now uses the fleet's existing operator hold, owned cleanup, and timed restoration while the current native attempt finishes.

### dependent-ci-resident-restart | high | Released hold can restart service during another dependent native attempt

Independent review confirms `fleetctl/host_admission/resident.py` in the deployed CI authority equals the main checkout at SHA256 ad27418a597b515101c59e0574d1c2610d025647bb573ef4c4de20580227bdcf. When any attempt is granted, upcoming becomes None. A hold for a released prior attempt can then enter the non-listening start branch despite a granted dependent registration. Attempt 679 exhibited this overlap. The preparation loop also visits waiting attempts after reconciliation; port absence does not certify cancellation of an asynchronously requested start. S09 owns service-specific active and consecutive dependency handling, bounded startup-stop evidence, CPU regressions, and trusted runtime rollout from the isolated CI checkout. Original resident shutdowns remain attributed requested stops; this finding explains a distinct startup/admission overlap observed during recovery.

### port-stop-incarnation-and-identity | high | Startup and tokenless serving termination need strong process evidence

Preparatory S08 review found that capturing OS birth only after reading launch argv can adopt a recycled foreign PID between those reads. Identity must be bracketed by matching birth observations and carry that incarnation through signaling. The serving explicit-port branch also accepts a tokenless Python HTTP listener through the legacy executable fallback. Termination needs exact resident launch evidence when no usable service token is present, while older status-report compatibility remains under its accepted ruling. Canonical owner lookup must also handle a dead launcher or divergent stale discovery pointer before declaring a requested warming port stopped. Marker tokens carried as data after Python -c are not an actual module launch and require a negative ownership case. S08 remains open until these boundaries and their real-process guards pass review.

### stale-resident-start-action | high | A selected start must not run after a newer stop enabled admission

Preparatory S09 review found host commands selected under the shared admission lock but executed later without action serialization or reservation revalidation. A delayed start selected before a dependent request could execute after another reconciliation completed stop and allowed its grant. Publishing no result afterward cannot undo that start side effect. S09 requires per-service command serialization outside the admission/SQLite lock, a current-reservation check before execution, and readiness revoked until every older in-flight start has been cancelled by the later acknowledged stop. A controlled threaded real-command regression and production mutation guard must establish this ordering.

### legacy-default-stop-ownership | high | Default and singleton recovery termination still accepted weak identity

The revised explicit-port checks exposed the same pre-existing weak termination policy in default server stop and machine-singleton reclaim. Both still accepted the legacy executable-name fallback and omitted an OS birth witness. A stale tokenless pointer to a foreign Python process can therefore authorize its termination. S08 must route all service-stop termination targets through the same canonical identity and incarnation confirmation, keeping the accepted read-only legacy observation policy separate. Real foreign-Python/default-stop and singleton-holder guards are required before rollout.

### Replacement discovery pointer deletion (MEDIUM)

Review found that stop cleanup could erase a replacement daemon's discovery status after the original target exited. S08 extends the existing status-lock deletion owner with the observed PID and port comparison before removal. Validation and deployment remain pending.

### Warming daemon mistaken for absence (HIGH)

S09 review found that a successful, Ready scheduled Start task can have returned through the resident service's already-starting path while its daemon is still warming up without a listener. Task idleness and an absent port therefore cannot authorize native admission. Repair must prove absence through the service control surface or acknowledge an actual stop, while preserving the rule that an originally absent service does not acquire restart ownership. Runtime admission is held during repair. The accepted CI resident-service decision tolerates an operator restart during an already active native job under its runtime resource floor; this finding concerns preparation before a new grant.

### Uncertain machine lock reported absent (HIGH)

Inspection of the authoritative machine-lock probe found that an unreadable lock and other open failures were returned as an unheld lock; `Path.exists()` can also suppress access errors. S08 now treats only confirmed missing paths as absent and propagates uncertain probe faults to the existing degraded discovery projection. This is required before the operator status exit code can safely authorize CI's absence probe. CPU fault regression and guard proof remain pending.

### S08 source repair verification

Source review clears the explicit/default stop, singleton reclaim and orphan reaping paths: canonical launch argv and health identity are bracketed by the same OS process birth; termination retains that original incarnation. Conditional status deletion compares PID and port under the existing writer lock across stop, start and status callers. Only confirmed missing machine-lock paths report absence; permission and coordination failures reach degraded discovery.

The final ten-file CPU suite passed 183 tests in 170.83 seconds. Package Ruff lint and format, strict basedpyright/Ty on all thirteen changed paths, design/length and cognitive/cyclomatic gates, and diff checks exited zero. Twenty-two process-only negative guard mutations failed the intended assertions, then restored fresh processes passed with unchanged source hashes. Copies of all four evidence logs are retained in the incident evidence directory. The new operator-context presence task returned the canonical absent result. Actual cold-start stop, ready service and publication repairs remain S04 verification work.

## Recommendations

Complete the open code Steps, verify their negative guards and integrated CPU behavior, then deploy the checkout through its separate locked GPU environment. Point the existing on-demand resident lifecycle tasks at that environment so CI restarts preserve the repair. Respect live CI ownership; repair affected publication domains through admitted explicit rebuild jobs, verify search and watcher convergence, and append the final review and rollout results here.
