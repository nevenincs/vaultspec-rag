---
tags:
  - '#audit'
  - '#resident-service-recovery'
date: '2026-10-02'
modified: '2026-10-03'
body_schema: 'body-v2'
body_hash: 'sha256:8cbdaf3e0b37542fbd02b951faa7c610028d3d164d2731002ebfaebfdbb8f67e'
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

### S08 live cold-start verification, 2026-10-02 21:48 UTC

Checkout commit `06872afb` started an actual resident daemon, PID 65460, with machine-lock ownership and warming status while its port remained closed. The new operator-context Probe task completed freshly with result 2, correctly identifying presence. The explicit-port Stop command exited zero with stopped status for that same PID. Subsequent canonical process and lock observations proved PID 65460 and its managed Qdrant child 83044 were both dead and the machine lock was free. The Start client's failure after its daemon was intentionally stopped was expected and settled before the next start. Evidence is retained in `cold-start-observation.json`, `cold-start-task-probe.json`, `cold-start-explicit-stop.json` and `cold-start-stop-verification.json` under the incident evidence directory.

The checkout service was restarted for publication repair under the owned CI maintenance hold. Cold Qdrant collection recovery is progressing; service readiness and repaired publication acceptance remain pending.

### Scheduled Start budget below canonical readiness budget (MEDIUM)

During the source rollout, Qdrant completed progressive cold recovery in 606.50 seconds. The Start task then ended its launcher at the declared 15-minute limit (result 267014) while the detached daemon PID 70288 remained alive and loading models. The canonical CLI permits the Qdrant readiness ceiling plus 300 seconds of import/model allowance, with accelerator preflight preceding that timer (`cli/_service_start.py`). The action-task limit therefore undercut a legitimate bounded startup. S09 aligns the protected declaration and live Start task to 30 minutes; the operator presence task separately proves warming after launcher exit. No daemon restart or change to model/storage policy was required for this operational correction.

### Compatible resumed stream loses framing (HIGH)

Live linked monitor code retry `b4517037-b249-421f-8ffa-2a530bf475d3` failed after 24 of 999 paths: `a new file in one weighted stream must follow a file-end marker and begin at ordinal zero`. `CodeRunCheckpoint.pending_segments` filters committed segment units before `_slicing.iter_weighted_code_slices` applies the complete-stream transition invariant. Compatible committed prefixes or terminal segments therefore create apparent gaps even though the original producer stream is valid. S10 must retain original ledger unit identities, validate the complete canonical producer stream, and skip already confirmed mutation/encoding work without weakening malformed-boundary rejection. CPU real-ledger resume proof and service rollout remain pending.

The next retry request exceeded its 30-second client bound but created actual TUI child `76907432-189e-45cb-a9fd-7659135e5581`; it is progressing. The supervisor resolved the actual child from canonical job history before further admission, preserving parent lineage and avoiding duplicate retries. The ingest rebuild is also progressing. One sparse-encoding OOM bucket was discarded and replanned under a smaller token budget; progress continued, so this recovered pressure event is not a daemon crash.

### Cross-kind metadata reconciliation rejects an old-model origin | high | S11

At 2026-10-02 22:10:49Z the ingest code rebuild child `17928f13-7d3b-426a-b2eb-d043c82e46b9` failed after confirming 168 files, at write metadata. Its replacement code collection had already been bound; `reconcile_generation_storage` then scanned DOCUMENT payloads through the ordinary vector-conformance path and raised a sparse-model incompatibility on `r44f00d4631ce_document_docs`. No incompatible sparse vector was needed for that payload-only route check. Origin deletion used the same conformance-dependent owner, so bypassing the scan alone would leave real target flips broken. Rebuilding DOCUMENT before retrying CODE can unblock this state, but opposite origin configurations make ordering an incomplete remedy. S11 repairs vector-free metadata enumeration and destination-confirmed origin cleanup, retaining strict vector and donor conformance and journal ordering. The exact trace and canonical source owner were inspected after semantic discovery failed against the replacing monitor index. Source and live verification remain pending.

### S09 source checkpoint

The isolated CI branch `fix/resident-start-admission` committed the verified source as `7386cc3`. Focused 70, admission/lifecycle 162 and task/manifest 66 tests all passed, as did canonical Python/type/YAML gates. Twenty-two actual production-method mutation failures were followed by twenty-two restored fresh subprocess passes, with all ten owned file hashes unchanged. The trusted deploy preview contains exactly six admission runtime paths and only the resident-services configuration change; the launcher is unchanged. The protected live authority reports no granted/quarantined attempts, one waiting unprepared attempt and this recovery operation owned hold. Deployment remains deferred until publication maintenance ends, because the canonical deploy lifts its deployment hold. S09 is still open for runtime verification.

