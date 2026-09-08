---
tags:
  - '#plan'
  - '#search-readiness-contract'
date: '2026-09-08'
tier: L3
related:
  - '[[2026-09-08-search-readiness-contract-adr]]'
  - '[[2026-09-08-search-readiness-contract-research]]'
  - '[[2026-09-08-search-readiness-contract-reference]]'
modified: '2026-09-08'
body_schema: body-v2
body_hash: 'sha256:3dec6407d1ef32ae05ee2b30c129b69f7ed68f2f131e4c25ae97441ed6f93292'
---

<!-- RETIRED: P14 -->

# `search-readiness-contract` plan

Implement the accepted canonical search-readiness contract from service state through every
adapter, with bounded publication waits and causal backpressure reporting.

## Description

The authorizing ADR governs every Wave. W01 establishes typed per-source state and publication
convergence. W02 applies it to service requests, HTTP, combined search, and wait attribution. W03
preserves the envelope through the client, CLI, and MCP. W04 supplies cross-surface, cancellation,
concurrency, load, documentation, and formal-review proof. Retrieval, ranking, GPU lock scope, and
immediate-mode serialization remain unchanged.

## Steps

## Wave `W01` - canonical state and convergence authority

Deliver the immutable vocabulary, source classification, aggregation, and publication-aware notification primitive required by all later Waves.

### Phase `W01.P01` - define the closed readiness model

Define and validate the immutable source and aggregate contract.

- [x] `W01.P01.S01` - Define typed availability freshness authority wait policy generation evidence source fact and aggregate serialization; `src/vaultspec_rag/_search_state.py`.
- [x] `W01.P01.S02` - Prove model validation rejects contradictions malformed identities negative timing and unbounded evidence; `src/vaultspec_rag/tests/test_search_availability.py`.
- [x] `W01.P01.S03` - Mutation-prove the model validation bound and authority contradiction guards; `src/vaultspec_rag/tests/test_search_availability.py`.

### Phase `W01.P02` - classify canonical source evidence

Project existing job generation controller integrity and collection facts through one service authority.

- [x] `W01.P02.S04` - Replace the empty-only classifier with per-source projection from canonical job generation controller integrity and collection evidence; `src/vaultspec_rag/server/_search_availability.py`.
- [x] `W01.P02.S05` - Project generation summary requested and effective mode controller resilience and revision evidence without a second authority; `src/vaultspec_rag/jobs.py`.
- [x] `W01.P02.S06` - Add explicit rebuild-required evidence and cover current updating unavailable unverifiable rebuild capacity authority and bounded scenarios; `src/vaultspec_rag/server/_search_availability.py and src/vaultspec_rag/tests/test_search_availability.py`.
- [x] `W01.P02.S07` - Mutation-prove exact source and root matching plus bounded evidence; `src/vaultspec_rag/tests/test_search_availability.py`.

### Phase `W01.P03` - add revision-based convergence

Wait for publication revisions under a monotonic cancellable bound instead of treating job termination as freshness.

- [x] `W01.P03.S08` - Implement a service-owned readiness revision registry and cancellable monotonic publication waiter; `src/vaultspec_rag/server/_search_readiness.py`.
- [x] `W01.P03.S09` - Own the readiness registry lifecycle and inject one registry-allocated revision emission after canonical code publication succeeds; `src/vaultspec_rag/server/_search_readiness.py, src/vaultspec_rag/service.py, src/vaultspec_rag/server/_lifespan.py, src/vaultspec_rag/indexer/_codebase_indexer.py, and src/vaultspec_rag/indexer/_generation_lifecycle.py`.
- [x] `W01.P03.S10` - Inject one registry-allocated readiness revision after each canonical document generation publication succeeds; `src/vaultspec_rag/indexer/_document_indexer.py, src/vaultspec_rag/service.py, and src/vaultspec_rag/server/_search_readiness.py`.
- [x] `W01.P03.S11` - Emit controller-only readiness notifications after canonical desired-state persistence without advancing publication; `src/vaultspec_rag/job_manager/_control.py, src/vaultspec_rag/job_manager/manager.py, src/vaultspec_rag/job_manager/state.py, src/vaultspec_rag/service.py, and src/vaultspec_rag/server/_search_readiness.py`.
- [x] `W01.P03.S12` - Prove immediate bypass notification wake monotonic timeout cancellation cleanup and multi-source convergence with a virtual clock; `src/vaultspec_rag/tests/test_search_readiness.py`.
- [x] `W01.P03.S13` - Mutation-prove waiter cleanup and job-terminal-not-publication guards; `src/vaultspec_rag/tests/test_search_readiness.py`.

## Wave `W02` - service request response and combined semantics

Build on W01 to deliver caller policy, bounded waiting, HTTP envelopes, combined aggregation, and service-owned wait attribution.

### Phase `W02.P04` - accept and enforce caller policy

Validate immediate and bounded policies capture stable targets and preserve cancellation.

