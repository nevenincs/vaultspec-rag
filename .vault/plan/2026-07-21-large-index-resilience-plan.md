---
tags:
  - '#plan'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
tier: L3
related:
  - '[[2026-07-21-large-index-resilience-adr]]'
  - '[[2026-07-21-large-index-resilience-research]]'
  - '[[2026-07-21-large-index-resilience-reference]]'
  - '[[2026-07-21-service-job-control-adr]]'
  - '[[2026-07-21-service-job-control-plan]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-plan]]'
---

<!-- RETIRED: S04 -->

# `large-index-resilience` plan

## Description

Replace restart-from-zero and corpus-sized memory growth with a storage-confirmed,
resource-bounded indexing workflow. The plan first adds enforceable RSS and CUDA ceilings,
bounded full and incremental vector lifetimes, a durable-progress deadline, and persistent
watcher circuits. It then adds the per-root SQLite generation ledger required to resume at
the last committed file segment, exposes resilience state through the service domain,
coordinates cooperative control with the accepted job-control plan, and establishes honest
support profiles whose managed-service floor includes the 250872-chunk incident corpus.

W01 alone is not sufficient to restart the poisoned large-root workload. W01 and W02 together
are the mandatory safety gate: bounded retention, memory termination, retry circuits, and
storage-confirmed checkpoints must all pass before any large-root daemon restart or reindex.
Execution and acceptance use isolated storage roots. The currently installed machine-global
service and its Qdrant child remain untouched until that gate is explicitly satisfied.

## Steps

## Wave `W01` - safety gates and bounded execution

Add enforceable resource, retry, and streaming limits first; downstream resume work depends on these bounds, and the large-root daemon must not restart after only this wave.

### Phase `W01.P01` - resource and outcome contracts

Define configuration, typed safety outcomes, and one reusable RSS and CUDA budget before index paths enforce them.

- [x] `W01.P01.S01` - Add explicit queue, no-progress, retry-circuit, RSS, CUDA, and support-profile configuration with environment mappings; `src/vaultspec_rag/config.py`.
- [x] `W01.P01.S02` - Define typed no-progress, memory-ceiling, circuit-open, and admission outcomes with shared remediation; `src/vaultspec_rag/_job_errors.py`.
- [x] `W01.P01.S03` - Upgrade memory observation into an enforceable RSS and CUDA budget sampled outside gpu_lock; `src/vaultspec_rag/memory_probe.py`.
- [x] `W01.P01.S05` - Verify production configuration and deliberately low resource budgets through imported behavior; `src/vaultspec_rag/tests/test_config.py`.

### Phase `W01.P02` - bounded vector lifetime

Remove whole-corpus and device-retention amplifiers across full and both incremental code paths.