### S10 source verification and S09 formal review checkpoint

S10 is verified and closed for source execution. The complete raw segment stream reaches the single weighted consumer; original ordinal, digest and point identities survive committed prefixes, interior gaps and committed end markers. Raw ordinal transitions, weight bounds and final framing remain guarded. The checkpoint owner records indexed state only after its real ledger confirms every file segment; a newly confirmed interior gap can complete a file whose end marker was already committed. The test-only singular confirmation implementation was removed in favor of the canonical plural atomic owner.

Package Ruff lint/format (868 files), strict basedpyright/Ty on all seven changed paths, configured Pylint/design/length, cognitive max19, Xenon and diff checks exited 0. The affected CPU suite passed 53 tests; its one preexisting CPU-Torch conversion case was deselected on the torch-free development interpreter. Eight actual production-method mutations each failed their intended assertions, then restored fresh subprocesses passed; all seven owned byte hashes matched final gates and proof evidence. The incident archive now retains `s10-source-gates.json`, `s10-weighted-resume-proof.json` and per-direction logs. Formal source review found no remaining issue. Live exact retry verification remains S04.

The first misplaced integration-tier invocation requested canonical service quiesce at 22:29:48Z; its drain timed out at 22:30:08Z and was aborted back to running, with no GPU borrower granted. The large clean rebuild remains inside its protected publication interval and continues confirming units. Final selections use the proper CPU tier. The owned automatic CI-hold restoration deadline was extended from 2026-10-03 00:58:11Z to 02:30:00Z for measured large rebuild progress plus source rollout; earlier restoration remains required when rollout completes. No active CI work was cancelled.

Independent S09 source and verification review passed at CI commit `7386cc3`, confirming all final tests and 22 mutation/restoration pairs against current hashes. Only trusted live authority deployment remains pending for S09.

### S11 source verification

Cross-kind origin scans and exact journaled ID deletion now use bounded, noncreating, vector-free administrative operations restricted to this root's active CODE/DOCUMENT collections. Destination completeness is checked through the canonical ledger and existing point evidence before its selected collection passes strict vector conformance. An absent or incompatible destination retains origin points. Same-kind purge, ordinary reads/writes and donor access preserve their normal compatibility checks. Real-model integration remains in the integration tier; pure ledger and storage routing regressions now run in the CPU tier.

The affected CPU suite passed 57 tests, including 24 migration cases; nine genuine integration cases were deselected. Package Ruff lint/format (868 files), strict basedpyright and Ty on five changed paths, and configured design, nesting and complexity gates exited zero. Seventeen actual production-method mutations failed the intended assertions, and every restored fresh subprocess passed. The six monitored source hashes match the final checkout. Complete proof and logs are copied into the incident archive's s11-route-proof directory. Source review is clear; actual linked finalization replay remains S04 work.

### Aborted quiesce strands paused desired-running jobs | high | S12

Read-only follow-up reproduced a canonical paused job with desired RUNNING after the global pause aborted. The abort path calls recover_running_quiesced_resume, whose claim admits QUEUED only; this paused job is never prepared or dispatched. Accepted service-quiesce recovery requires PAUSED plus QUEUED desired-running work, preserving logical identity and operator paused/cancelled intent. The reproduction used isolated in-memory canonical components only.

### Unstarted capacity waiters retain control tickets | high | S12

A second isolated real-AnyIO reproduction held the index limiter with job1, then paused job2 before its worker entered. Job2 remained PAUSING with its compute ticket until job1 released the slot, because the first token checkpoint runs inside a worker after the limiter wait. The capacity wait itself must observe control without cancelling or abandoning an already-running worker. S12 owns both control repairs under the existing service-quiesce, job-control and concurrency rulings.

The current 10 PAUSING/desired-RUNNING repair jobs are distinct: their retained quiesce signals have a valid late-acknowledgement path after protected work completes. Controller abort reopens admissions; safe acknowledgement releases resources and schedules a same-ID attempt. Their pending projection is truthful, and no lost work was established for those jobs.

### Search conformance refusal escapes as HTTP 500 | high | S13

Four recent POST /search ASGI exceptions at 22:13, 22:29, 22:57 and 23:01 UTC end in StorageModelError. The concrete availability wrapper only catches collection disappearance, and the route only catches backend and quiesce faults. Accepted search readiness requires typed nonretryable rebuild-required source facts and HTTP 409; combined search must retain failed constituents beside useful compatible hits. S13 owns the narrow typed-error mapping without changing storage conformance, retrieval ranking or public schema. The pre-repair checkout service log is archived as checkout-pre-s12-service.log.

### Recovered sparse OOM probe assessment

