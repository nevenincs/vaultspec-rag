---
tags:
  - '#plan'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-30'
tier: L3
related:
  - '[[2026-07-24-service-quiesce-adr]]'
  - '[[2026-07-24-service-quiesce-research]]'
  - '[[2026-06-12-service-concurrency-adr]]'
  - '[[2026-06-24-service-hardware-singleton-adr]]'
  - '[[2026-07-21-service-job-control-adr]]'
  - '[[2026-07-28-pressure-management-adr]]'
---

# `service-quiesce` plan

## Description

This amended plan executes the accepted service-quiesce decision. `W01` retains the completed Event-gate history solely for auditability; its global hold design is superseded and must not be extended. `W02` is owned by the core lifecycle implementation lane and replaces that gate with acknowledged resource quiescence: controller state, cooperative drain, GPU-residency release, and same-ID job convergence. `W03` is owned by the service-interface lane and makes routes, adapters, status, and fallback behavior describe the one achieved controller state. `W04` is owned by the containment-and-validation lane and supplies the distinct borrower lease and CPU-only proof that no uncertain service state can trigger local GPU contention.

The release boundary is exact: only `quiesced` with `vram_released: true` and `safe_to_borrow_gpu: true` permits a borrower. A pause request, `pausing`, `warming`, timeout, rebuild failure, or degraded discovery is not permission to allocate GPU work. The plan deliberately excludes service starts, live GPU runs, and co-scheduled end-to-end tests; those require a separately authorized maintenance window.

## Steps

## Wave `W01` - Retire the unsafe hold gate

Preserve the completed phase-one history while replacing its unsafe global hold semantics under the amended service-quiesce decision.

### Phase `W01.P01` - Historical Event-gate primitive

Record the completed phase-one Event-gate work only; its global hold semantics are superseded by the amended decision and must not be extended.

- [x] `W01.P01.S01` - Create the torch-free Event-gate primitive with running and held states plus latch behavior; `src/vaultspec_rag/job_control.py`.
- [x] `W01.P01.S02` - Integrate the historical gate into RunControlToken protected checkpoints; `src/vaultspec_rag/job_control.py`.
- [x] `W01.P01.S03` - Add the historical Event-gate and protected-checkpoint guard coverage; `src/vaultspec_rag/tests/test_job_control_unit.py`.

### Phase `W01.P02` - Historical global-gate wiring

Record the completed global-gate wiring only; W02 replaces it with controller-owned resource quiescence.

- [x] `W01.P02.S04` - Expose the historical process-global gate beside the registry GPU lock; `src/vaultspec_rag/service.py`.
- [x] `W01.P02.S05` - Inject the historical global gate into managed attempt tokens; `src/vaultspec_rag/job_manager`.
- [x] `W01.P02.S06` - Gate historical search admission before GPU-lock acquisition; `src/vaultspec_rag/search/_searcher.py`.

### Phase `W01.P03` - Historical pause and resume surface

Record the original route and CLI surface only; W03 upgrades it to acknowledged quiescence and truthful failure states.

- [x] `W01.P03.S07` - Add the original service pause and resume route behavior; `src/vaultspec_rag/server/_routes.py`.
- [x] `W01.P03.S08` - Add the original server pause and resume CLI verbs; `src/vaultspec_rag/cli/_service_quiesce.py`.
- [x] `W01.P03.S09` - Add the original pause and resume CLI envelope guards; `src/vaultspec_rag/tests/test_service_quiesce_cli.py`.

## Wave `W02` - Build acknowledged resource quiescence

Replace the shared hold gate with a registry-owned controller that drains cooperative work and releases GPU residency before asserting a safe handoff. W03 depends on its stable state vocabulary.

### Phase `W02.P04` - Controller and registry GPU residency

Establish the one stateful quiesce authority, its admission epochs and drain evidence, and reversible GPU-stack release and rebuild without closing stores.

- [x] `W02.P04.S10` - Create the serialized resource-quiesce controller with state transitions, epoch-scoped compute tickets, bounded drain acknowledgement and truthful safety snapshots; `src/vaultspec_rag/service_quiesce.py`.
- [x] `W02.P04.S11` - Keep warming admission closed through durable same-ID recovery preparation, open the new epoch only for prepared or no-work, and preserve exhaustive durable, unpublished, and published-not-durable typed evidence; `src/vaultspec_rag/service.py`.
- [x] `W02.P04.S12` - Prove with real threads, real manager persistence, and a bound runner that recovery is durable before admission and execution, repaired concurrent retries coalesce, failure stays closed, and one dispatch claim starts one attempt; `src/vaultspec_rag/tests/test_service_registry_recovery.py`.

### Phase `W02.P05` - Cooperative job and search drain

Make global quiesce unwind managed attempts and drain search work without letting token-local cancellation or protected mutations corrupt controller state.