- [x] `W01.P02.S06` - Transfer sparse document outputs to CPU immediately after forward completion and narrow caller lock spans; `src/vaultspec_rag/embeddings.py, src/vaultspec_rag/indexer/_streaming.py`.
- [x] `W01.P02.S07` - Define bounded file segments, weighted slices, CPU transfer, and immediate vector-field release; `src/vaultspec_rag/embeddings.py, src/vaultspec_rag/indexer/_streaming.py`.
- [x] `W01.P02.S08` - Convert full indexing to weighted production without whole-corpus vector sorting or retention; `src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_chunk_worker.py, src/vaultspec_rag/indexer/_preprocess_glue.py`.
- [x] `W01.P02.S09` - Convert unscoped incremental indexing to bounded file-segment streaming; `src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `W01.P02.S10` - Convert scoped incremental indexing to bounded file-segment streaming; `src/vaultspec_rag/indexer/_codebase_indexer.py, src/vaultspec_rag/indexer/_streaming.py`.
- [ ] `W01.P02.S11` - Verify sparse CPU retention and bounded slice cleanup on real CUDA; `src/vaultspec_rag/tests/integration/test_embeddings.py`.

### Phase `W01.P03` - workflow retry and no-progress policy

Add a durable-progress deadline and persistent watcher circuit above existing operation-level storage retry.

- [x] `W01.P03.S12` - Construct the server-mode store client from explicit operation timeout configuration; `src/vaultspec_rag/store.py`.
- [x] `W01.P03.S13` - Clamp bounded write retry and sleep to the remaining durable no-progress budget; `src/vaultspec_rag/_store_writes.py`.
- [x] `W01.P03.S14` - Implement durable-progress deadlines and interruptible queue, retry, and shutdown polling; `src/vaultspec_rag/indexer/_run_policy.py`.
- [x] `W01.P03.S15` - Persist per-root watcher failure count, classification, retry time, circuit state, and convergence intent; `src/vaultspec_rag/watcher_retry.py`.
- [x] `W01.P03.S16` - Gate idle-tick dispatch through persistent closed, open, and half-open watcher transitions; `src/vaultspec_rag/watcher.py`.
- [x] `W01.P03.S17` - Verify real Qdrant failure, coalescing, backoff, circuit opening, half-open recovery, and reset; `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`.

### Phase `W01.P04` - safety-gate verification

Prove low ceilings, bounded queue shutdown, and circuit behavior through production paths before checkpoint integration.

- [ ] `W01.P04.S18` - Verify low RSS and CUDA ceilings stop production with typed outcomes and bounded cleanup; `src/vaultspec_rag/tests/integration/test_indexer_integration.py`.
- [ ] `W01.P04.S19` - Verify a blocked store consumer cannot trap producer queue waits or hold the writer lock beyond the deadline; `src/vaultspec_rag/tests/integration/test_indexer_integration.py`.

## Wave `W02` - durable checkpoint and recovery

Persist storage-confirmed generations and integrate resumable full and incremental finalization; completion of this wave is the minimum gate before any large-root restart.

### Phase `W02.P05` - transactional run ledger

Create the per-root SQLite generation and commit-unit authority with corruption and compatibility handling.

- [ ] `W02.P05.S20` - Implement the per-root SQLite run generation, signature, commit-unit, finalization, and compaction schema; `src/vaultspec_rag/indexer/_run_ledger.py`.
- [ ] `W02.P05.S21` - Verify atomic transactions, row-wise iteration, compatibility rejection, corruption handling, and immutable completion; `src/vaultspec_rag/tests/test_index_run_ledger.py`.

### Phase `W02.P06` - resumable pipeline integration

Drive full, unscoped incremental, and scoped incremental work from storage-confirmed ledger units.

- [ ] `W02.P06.S22` - Drive full indexing from deterministic ledger segments and storage-confirmed commit records; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W02.P06.S23` - Drive unscoped incremental indexing from compatible generation and file completion records; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W02.P06.S24` - Drive scoped incremental indexing from compatible generation and deletion records; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W02.P06.S25` - Stream metadata rows and deterministic point identities through the ledger contract; `src/vaultspec_rag/indexer/_code_meta.py`.

### Phase `W02.P07` - idempotent finalization and clean recovery

Make stale reconciliation, metadata publication, and clean-rebuild recovery restart-safe.