- [x] `W02.P04.S14` - Add immediate-default and bounded request policy capture stable source targets enforce maximum wait and preserve cancellation; `src/vaultspec_rag/server/_routes_search.py`.
- [x] `W02.P04.S15` - Add the bounded freshness-wait maximum to canonical configuration and settings projection; `src/vaultspec_rag/config`.
- [x] `W02.P04.S16` - Prove policy defaults validation stable targets typed timeout and disconnect behavior; `src/vaultspec_rag/tests/test_http_search_routing.py`.
- [x] `W02.P04.S17` - Prove freshness-wait configuration defaults overrides and upper-bound validation; `src/vaultspec_rag/tests/test_config.py`.

### Phase `W02.P05` - shape canonical success and failure envelopes

Map canonical source facts into truthful result status header and retry behavior.

- [x] `W02.P05.S18` - Attach per-source facts and aggregate to success and require authoritative absence for empty success; `src/vaultspec_rag/server/_routes_search.py`.
- [x] `W02.P05.S19` - Map typed failure status and emit Retry-After only from a canonical future deadline; `src/vaultspec_rag/server/_routes_search.py`.
- [x] `W02.P05.S20` - Replace legacy availability envelopes with canonical code retry wait evidence and remediation; `src/vaultspec_rag/server/_search_availability.py`.
- [x] `W02.P05.S21` - Cover stable failures updating success empty authority result suppression status and header truthfulness; `src/vaultspec_rag/tests/test_http_search_errors.py`.
- [x] `W02.P05.S22` - Mutation-prove empty authority and Retry-After guards; `src/vaultspec_rag/tests/test_http_search_errors.py`.

### Phase `W02.P06` - preserve every combined constituent

Aggregate per-source facts without erasing useful results degradation or authority gaps.

- [x] `W02.P06.S23` - Extend domain outcomes with immutable source readiness and derive a lossless combined aggregate; `src/vaultspec_rag/search/_outcomes.py`.
- [x] `W02.P06.S24` - Classify every requested source and retain constituent failures beside useful combined results; `src/vaultspec_rag/_public_search.py`.
- [x] `W02.P06.S25` - Carry per-domain facts through route dispatch and require all-source authority for empty aggregate; `src/vaultspec_rag/server/_routes_search.py`.
- [x] `W02.P06.S26` - Prove partial degraded failed authoritative-empty non-authoritative-empty and omitted-domain combined outcomes; `src/vaultspec_rag/tests/test_search_outcomes.py`.
- [ ] `W02.P06.S27` - Prove combined HTTP no longer bypasses classification or hides constituent failure; `src/vaultspec_rag/tests/test_http_search_errors.py`.

### Phase `W02.P07` - attribute service-owned waits

Measure every existing admission and capacity boundary under its actual canonical cause.

- [x] `W02.P07.S28` - Record admission before blocking and expose bounded queued-request wait observations; `src/vaultspec_rag/server/_search_activity.py`.
- [ ] `W02.P07.S29` - Measure search-limiter and compute-ticket waits separately from service duration; `src/vaultspec_rag/server/_routes_search.py`.
- [ ] `W02.P07.S30` - Preserve GPU-compute and project-lease measurements as distinct named causes without widening lock scope; `src/vaultspec_rag/search/_searcher.py`.
- [ ] `W02.P07.S31` - Map storage duration and refusal to storage-owned outcomes without guessing index state; `src/vaultspec_rag/server/_routes_search.py`.
- [ ] `W02.P07.S32` - Prove queued visibility deadlines bounded history completion and cancellation cleanup; `src/vaultspec_rag/tests/test_search_activity.py`.
- [ ] `W02.P07.S33` - Prove every named wait cause remains distinct under contention; `src/vaultspec_rag/tests/test_service_search_diagnostics.py`.
- [ ] `W02.P07.S34` - Mutation-prove the no-new-GPU-serialization concurrency guard; `src/vaultspec_rag/tests/test_service_search_diagnostics.py`.

## Wave `W03` - client CLI and MCP conformance

Build on W02 to preserve one service envelope and render it across the client, CLI, and MCP without adapter-owned classification.

### Phase `W03.P08` - preserve the service envelope in the client

Carry policy and canonical success or failure payloads without inferred readiness.

- [ ] `W03.P08.S35` - Send caller policy and bound preserve canonical bodies and remove synthesized freshness diagnosis; `src/vaultspec_rag/serviceclient/_search_transport.py`.
- [ ] `W03.P08.S36` - Prove payload propagation envelope passthrough transport-only failures and absence of client-derived readiness; `src/vaultspec_rag/tests/test_cli_search.py`.

### Phase `W03.P09` - render CLI readiness

Expose caller policy and render canonical JSON and concise human diagnostics.

- [ ] `W03.P09.S37` - Expose freshness policy and bounded duration on search commands with immediate defaults; `src/vaultspec_rag/cli/_search.py`.
- [ ] `W03.P09.S38` - Preserve canonical JSON and render concise human readiness wait identifiers code and remediation; `src/vaultspec_rag/cli/_search.py`.
- [ ] `W03.P09.S39` - Prove JSON parity policy validation updating success typed failure wait cause and identifier bounds; `src/vaultspec_rag/tests/test_cli_search.py`.
- [ ] `W03.P09.S40` - Prove fallback and timeout safety never recreate adapter readiness diagnosis; `src/vaultspec_rag/tests/test_cli_search_safety.py`.