The log sweep counted 70 recovered sparse OOM warnings by 23:06 UTC, with continued durable progress. The learned ceiling is retained on the model; accepted adaptivity deliberately probes upward after sixteen sufficiently loaded successful calls. Observed consecutive OOMs have 19 to 63 successful upserts between them, matching guarded recovery rather than reset-per-slice behavior. No new crash or discarded learned state was established. The previous single-bucket description covered the first observation only.

### S10 and S11 integrated final source review

Independent final review passes S10 and S11 together: 53 and 57 applicable CPU tests, all eight and seventeen intended production-mutation failures followed by restored fresh passes, and matching final source hashes. S10 file completeness and exact segment evidence remain authoritative before S11 destination validation and journaled origin deletion. Runtime verification is still pending S04, and S12/S13 must finish before the next restart.

At 23:20 UTC the actual TUI job remains inside protected ingestion, with 7883 of 10491 paths processed and recent progress. Ten repair jobs are PAUSING with desired RUNNING; the controller separately reports eleven compute tickets, which must not be conflated with job count. Canonical job detail proves the TUI worker still owns its index slot, project lease, writer lock and active pipeline. Those resources are not reported released.

### Live checkpoint resilience | medium | Running snapshots retain admission defaults

Review at 2026-10-03 02:00 UTC found `job_dispatch.py` publishing concrete checkpoint resilience only at attempt exit. Read-only evidence at 01:33:58 UTC shows the running MCP generation `5665e092078b43febab23033bce7d78a` with 18,295 confirmed units and a fresh durable commit, while the canonical job exposes generation null and zero committed units. The vault projector also discards its now-real checkpoint. Accepted large-index resilience D8/D9 and explicit-reindex observability require accurate attempt-owned live facts. S19 owns bounded checkpoint observation and actual vault projection, retaining absent vault support profile and ceilings. Verification remains pending.

### Vault durable progress | high | Healthy chunk commits do not renew the deadline

Review at 2026-10-03 02:00 UTC confirmed `VaultRunCheckpoint.record_confirmed_chunks` records actual ledger units without advancing its RunPolicy, and vault ingestion uses no write policy. The shared terminal publication marks a generation succeeded and compacts it before recording progress against the expired clock. A progressing full vault run longer than the no-progress timeout can therefore report timeout after successful proof and generation publication. Accepted resilience D4/D8/D9 and the shared vault publication lifecycle govern S20. The supervisor paused the three unstarted ingest, TUI and MCP vault repair jobs; each acknowledged desired PAUSED, attempt 1, revision 4, with no index capacity, project lease, writer lock or pipeline held. The protected MCP code worker remains running. Review verdict is REVISION REQUIRED until S20's real storage/deadline evidence passes. Vault memory profile exclusions remain unchanged.

The brief 01:30:43 UTC health degradation remains unattributed. File-completion counters intentionally advance only at file end; the accepted legacy stall policy and separate throughput-collapse diagnostic do not establish a new defect from that sample. Later observations are ready with no degradation reasons and unchanged resident/Qdrant identities.

**HIGH — S21 managed CODE weight violates the accepted floor.** The MCP CODE repair failed at 02:45:48 UTC after 9,393 of 9,806 files, 69,986 durable units and 134,967 physical points. It reported weighted bytes 549,758,571,584 against the 549,755,813,888-byte managed limit. Daemon PID 38488 and Qdrant PID 77200 stayed alive with zero backend restarts and no fatal output. This was a deliberate support refusal, not replay inflation, a physical 549 GiB allocation or an OOM crash. The canonical estimator reserves pinned 50,370 sparse dimensions at 80 lifetime bytes each. The real benchmark/chunker/support-budget CPU reproduction shows the accepted 83,624-file, 250,872-chunk floor weighs 1,021,070,531,368 bytes (950.946 GiB), while current enforcement rejects at 135,075 chunks. D6 already requires that floor. S21 corrects only the managed CODE aggregate cap to 1,024 GiB, retains cumulative accounting and all queue/runtime/embedded limits, and adds real floor/boundary regression and negative proof. Its dated D6 clarification records the derivation without claiming new above-floor capability. Source review remains pending.

### Resumed resource boundaries | medium | S22

The live MCP VAULT resumed attempt reports its current started reading beside the prior paused attempt's finished reading. Canonical resumed-attempt preparation increments attempt identity while retaining resources, and worker admission updates started without clearing finished. ResourceUpdate documents exact-attempt facts and carries no historical attribution. S22 clears boundary readings when preparing a new resumed attempt, preserving same-attempt pause withdrawal and terminal history. The VAULT pipeline_active=false value is intentional: that flag describes CODE/DOCUMENT consumer execution, while vault capacity/project/writer ownership remains independently visible.