- [ ] `W02.P07.S26` - Implement idempotent stale-identity reconciliation and generation publication phases; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W02.P07.S27` - Atomically publish metadata from ledger rows and preserve the last valid sidecar until replacement; `src/vaultspec_rag/indexer/_code_meta.py`.
- [ ] `W02.P07.S28` - Persist clean-rebuild destructive intent and resume incomplete replacement generations without a second drop; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `W02.P08` - restart and invalidation verification

Interrupt real work and prove one-unit replay, exact final state, and safe signature invalidation.

- [ ] `W02.P08.S29` - Interrupt and restart a real multi-segment index and prove replay is limited to the last unrecorded unit; `src/vaultspec_rag/tests/integration/test_indexer_integration.py`.
- [ ] `W02.P08.S30` - Invalidate incompatible checkpoints on model, schema, content, membership, preprocessing, and configuration drift; `src/vaultspec_rag/tests/test_config_epoch.py`.
- [ ] `W02.P08.S31` - Interrupt each finalization phase and prove restart converges to exact point IDs and metadata; `src/vaultspec_rag/tests/integration/test_indexer_integration.py`.

## Wave `W03` - service operability and control integration

Expose checkpoint and safety state through the service domain and coordinate the accepted job-control plan against the completed ledger contract.

### Phase `W03.P09` - service-domain resilience snapshots

Publish generation, checkpoint, retry, circuit, memory, profile, and terminal state once for every adapter.

- [ ] `W03.P09.S32` - Record generation, commit, replay, memory, deadline, circuit, profile, and terminal fields in canonical job snapshots; `src/vaultspec_rag/jobs.py`.
- [ ] `W03.P09.S33` - Shape bounded job collection and detail responses from canonical resilience fields; `src/vaultspec_rag/server/_routes_jobs.py`.
- [ ] `W03.P09.S34` - Include bounded resilience rollups in service health without loading torch on the reporting path; `src/vaultspec_rag/server/_lifespan.py`.
- [ ] `W03.P09.S35` - Render checkpoint, retry, circuit, memory, profile, and remediation fields without recomputing policy; `src/vaultspec_rag/cli/_service_jobs.py`.
- [ ] `W03.P09.S36` - Verify jobs, health, and CLI surfaces expose identical resilience state and typed outcomes; `src/vaultspec_rag/tests/integration/test_service_jobs.py`.

### Phase `W03.P10` - job-control plan coordination

Bind the accepted job-control execution waves to ledger safe points without duplicating their runtime or API ownership.

- [ ] `W03.P10.S37` - Expose ledger commit units, protected spans, and typed safety signals through the run-policy safe-point contract; `src/vaultspec_rag/indexer/_run_policy.py`.
- [ ] `W03.P10.S38` - Verify service-job-control cooperative indexing phases use ledger safe points and preserve one-unit replay; `src/vaultspec_rag/tests/integration/test_index_job_control.py`.

### Phase `W03.P11` - operator visibility verification

Prove jobs, health, status, and logs expose the same resilience state and remediation.

- [ ] `W03.P11.S39` - Verify controlled, interrupted, memory-limited, timed-out, and circuit-open jobs converge on one operator snapshot; `src/vaultspec_rag/tests/integration/test_service_jobs.py`.

## Wave `W04` - support profiles and corpus acceptance

Define honest backend and hardware admission and prove the accepted incident corpus on the declared managed-service profile.

### Phase `W04.P12` - named support profiles and admission

Define managed and local profiles and distinguish host, corpus, and disk refusal outcomes.

- [ ] `W04.P12.S40` - Define named managed-service and embedded-local profiles with benchmark-derived resource and corpus dimensions; `src/vaultspec_rag/index_profiles.py`.
- [ ] `W04.P12.S41` - Measure source bytes, files, generated chunks, and weighted units without materializing the corpus; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W04.P12.S42` - Enforce hardware and backend profile admission at service job submission before GPU work; `src/vaultspec_rag/jobs.py`.
- [ ] `W04.P12.S43` - Verify profile requirements, corpus limits, disk preflight, checkpoint preservation, and structured refusal; `src/vaultspec_rag/tests/integration/test_indexer_integration.py`.

### Phase `W04.P13` - large-corpus and concurrency acceptance

Measure bounded growth, concurrent search headroom, and completion at the incident corpus floor.

- [ ] `W04.P13.S44` - Create a reproducible large-index resilience harness using the production index path and real backends; `src/vaultspec_rag/tests/benchmarks/bench_large_index_resilience.py`.
- [ ] `W04.P13.S45` - Compare real-CUDA RSS and allocated and reserved high-water marks at N and two-N corpus sizes; `src/vaultspec_rag/tests/integration/test_indexer_integration.py`.
- [ ] `W04.P13.S46` - Prove concurrent search retains reserved GPU headroom while bounded indexing progresses; `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`.
- [ ] `W04.P13.S47` - Complete the 250872-chunk incident floor on the declared default managed-service profile; `src/vaultspec_rag/tests/benchmarks/bench_large_index_resilience.py`.