- [x] `W02.P05.S13` - Separate token-local cancellation and shutdown from global resource-quiesce signalling while preserving protected checkpoint semantics; `src/vaultspec_rag/job_control.py`.
- [x] `W02.P05.S14` - Prepare durable same-ID recovery across paused and queued desired-running jobs, preserve operator intent, and return exhaustive typed durable, unpublished, or published-not-durable persistence evidence; `src/vaultspec_rag/job_manager`.
- [x] `W02.P05.S15` - Guard index streaming safe boundaries so quiesce observations remain outside GPU locks and indivisible storage mutations; `src/vaultspec_rag/indexer/_streaming.py`.
- [x] `W02.P05.S16` - Translate controller-closed search admission into the canonical retryable HTTP 503 response before project or GPU ownership; `src/vaultspec_rag/server/_routes_search.py`.
- [x] `W02.P05.S17` - Prove real unpublished-write retry, durable queued restart recovery, and atomic exact-attempt dispatch-token coalescing across concurrent and loopless callbacks without duplicate attempts or dispatch; `src/vaultspec_rag/tests/test_job_manager_quiesce.py`.
- [x] `W02.P05.S18` - Prove closed search admission returns the canonical structured HTTP 503 while retaining no project, model, reranker, or CUDA state; `src/vaultspec_rag/tests/test_search_quiesce_admission.py`.

## Wave `W03` - Publish truthful lifecycle status

Expose controller-achieved states through routes and adapters while refusing unsafe local fallback or partial acknowledgement. W04 relies on these routes for lease orchestration but W03 neither implements nor assumes borrower authority. W03 acceptance is CPU-only and explicit: the authenticated real-filesystem failure and repaired-retry route module, service-state and jobs projection tests, transport and CLI rendering tests, fallback-refusal tests, MCP and TUI adapter tests, fresh-interpreter assertions that service paths leave torch absent, ruff check src tools, ty check, and the configured strict basedpyright gate. Every negative guard is proven red then green without mocks, fakes, stubs, patches, monkeypatches, skip, or xfail. No service process, RAG endpoint, CUDA allocation, GPU test, or W04 implementation belongs to this wave.

### Phase `W03.P06` - Authoritative routes and service state

Make authenticated pause and resume return HTTP 200 whenever the service answers, with one body shape: ok, status, and quiesce. Every unachieved service-owned lifecycle result also carries error equal to status, a message, and retryable set to true; achieved results omit error, message, and retryable. For resume recovery failure the exact status and error are resume_recovery_failed, retryable is true, and quiesce remains warming with admissions_open and safe_to_borrow_gpu false plus its typed failure_reason. Every health, jobs, and service-state projection must reuse QuiesceSnapshot.as_envelope without recomputation and carry exactly state, admission_epoch, admissions_open, active_compute_tickets, drain_complete, vram_released, safe_to_borrow_gpu, pause_requested_at, drain_acknowledged_at, quiesced_at, warming_started_at, and failure_reason.

- [ ] `W03.P06.S19` - Map typed resume recovery failure to the canonical authenticated retryable lifecycle envelope while warming admission remains closed, and return a repaired retry as running without changing the logical job identity; `src/vaultspec_rag/server/_routes.py`.
- [ ] `W03.P06.S20` - Publish the canonical quiesce block through existing health, jobs, and lifecycle heartbeat cadence without adding a poller, duplicating controller computation, or importing GPU dependencies; `src/vaultspec_rag/server/_lifespan.py, src/vaultspec_rag/server/_routes.py`.
- [ ] `W03.P06.S21` - Add the exact canonical quiesce block to read-only service-state output by projecting the registry controller snapshot once; `src/vaultspec_rag/api.py`.
- [ ] `W03.P06.S22` - Prove through the authenticated production routes, real registry, real manager writer, and real filesystem that an unpublished resume write returns resume_recovery_failed in closed warming, then directory repair and a second resume return running with the same logical job ID and one recovered generation; `src/vaultspec_rag/tests/test_service_quiesce_routes.py`.

### Phase `W03.P07` - Adapter visibility and fallback refusal

Treat the service-owned lifecycle and service-state payloads as authoritative data. Transports pass them through unchanged; CLI, MCP, and TUI render the same canonical quiesce block and never infer borrower permission. Only ok true with the requested achieved state is success. W03 has no borrower-lease verifier, so an unreachable, incompatible, uncertain, pausing, warming, failed, or otherwise unverified service is a hard refusal for local GPU indexing; --allow-fallback is not authorization and cannot start local compute before W04.