### Synchronous health lock wait | medium | S23

The async health_handler calls synchronous ServiceRegistry.health on the HTTP event loop. That owner holds its registry RLock while awaiting each store lifecycle lock, and collection ensure holds that lifecycle lock across backend collection and payload-index operations. Thus slow storage can starve independent HTTP work. The exact 03:24:46 and 03:25:41 UTC health timeouts remain unattributed without lock-duration capture: document discovery and the long payload-only route scan do not hold this lifecycle lock. S23 reuses the existing anyio thread seam for the registry projection, retaining conformance results and existing bounded caller uncertainty without claiming a new health latency guarantee or caching success.

## Recommendations

Complete the open code Steps, verify their negative guards and integrated CPU behavior, then deploy the checkout through its separate locked GPU environment. Point the existing on-demand resident lifecycle tasks at that environment so CI restarts preserve the repair. Respect live CI ownership; repair affected publication domains through admitted explicit rebuild jobs, verify search and watcher convergence, and append the final review and rollout results here.

## Final control and search repair checkpoints

S12 additionally reproduced an explicit operator pause being rejected for PAUSING or retained idle PAUSED work whose desired state was RUNNING after global quiesce. All canonical capability owners now derive pausable state from the actual desired state; persisting operator intent retains the existing attempt, resources, revision guards and quiesce ownership. Recovery durably prepares retained desired-running work before admission reopens, reconciles late acknowledgements after reopening, and closes admission on publication failure. Capacity waiters observe control without abandoning admitted workers.

S12 is frozen with 253 affected CPU tests passing, all ten changed-source gates exit0, and 23 production-function process-only mutation proofs failing at the intended assertion then passing in a fresh restored process. S13 is frozen with 31 focused and 289 affected CPU tests passing, changed strict/design gates exit0, and 17 process-only fail/restored-pass proofs. The generic exception mapping and accepted same-geometry dense-model policy are preserved; typed incompatible storage becomes a nonretryable rebuild-required fact, and compatible combined hits retain failed constituents. Shared package Ruff lint and format pass for all 872 files. Root verified all nineteen owned file hashes and preserved complete proof directories in the incident evidence directory. Formal integrated evidence review precedes source closure.

At 23:31:40 UTC the canonical global pause reached its 20-second drain bound with admission closed and eleven compute tickets retained. Ten repair jobs were PAUSING/desired-RUNNING; two other leaves were failed. The active TUI rebuild continued forward and had confirmed 9,283 of 10,491 source files and 58,064 durable units before restart. At 23:34 UTC an authoritative admission snapshot was empty, the Start task was disabled, and canonical service stop succeeded for daemon PID 70288. Windows detached-daemon stop terminates the process; no graceful-shutdown claim is made. Root subsequently verified daemon 70288 and managed Qdrant 27336 absent and both ports unused. Durable per-root checkpoints and safe health/job projections were captured before stop. Linked canonical retries will reconcile unfinished attempts after the committed fixes restart. A fresh scheduled Probe completed at 23:36:13 UTC with its authoritative absence result0.

## Integrated S12 and S13 review

The independent reviewer issued SOURCE+CPU PASS for S12 and S13 against the current frozen files and complete evidence. All nineteen owned hashes and the additional unchanged storage-conformance hash match. All 23 S12 and 17 S13 actual production-function mutation logs fail at their intended assertion and pass after fresh restoration. No remaining source findings were reported. Quiesce recovery preserves closed durable preparation, protected workers and operator intent; search conformance refusal retains compatible combined results without starting rebuilds or weakening publication. S04 live rollout remains pending. Fresh captured subprocesses from both CPU and debug interpreters import this checkout and return stopped exit3 in human and JSON modes; earlier reported exit1 was PowerShell propagation, with no status-source defect.

## Continued rollout findings at 2026-10-03 00:07 UTC

The committed S12/S13 checkout restarted as daemon 2664 with managed Qdrant 88116 and reached readiness at 23:52:17 UTC. An actual 20-second quiesce, abort and resume recovered waiting desired-running jobs under their existing IDs as attempt2. Explicit operator pause remained held under its original attempt until separately resumed. Search incompatibility now produced typed nonretryable rebuild-required outcomes; compatible combined results remained usable.

The ingest CODE child 50a7e0c4-85af-42a2-9989-44c794cfef58 completed its interrupted finalization at 23:56:20 UTC: generation 02d3547f844c400184cd936ad9a4356d published 1,665 points across 168 file outcomes. This establishes the S11 vector-free origin repair on the resident.