### Phase `W03.P10` - return structured MCP content

Preserve canonical structured success and recoverable failure content through every MCP search tool.

- [ ] `W03.P10.S41` - Extend MCP input and result models with policy and canonical readiness content; `src/vaultspec_rag/mcp/_tools.py`.
- [ ] `W03.P10.S42` - Replace opaque RuntimeError reduction with structured error content and actionable text; `src/vaultspec_rag/mcp/_tools.py`.
- [ ] `W03.P10.S43` - Prove every MCP search tool preserves structured success and failure through the official client; `src/vaultspec_rag/tests/integration/_service_search_diagnostics_mcp.py`.
- [ ] `W03.P10.S44` - Prove MCP schemas expose bounded policy consistently for every search source; `src/vaultspec_rag/tests/test_mcp_conformance_surface.py`.
- [ ] `W03.P10.S45` - Mutation-prove the MCP structured-failure preservation guard; `src/vaultspec_rag/tests/integration/_service_search_diagnostics_mcp.py`.

## Wave `W04` - end-to-end proof and performance protection

Build on W03 to deliver reusable conformance coverage, real boundary tests, explicit load evidence, documentation, and formal review.

### Phase `W04.P11` - reuse one cross-surface scenario matrix

Drive identical readiness scenarios through HTTP CLI MCP and combined search.

- [ ] `W04.P11.S46` - Define reusable current updating unavailable unverifiable rebuild timeout capacity backend empty and mixed scenarios; `src/vaultspec_rag/tests/_search_readiness_scenarios.py`.
- [ ] `W04.P11.S47` - Apply the readiness scenario matrix to real HTTP responses and headers; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_http.py`.
- [ ] `W04.P11.S48` - Apply the readiness scenario matrix to CLI JSON and human rendering; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_reporting.py`.
- [ ] `W04.P11.S49` - Apply the readiness scenario matrix to official-client MCP structured responses; `src/vaultspec_rag/tests/integration/_service_search_diagnostics_mcp.py`.
- [ ] `W04.P11.S50` - Prove rebuild-required behavior and remediation across service and adapters; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics_rebuild.py`.

### Phase `W04.P12` - enforce compatibility and load budgets

Prove immediate-mode semantics and concurrency performance remain intact.

- [ ] `W04.P12.S51` - Add immediate readiness overhead and bounded-wait contention to the concurrency benchmark; `src/vaultspec_rag/tests/benchmarks/bench_concurrency.py`.
- [ ] `W04.P12.S52` - Record accepted no-wait latency throughput limiter GPU queue and waiter-cleanup comparison output; `src/vaultspec_rag/tests/benchmarks/baselines`.
- [ ] `W04.P12.S53` - Prove immediate requests do not poll or wait and bounded waits add no global or GPU serialization; `src/vaultspec_rag/tests/test_search_readiness.py`.
- [ ] `W04.P12.S54` - Prove retrieval ordering ranking output and result shape remain unchanged; `src/vaultspec_rag/tests/integration/test_search_result_shape.py`.

### Phase `W04.P13` - run repository gates documentation and formal review

Complete explicit gates public documentation and independent review before closure.

- [ ] `W04.P13.S55` - Run focused unit integration MCP conformance concurrency guard and benchmark gates with individual exit codes; `src/vaultspec_rag/tests`.
- [ ] `W04.P13.S56` - Run repository lint format type full test vault and diff gates with individual exit codes; `repository-wide verification`.
- [ ] `W04.P13.S57` - Perform formal review for ADR service cancellation evidence retry GPU and storage conformance; `cohesive changed-file set`.
- [ ] `W04.P13.S58` - Document immediate and bounded policy states retries CLI and MCP automation examples; `docs/search-and-index.md`.

## Parallelization

Waves execute in order. In W01, P01 precedes P02; P03 begins once the model interface is stable.
In W02, policy validation and response classification may proceed together, while combined
aggregation depends on the source-fact shape; wait instrumentation can proceed beside aggregation.
In W03, transport lands before adapter conformance, after which CLI and MCP work may run in
parallel. In W04, HTTP, CLI, MCP, and benchmark applications may run in parallel after the shared
scenario matrix exists. Steps touching the same production or test file remain serial.

## Verification

- Every immediate and bounded scenario produces the same canonical facts through service-domain,
  HTTP, CLI JSON, CLI human, MCP, and combined-search surfaces.
- Virtual-clock tests prove exact timeout, publication wake, spurious-wake resistance, and prompt
  cancellation cleanup.
- Contention tests distinguish index transition, controller deferral, GPU compute, search
  admission, project lease, storage/backend, and other service capacity.
- Mutation demonstrations record the intended red assertion and restored green result for every
  guard Step.
- Focused unit, integration, conformance, concurrency, benchmark, lint, format, type, full test,
  vault, and diff gates each record their own exit code.
- The load comparison shows no new immediate-mode or GPU serialization, and formal review reports
  no unresolved blocking findings.
- The plan is complete only when all 58 Step rows are closed and the issue documentation matches
  the shipped contract.