- [ ] `W03.P07.S23` - Pass quiesce transition and service-state payloads through the single service-client transport unchanged, including retryable recovery failure, without local GPU behavior; `src/vaultspec_rag/serviceclient/_transport.py`.
- [ ] `W03.P07.S24` - Render pause and resume as success only when ok is true and the canonical quiesce block carries the requested achieved state, preserving exact unsafe status, error, retryable, message, and quiesce evidence in human and JSON failures; `src/vaultspec_rag/cli/_service_quiesce.py`.
- [ ] `W03.P07.S25` - Hard-refuse in-process GPU indexing whenever delegation does not succeed and render truthful human and JSON remediation, because neither --allow-fallback nor a quiesced service block authorizes local compute until verified borrower-lease evidence exists; `src/vaultspec_rag/cli/_index.py, src/vaultspec_rag/cli/_render.py, src/vaultspec_rag/tests/test_cli_index_fallback_refusal.py`.
- [ ] `W03.P07.S26` - Expose the service-owned quiesce block through existing MCP service-state delegation without adding public lifecycle mutation tools; `src/vaultspec_rag/mcp/_tools.py`.
- [ ] `W03.P07.S27` - Render controller state, GPU release evidence and borrower safety in the jobs TUI header and status details; `src/vaultspec_rag/cli/_jobs_tui.py`.
- [ ] `W03.P07.S28` - Prove CLI, MCP and TUI adapters preserve one controller vocabulary and never initialize torch on service paths; `src/vaultspec_rag/tests/test_service_quiesce_adapters.py`.

## Wave `W04` - Authorize external GPU borrowing

Require a distinct machine-global borrower lease plus acknowledged service quiescence across every local and CI GPU entry point. Device load and free-capacity readings remain torch-free diagnostics only and can never authorize GPU work.

### Phase `W04.P08` - Borrower lease and transition orchestration

Create the distinct machine-global borrower lease and one crash-safe coordinator that acquires the lease before requesting pause, admits work only from a strict acknowledged-quiescence snapshot, resumes before release, and never starts another service.

- [ ] `W04.P08.S29` - Implement a distinct machine-global GPU borrower lease with exact typed ownership, nonblocking refusal, and OS-backed crash release without touching the service identity lock; `src/vaultspec_rag/gpu_borrow_lease.py`.
- [ ] `W04.P08.S30` - Orchestrate borrower lease acquisition, acknowledged pause, child GPU work, guaranteed resume, and lease release without starting another service; `src/vaultspec_rag/cli/_gpu_lease.py`.
- [ ] `W04.P08.S31` - Make service preflight a torch-free diagnostic over a strict typed quiescence snapshot that reports capacity but never authorizes GPU work and fails closed on unreachable, missing, unknown, stale, or version-skewed evidence; `src/vaultspec_rag/cli/_service_preflight.py`.

### Phase `W04.P09` - Torch-free diagnostics and GPU entry-point enforcement

Keep service diagnostics torch-free and strictly typed, fail closed on missing, unknown, stale, or version-skewed quiescence evidence, and require the same borrower lease plus acknowledged quiescence in pytest and self-hosted CI.

- [ ] `W04.P09.S32` - Require selected GPU pytest lanes to hold the borrower lease and acknowledged quiescence for the session lifetime, with guaranteed resume and release and no capacity-only authorization; `conftest.py`.
- [ ] `W04.P09.S33` - Wrap the self-hosted GPU tier in borrower orchestration that holds the lease and acknowledged quiescence throughout, fails closed on unsafe or skewed service state, and always resumes and releases; `.github/workflows/ci.yml`.

## Parallelization

Waves are ordered: W02 establishes the controller contract, W03 adapts all public surfaces to it, and W04 relies on both for safe borrowing. Within W02, P04 precedes P05; after the controller interface is fixed, the service residency implementation and its controller tests may proceed alongside the job/search drain lane. Within W03, P06 precedes P07 because adapters consume the route vocabulary. Within W04, P08 precedes P09. Independent test Steps may begin with their owned production Step, but each guard must be proven red then green without leaving a mutation on disk.

## Verification

The plan is complete only when every open Step is checked and code review confirms these acceptance criteria:

- `POST /pause` and `server pause` succeed only after admission closure, pre-pause ticket drain, managed-resource release, GPU-stack detachment, allocator release, and `safe_to_borrow_gpu: true`; every other state is a non-success.
- `POST /resume` and `server resume` succeed only after GPU rebuild and a new admission epoch open; failed warmup stays closed and names the failure.
- Cancelling or shutting down one attempt cannot disable a future global quiesce; no global wait occurs inside a GPU lock, protected mutation, or store write.
- Quiesced jobs preserve logical identity and desired running intent while releasing limiter, project lease, writer, worker and pipeline ownership; searches drain or receive a retryable quiescing outcome without retaining a model reference.
- Health, service-state, jobs, CLI, MCP service-state, and TUI expose the same controller vocabulary; public MCP retains no lifecycle mutation and no adapter falls back to local GPU work.
- A borrower lease is distinct from the machine service lock, auto-releases on borrower death, and local fallback or GPU-live test entry refuses unless lease and safe service conditions are proven.
- Required non-GPU gates are focused unit and integration tests for the listed files, fresh-interpreter torch-import guards, `uv run --no-sync ruff check src tools`, `ty check`, and the configured strict type check. Full GPU-live release proof is explicitly unrun and requires a separately authorized maintenance window.