The same control trace exposed S14: resumed REBUILD children passed clean=false at source entry despite retained rebuild authority. Untouched vault/document domains then refused incompatible old-model collections. S15 exposed inconsistent Windows root identity: forward-slash and uppercase-drive watcher filters returned zero controllers while the canonical lowercase root returned three. Review additionally found embedded-NUL path filters could escape as HTTP500; narrow bad-request validation is required. Independent source review passes S14 with 199 affected CPU cases, all changed gates and eleven production mutation/restoration pairs; actual source-entry and ledger-reuse proof scopes remain distinct.

### Resumed edits delete shared freshly written chunk IDs | high | S18

Monitor CODE child dcbefc0f-201f-483f-9975-e382def72940 failed the strict ingest barrier with 14,897 expected versus 14,541 actual points. Generation 81a0c6c67a714492951cef99cec90004 contains 7,700 UPSERT units and 14,897 distinct committed IDs; it has no deletion units. Real chunking/local-storage review reproduced whole-file drift retirement deleting unchanged chunk IDs already republished in the current mutation. The mechanism is confirmed; every one of the live 356 missing IDs has not been individually attributed. Fresh confirmed mutation IDs must survive retirement while all obsolete ledger units are removed.

### Historical deletion records revive retired expected IDs | high | S18

A separate interrupted deletion reopened a generation with zero live points and zero retained manifest paths, but the consumer seeded the deleted point identity from a durable deletion unit. Upsert-only ledger iteration must retain unfinished file prefixes while excluding deletion history; default all-operation iteration remains available to existing callers.

Canonical stop succeeded at 00:07:31 UTC after checkpoint capture. Daemon2664 and Qdrant88116 were verified absent with unused ports. The damaged monitor build and TUI generation 0f2e9d6c33454bfc9246c5393face70d must be invalidated through the canonical RunLedger API before the next repair admission. Storage and previously served collections remain intact. Start/Stop tasks stay disabled during this bounded repair window; Probe remains enabled and the owned CI maintenance hold is retained.

A separate cold-start investigation found retained generation ages within the accepted168-hour grace, so no incident-driven storage deletion is justified. CPU proofs nevertheless confirmed S16 disabled autoprune still admitted generation destruction and S17 CLI survey decoding omitted generation diagnostics. Those contract defects have explicit repair Steps and independent CPU verification.

## S18 source and canonical retirement checkpoint

Independent SOURCE+CPU review passes S18 against four frozen hashes: 85 affected CPU cases with one accelerator case deselected, eleven changed gates exit0 and six intended production mutation failures followed by fresh restored passes. Optional operation filtering pages correctly across two upserts beside deletion history and preserves unfinished confirmed prefixes. All eight prior S10 guard pairs were refreshed against the changed consumer and pass. Shared package lint/format and diff verification pass with all28 current source/test hashes unchanged.

At 00:33 UTC, with the resident and managed backend absent and the owned CI hold present, canonical RunLedger APIs invalidated monitor generation81a0c6c67a714492951cef99cec90004 and TUI generation0f2e9d6c33454bfc9246c5393face70d. Original signatures and evidence remain preserved; no served collection or storage was removed. Subsequent actual rebuild generation IDs must differ from both damaged IDs. The accepted drift ADR received a dated implementation clarification for shared chunk identities, preserving its single owner and ordering.

Timed maintenance restoration was extended to 04:30 UTC on 2026-10-03 for reviewed source rollout and fresh large rebuilds, with the same owned hold and cleanup task. Early cleanup remains required once verification finishes. Correct managed backend and service ports8765/8766 were checked unused before canonical retirement and rollout.

## S15 review and additional S16 boundary

Independent SOURCE+CPU review passes final S15:27 focused and335 affected CPU cases, seven recorded changed-file gates exit0, eight production guard fail/fresh-pass pairs including explicit NUL validation, and three refreshed S07 temporal guards against the extracted predicates. All eleven owned hashes match. Real ASGI tests cover Windows path aliases and malformed root/project_root filters, including conflicting valid/invalid filters. The affected suite refreshes S01/S07 recovery and S13 readiness/conformance/availability behavior.

S16 review additionally found archive expiry/size eviction still running while autoprune was disabled. The accepted autoprune decision places archive retention in stage4 of the same configured cycle and declares no independent archive enable; the existing policy documentation promises all destructive stages remain inert when disabled. S16 scope now also gates archive eviction while retaining enabled retention and independently configured reconciliation. Source and CPU review must finish before rollout.

## Expanded S17 survey fact audit

Independent per-namespace audit confirmed the CLI service decoder also dropped stamped model maps and vault/code/document point counts. The model loss falsely labelled stamped namespaces as predating stamping in human output. Published temp_rooted was discarded and recomputed under the client TEMP/TMP/TMPDIR/tempfile environment, so the client could report a different classification from the service. S17 now preserves all four dimensions alongside generation diagnostics through the existing canonical survey record and a shared fact accessor; both published true and false must survive, with canonical local fallback only when no valid published fact exists. Prefix, root, status, collection names, valid aggregate points, verification, footprint and queried-root facts already survived. HTTP-only snapshot age and envelope totals remain outside scope. Final source/gate/guard review is pending the expanded proof handoff.