## Wave `W05` - system verification and review

Run the complete resilience, concurrency, restart, and operability verification matrix and close with mandatory code review.

### Phase `W05.P14` - complete regression matrix

Run focused and full suites across indexing, watcher, storage, jobs, restart, and concurrency.

- [ ] `W05.P14.S48` - Run focused indexer, watcher, storage-write, jobs, profile, restart, and GPU integration suites; `src/vaultspec_rag/tests`.
- [ ] `W05.P14.S49` - Run the complete project test suite without skips or expected failures; `pyproject.toml`.
- [ ] `W05.P14.S50` - Run pre-commit lint, formatting, type, and policy checks over the completed change; `.pre-commit-config.yaml`.

### Phase `W05.P15` - architecture and safety audit

Review the finished system against both resilience and job-control ADRs and all GPU, storage, and test rules.

- [ ] `W05.P15.S51` - Perform the mandatory code review for checkpoint correctness, bounded resources, retry liveness, GPU discipline, operability, and test integrity; `.vault/audit/2026-07-21-large-index-resilience-audit.md`.

## Parallelization

Waves are ordered. Within W01, P01 lands before P02 and P03; P02 and P03 may then proceed in
parallel only when their files do not overlap, and P04 runs after both. W02 is ordered P05,
then P06 and P07 as a coordinated implementation over the same ledger and indexer files, then
P08. No large-root restart is authorized before P08 passes.

Cross-plan sequencing is load-bearing. Large-index W01 and W02 establish the bounded pipeline
and ledger before service-job-control W02 threads control through indexing. Service-job-control
W01 establishes the manager and token before large-index W03 migrates canonical job snapshots.
Large-index P10 and service-job-control W02 are coordinated rather than parallelized when they
touch `job_control.py`, `_run_policy.py`, `_streaming.py`, or `_codebase_indexer.py`. The
job-control watcher, shutdown, and operator waves follow those shared safe points. Large-index
W04 starts only after W03 and the relevant job-control integration tests pass. W05 is strictly
last.

The machine-discovery plan is independent and may execute concurrently, except real CUDA and
Qdrant acceptance runs remain serialized to protect the one machine GPU and backend.

## Verification

- Plan validation reports canonical L3 structure, one intentionally retired `S04`, contiguous
  rows inside every Phase, and no placeholder, link, frontmatter, or markdown error.
- Full, unscoped incremental, and scoped incremental paths retain memory proportional to the
  configured unit and queue budget rather than corpus size, with sparse results transferred to
  CPU and vector-bearing objects released after commit.
- Deliberately low RSS and CUDA ceilings stop production with typed outcomes, preserve the last
  confirmed checkpoint, release writer and GPU resources, and prevent immediate watcher retry.
- A watcher failure persists its convergence intent, backs off, opens after the configured
  threshold, admits one half-open attempt, and resets only after successful completion.
- A no-progress deadline advances only on storage-confirmed ledger commits or finalization
  phases; a healthy long run has no total-duration cutoff.
- Restart after interruption replays at most the last unrecorded file segment and converges to
  exact point IDs, deletion state, and metadata. Incompatible signatures never skip work.
- Clean-rebuild interruption remains visibly `rebuild_incomplete` and resumes without a second
  destructive drop.
- Jobs, health, status, logs, and CLI rendering expose the same generation, commit, replay,
  memory, deadline, circuit, profile, and terminal fields.
- Cooperative control acknowledges only after the active ledger unit and protected mutation
  settle and all execution resources release.
- The default managed-service profile completes the 250872-chunk incident floor, and N versus
  two-N real-CUDA runs demonstrate bounded RSS and CUDA high-water growth while concurrent
  search retains reserved headroom.
- Focused tests, the complete suite, and pre-commit checks pass without fakes, mocks, patches,
  monkeypatches, skips, or expected failures.
- The mandatory audit reports no unresolved checkpoint, liveness, memory, GPU-lock, storage,
  operability, or test-integrity finding.