Both monitor and TUI ledgers were preserved through SQLite consistent read-only backups before fresh rebuild publication can compact obsolete evidence. Their sizes are57,311,232 and441,352,192 bytes. A vector-free backend ID comparison and actual source-snapshot chunking will be attempted after backend readiness to bound attribution of the356 missing monitor points.

## Final S16 source checkpoint

Independent SOURCE+CPU review passes expanded S16 against both frozen hashes:13 focused and190 affected CPU cases, seven changed gates exit0 and five intended production mutation failures followed by fresh restored passes. Real local-Qdrant and complete-archive tests prove autoprune off preserves eligible generations and expired/over-cap archives, with byte-for-byte archive preservation, while still recording grace observations and running independently configured reconciliation. Enabled autoprune and explicit dry-run retain their accepted behaviors. Neither this repair nor incident investigation deleted any live backend storage or archive.

## Final S17 and integrated source checkpoint

Independent SOURCE+CPU review passes expanded S17 against all five frozen hashes:22 focused and220 affected CPU cases, seven configured gates exit0 and21 intended production mutation failures followed by fresh restored passes. Exact model maps, all per-kind count fields, generation unknown/empty/debt and published temp-root true/false facts survive service-to-CLI adaptation and applicable human rendering; malformed/legacy evidence retains conservative fallback.

The integrated S14-S18 review passes with every source finding in that batch closed. S01/S07 watcher behavior and temporal guards, S10 stream guards, and S13 search readiness/conformance were refreshed where applicable. All28 final source/test hashes match shared package lint/format/diff evidence. S09 trusted authority deployment and S04 actual fresh publication, search and watcher convergence remain open; the resident will restart only from these committed repairs.

## Final checkout resident start and repair admission

At 00:59 UTC the authoritative CI snapshot was empty and the owned hold was verified. The current committed checkout5e87f227 restarted through its hidden debug-environment Start task as daemon38488 with managed Qdrant77200. The editable import resolves to this monitor checkout and the pinned monitor checksum matches. Startup completed at01:02:09 UTC in161.92 seconds; the actual scheduled Probe reports presence result2 during warmup. Canonical health then showed models loaded, server backend1.19.0, zero restarts and open admission. Final publication and per-root readiness remain pending.

A vector-free scan of the preserved damaged monitor collection found exactly14,897 ledger IDs versus14,541 live IDs:356 missing and no inferred missing-count gap. All356 missing IDs across25 paths match chunks reconstructed from the actual indexed source snapshot253f1204, with zero unattributed current-source identities. This identifies the lost semantic points precisely; the real drift reproduction establishes the deletion mechanism. Full evidence is in missing-monitor-point-attribution.json beside consistent ledger backups.

Canonical retry created eleven linked children, saving each identity immediately; the already published ingest CODE child remained unchanged. Monitor CODE is now building fresh generation5a74174e98334bb4b199d337b12bb542, distinct from retired81a0c6c67a714492951cef99cec90004, with continued confirmed units and1,011 current source paths. TUI's fresh generation must be checked when its protected worker enters. No damaged generation is being trusted for resumption.

Monitor VAULT childbce9cd71-bd07-4a4a-8e1e-67a59672df19 was paused before worker admission, acknowledged PAUSED promptly with no capacity/project/writer/pipeline ownership, and resumed under the same ID as attempt2. Its actual full replacement and publication remain pending; this deliberately exercises the repaired resume authority boundary. The live CLI survey independently matches all14 published namespace fields, including four stamped model entries and false temporary-root classification, through the actual CLI process. No model loading or storage mutation was needed for that adapter proof.

The new daemon initially has no active project watchers, so its pre-admission watcher listing is empty rather than a path-filter failure. Explicit watcher activation and canonical path-alias convergence will be verified after replacement proofs settle.

## S19 integrated source checkpoint

S19 SOURCE + CPU review PASS at 2026-10-03 02:18 UTC, with no blocking findings. The actual checkpoint observer publishes attempt-owned code, document and vault facts after confirmed durable boundaries, outside the policy lock, at a bounded cadence. Opening, first durable progress, finalization and exit preserve visibility; closure detaches the observer, and canonical task ownership rejects stale writes. Vault checkpoint facts retain unknown profile and ceilings. All six source/test hashes match the gate and guard manifests. Ten separate gates passed, including 239 affected CPU cases; all eleven actual production mutations failed as intended and immediately passed in fresh restored interpreters. Shared package lint, format and diff passed with 33 changed source/test hashes. S14 authority coverage passed in the affected suite; unchanged S10 framing owners need no refresh. Four managed-integration projection caller migrations were statically checked, with no GPU borrower fixture executed. Evidence is archived in the incident's `s19-proof` directory. The resident still runs the earlier committed source while protected code/document work settles; S04 owns loading and live proof. S20's vault clock correction remains open.

## Continuing degradation and S20 wait evidence

At 2026-10-03 02:30 UTC, the protected MCP CODE job was degraded by its published throughput comparison: recent file rate 0.142 per second against median 2.313, ratio 0.062. It was not stalled. A fresh GPU forward was active, backend latency was 0.033 seconds, and Qdrant remained alive with zero restarts. Independent canonical ledger reads found 61,378 confirmed units and a durable commit less than two seconds old. Service logs show continued 32-chunk upserts and recovered sparse accelerator OOMs; the encode counter was 143 at this sample. The existing adaptive ceiling deliberately probes upward after 16 at-ceiling successful calls and replans failed buckets. This captured warning does not establish a new crash or justify speculative tuning. The earlier brief 01:30 sample remains unattributed; the later exact reason must not be retroactively assigned to it. Evidence: `degradation-evidence-0231.json` and `durable-progress-0231.json` in the incident directory.

S20 also confirmed that the two vault store ingest methods used an unconditional point lock despite receiving a deadline policy. The correction extends narrowly to those methods, reusing the canonical deadline-aware point lock already used by code and document storage. Real held-lock CPU checks and production mutations will prove bounded waiting. Successful terminal commitment must retire only deadline enforcement for cleanup and metadata epilogues, retain cooperative control delivery, and admit no additional storage writes. Failed terminal mutations and latched failures cannot retire the deadline. Source and evidence review remains pending. The authoritative CI admission snapshot remained idle at 02:30 UTC under the bounded maintenance hold.

## S21 controlled maintenance stop

TUI CODE entered fresh generation `060330354c214c37...`, distinct from its retired damaged generation, after MCP failed. An actual pause request at 02:47 UTC recorded desired PAUSED; acknowledgement remained deferred through the accepted clean publication protected span. The four unstarted document jobs were also given pause intent before the source restart. The three previously paused vault jobs retained that intent. Canonical Windows `server stop --port 8766 --json` succeeded at 02:55 UTC. This platform stop is abrupt native termination with owned-backend cleanup, not graceful in-daemon teardown. Independent native process and port checks confirmed daemon 38488 and Qdrant 77200 absent and no listeners on 8764, 8765 or 8766. The authoritative CI admission snapshot remained idle under the bounded hold. The incomplete and failed builds are preserved for canonical recovery; no generation was invalidated or storage discarded merely because of the cap refusal. Restart and exact recovery-state verification remain S04 work.

## S20 integrated source checkpoint

S20 SOURCE + CPU review PASS at 2026-10-03 02:59 UTC, with no blocking findings. Newly inserted vault units renew the exact attempt policy only after acknowledged storage and real ledger commit; duplicates, empty boundaries and failed commits do not renew it. Actual full, unscoped and scoped vault entry paths, payload writes, queues and safe boundaries use that policy, and the two vault write methods now use the canonical deadline-aware point lock. Successful terminal publication is preceded by a strict check; confirmed success retires epilogue deadlines and closes new storage admission immediately while preserving cooperative control, latched failures and independently bounded cleanup. Final live observation remains isolated and runs outside the policy lock. No schema, profile or memory ceiling is added.

Nine frozen source/test hashes match both gate and guard manifests. All ten separate gates passed; the affected CPU suite passed 235 cases with one Torch case deselected. All 22 actual production mutations reached their intended assertion failures (exit 1), then passed immediately in fresh normal interpreters (exit 0). The changed S19 observer isolation and unlock owners and terminal live observation were refreshed; applicable S14/S10 coverage passed. Package lint, format and diff passed with 40 current changed hashes. The broader run exposed stale test-only null policies and abstract checkpoint fixtures; all three were replaced with real CodeRunCheckpoint and RunPolicy rather than weakening production checks. An initial scratch-driver import failure occurred before mutation/test and was excluded, then corrected to use the canonical store entry. Evidence is archived in `s20-proof`. S20's HIGH source finding is resolved. Loading and live validation remain S04 work, and S21's independently confirmed managed corpus-cap finding remains open.

After the S21 controlled stop, consistent read-only SQLite backups preserved the MCP ledger (489,316,352 bytes) and TUI ledger (461,680,640 bytes) before future replay or compaction. `s21-ledger-backups.json` records their paths. No original generation, receipt or storage data was deleted.

## S21 integrated source checkpoint

S21 SOURCE + DECISION + CPU review PASS at 2026-10-03 03:08 UTC, with no blocking findings. Only the managed CODE aggregate weighted cap changes, from 512 to 1,024 GiB; the dated D6 clarification preserves the accepted floor and all cumulative, queue, runtime and embedded-local invariants. Real benchmark/chunker/segmenter/support-budget tests reach 250,872 representative chunks at 1,021,070,531,368 cumulative bytes and reject the first segment exceeding the corrected cap before yield, including across calls. The source finding is resolved; this is not a new above-floor GPU benchmark claim.

All seven separately captured changed-path gates passed, with 23 focused and 61 affected CPU cases passing. The affected run has seven deselections, including the unchanged Torch-dependent conversion test that could not execute in the CPU environment; its initial dependency-failure log is preserved. All three corrected actual production mutation pairs reached named assertion failures (exit 1), restored methods in finally, and passed in fresh normal processes (exit 0). A scratch annotation NameError was rejected as invalid guard evidence and corrected before the complete uninterrupted sequence was rerun. Eight dependency hashes and the shared 42-file package lint/format/diff manifest match current source. Evidence is archived in `s21-proof`. The resident remains stopped pending committed-source startup and compatible build recovery under S04.

## Committed-source live recovery checkpoint

The canonical Start task loaded editable checkout revision 4700ebcaf67060ea7e2edca9e292e0be37220aa8 on 2026-10-03 03:09:43 UTC. Daemon 83668 and managed backend 89504 became ready at 03:16:04 UTC, with zero backend restarts and an empty fatal log. Seven paused document/vault jobs retained operator intent across restart and were explicitly resumed under the same logical identities. Two monitor source refresh jobs replace earlier successful leaves because the source and audit changed after those publications.

MCP CODE linked retry e4117d6a-9471-46d2-b0d8-8e54b82f3b21 succeeded in 433630ms using compatible generation 5665e092078b43febab23033bce7d78a, 70806 committed units and 69986 replayed units. Its compacted clean publication contains 136334 retained IDs, all equal to actual backend payload IDs under the current Linkup sparse model. The initial phase with no file progress completed; read-only tracing confirms complete-corpus re-reading, framing validation and per-segment replay lookup before newly consumed file ends update the counter. No blocking defect follows from that temporary silence. The follow-up physical producer now binds the CODE current VERIFIED proof and validates its receipt-free read token before and after scanning. Document/vault proof artifacts additionally bind the job's actual generation to the scanned canonical generation.

MCP VAULT now publishes actual active generation f9c7ff508816401e842c6a59af1831e7 and real durable committed-unit/timestamp updates. A read-only SQLite observation at 03:28:28 UTC showed 1280 confirmed units, matching the live projection after its bounded publication interval. This is actual S19 active VAULT evidence; profile and memory ceilings correctly remain unknown. At 03:32:28 UTC six of twelve current repair leaves had succeeded, with all others running or waiting. Final all-domain physical proof, search, watcher convergence, S22 source rollout and trusted idle fleet deployment remain pending.

## S22 source verification checkpoint

S22 changes only job_manager/_control.py and tests/test_job_manager_transitions.py. The canonical resumed-attempt preparation clears started and finished resource boundaries through immutable replacement, preserving ownership flags and the existing revision, lineage and persistence transaction. Same-attempt pause withdrawal and terminal retry history remain unchanged. Ten separately recorded gates pass, including strict source/test typing and 187 affected CPU tests. Three fresh-process guards mutate the actual production method to omit started cleanup, omit finished cleanup, or wrongly clear same-attempt readings; each fails its intended assertion with exit 1, restores the original method in finally, and then passes in a fresh normal process with exit 0. Both source hashes remain unchanged. Evidence: .pytest-tmp/S22 and incident s22-proof archive. Shared package Ruff, formatting and diff gates pass with 44 changed source/test hashes. Final source review and the idle deployed restart are tracked separately from these checks.

At 03:42:28 UTC the real MCP VAULT generation remained running after more than 900 seconds, with 19264 durable units and a commit timestamp less than two seconds old. Canonical job projection at 03:42:16 showed 18880 confirmed units and a renewed 900-second no-progress budget. This is live S20 evidence of progressing work outlasting the original admission-age deadline; successful final publication remains pending.

## S22 formal review

Independent integrated source review: PASS, no blocking findings. Both frozen hashes, ten gates, 187 CPU passes and all three intended production mutation failure/restored-pass pairs were independently checked. Shared package gates and all 44 hashes matched. The resumed-resource finding is resolved in source; the final idle restart remains part of S04. S23 and final S04/S09 runtime proof remain pending.
