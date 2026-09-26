---
tags:
  - '#plan'
  - '#vault-result-evidence'
date: '2026-09-23'
tier: L2
related:
  - '[[2026-09-23-vault-result-evidence-adr]]'
  - '[[2026-06-12-service-concurrency-adr]]'
modified: '2026-09-24'
body_schema: body-v2
body_hash: 'sha256:fa6a6fb259e5029054944c046c745e77418e42fc63a438b6e619e362c64fd7ae'
---

# `vault-result-evidence` plan

## Description

Approved 2026-09-23. Basis: the user approved the ADR and this plan in full, P05
included, after they were presented in conversation.

**Added scope, 2026-09-23.** The user authorized P05a, P05b and P05c in conversation
after the plan-close review:

- Every defect the review and the full lane identified is in scope, and no pull request
  opens while a known defect remains (P05a).
- The P05 result, that the section breadcrumb hurt ranking, must be assessed carefully
  before it stands, because format and section changed together (P05b).
- The latency target is indicative. The measured 0.71 s median is acceptable, but the
  miss points at unexplored optimization, which is in scope (P05c). Latency depends on
  the host, so no test gates it.

Make vault search results answerable and locatable, and cut vault search latency, per
GitHub issue #531.

**Governing decisions.**

- `2026-09-23-vault-result-evidence-adr` (accepted) governs every Phase and grounds in
  `2026-09-23-vault-result-evidence-research`.
- `2026-06-12-service-concurrency-adr` (accepted) is completed by this plan:
  - Its D7 (snippet from the matched passage) is delivered by P03 and P04.
  - Its D8 (heading-path vault embedding input) is delivered by P05, only if the gate
    shows no ranking regression. Otherwise P05 records an amendment instead of shipping
    the change.

**Coverage.** The storage-schema and explicit-reindex decisions apply unchanged:
additive payload fields do not bump the storage schema, and the vault rebuild surfaces
as the typed `full_reindex_required` refusal. No other costly decision is involved.

**Out of scope.** Chunk-size or packing changes, MaxP ranking, and document-collection
passages are deferred by the ADR.

## Steps

### Phase `P01` - build the evidence evaluation instrument

Delivers a blind-labelled evidence query set over the frozen vault and a quality gate for ranking, evidence-in-snippet, section match and verbatim spans, with today's behaviour measured as the baseline.

- [x] `P01.S01` - author a blind evidence-labelled query set (query, gold record, gold section, verbatim evidence) from the frozen vault without viewing search output; `src/vaultspec_rag/tests/quality/evidence_queries.toml`.
- [x] `P01.S02` - add the evidence quality gate measuring hit@1, MRR, evidence-in-snippet, section match and the verbatim-span invariant, and record the pre-change measurement; `src/vaultspec_rag/tests/integration/test_vault_evidence_gate.py, src/vaultspec_rag/tests/quality/`.

### Phase `P02` - run the reranker in fp16 from one constructor

Delivers one CrossEncoder constructor loading fp16 for the service and the searcher fallback, one shared predict path, and a measured latency drop.

- [x] `P02.S03` - collapse the two CrossEncoder construction sites into one fp16 constructor and share the out-of-memory predict backoff; `src/vaultspec_rag/service.py, src/vaultspec_rag/search/_searcher.py`.

### Phase `P03` - store passages and locators on vault chunks

Delivers index-time structural passages and chunk locators in the vault payload, a point-schema bump, and the typed rebuild refusal for vault indexes built before it.

- [x] `P03.S04` - add the torch-free markdown passage module (fence and heading aware, 1200-character bound, file line spans, section breadcrumbs) with unit tests; `src/vaultspec_rag/_markdown_passages.py (new, package root so indexing and search share it), src/vaultspec_rag/tests/test_markdown_passages.py (new)`.
- [x] `P03.S05` - attach line spans, section and clipped passages to vault chunks and payloads, bump the vault point schema, and convert the vault ledger incompatibility to full_reindex_required; `src/vaultspec_rag/indexer/_vault_prep.py, src/vaultspec_rag/_store_models.py, src/vaultspec_rag/store_schema.py, src/vaultspec_rag/indexer/_index_schema.py, src/vaultspec_rag/indexer/_vault_indexer.py`.

### Phase `P04` - select snippets by query and expose the locator

Delivers the query-selected passage snippet over each final vault result's top two chunks, the section field, and every output surface rendering them consistently.

- [x] `P04.S06` - keep each record's runner-up chunk through grouping and select the best passage per final vault result with one batched forward; `src/vaultspec_rag/search/_searcher.py, src/vaultspec_rag/search/_result_shaping.py, src/vaultspec_rag/search/_models.py, gate section metric in src/vaultspec_rag/tests/integration/`.
- [x] `P04.S07` - carry section and passage spans through the result contract with CLI and MCP parity: one wire serializer for the route and in-process CLI, CLI rendering, MCP descriptions, docs, shared canonical scenarios, and a live CLI-versus-MCP parity test; `src/vaultspec_rag/server/_models.py, src/vaultspec_rag/server/_routes_search.py, src/vaultspec_rag/cli/_search.py, src/vaultspec_rag/cli/_render.py, src/vaultspec_rag/mcp/_tools.py, docs/, src/vaultspec_rag/tests/`.

### Phase `P05` - complete the heading-path embedding input under the gate

Delivers the title, section and chunk-text vault embedding input from one function, donor verification against that input, and a gate comparison against the fp16 baseline that decides whether it ships.

- [x] `P05.S08` - build the vault embedding input in one function with the section breadcrumb, verify donors against the full input, and measure it on the gate against the fp16 baseline; `src/vaultspec_rag/indexer/_streaming.py, src/vaultspec_rag/indexer/_reuse.py, src/vaultspec_rag/indexer/_slicing.py`.

### Phase `P05a` - clear the known defects before review

Delivers a branch with no known defect: the strict type gate and the child-output decoding guard green, the rebuild remedy named at the service level, and the install-mode doctor agreeing with the MCP launch shape.

- [x] `P05a.S10` - clear the strict type gate and the child-output decoding guard, fold the compute probe onto the shared MiB conversion, and make the degraded-verdict guards assert the typed failed-job reason; `src/vaultspec_rag/operator_state/, src/vaultspec_rag/api.py, src/vaultspec_rag/cli/_jobs_tui_header.py, src/vaultspec_rag/cli/_jobs_tui_constants.py, src/vaultspec_rag/cli/_status.py, src/vaultspec_rag/serviceclient/_typed_state.py, src/vaultspec_rag/tests/`.
- [x] `P05a.S11` - carry the failed job's source into service health and name the per-source rebuild command when the failure is full_reindex_required; `src/vaultspec_rag/server/_lifespan.py, src/vaultspec_rag/cli/_status_labels.py, src/vaultspec_rag/tests/`.
- [x] `P05a.S12` - reconcile the install-mode doctor verdict with the project's MCP launch shape; `src/vaultspec_rag/operator_state/, src/vaultspec_rag/tests/`.
- [x] `P05a.S16` - resolve the close review of P05a-P05c: scope the service rebuild remedy and failure supersession to the failed job's project, make half accumulation a no-op on torch without the switch, and correct the ADR splice, docstring and comment; `src/vaultspec_rag/server/_lifespan.py, src/vaultspec_rag/server/_routes_jobs.py, src/vaultspec_rag/cli/_status_labels.py, src/vaultspec_rag/_operator_commands.py, src/vaultspec_rag/_gpu.py, src/vaultspec_rag/indexer/_slicing.py, src/vaultspec_rag/cli/_jobs_tui_constants.py, src/vaultspec_rag/tests/`.
- [x] `P05a.S17` - read the run ledger's schema state from one snapshot so concurrent fresh openers never demand a needless rebuild; `src/vaultspec_rag/indexer/_run_ledger_runtime.py`.

### Phase `P05b` - reassess the section in the vault embedding input

Delivers a controlled comparison that separates the embedding-input format from the section breadcrumb, on the in-repo gates and the issue's query sets, and ships or records the result on that evidence.

- [x] `P05b.S13` - measure the shipped embedding input against format-only, section-in-shipped-format and the originally tested input on the in-repo gates and the issue's query sets, per query; `src/vaultspec_rag/indexer/_slicing.py (variants measured in scratch, not committed)`.
- [x] `P05b.S14` - ship the input the controlled evidence favours, or revise the audit and the D8 amendment to the controlled result; `src/vaultspec_rag/indexer/_slicing.py, .vault/audit/2026-09-23-vault-result-evidence-audit.md, .vault/adr/2026-06-12-service-concurrency-adr.md`.

### Phase `P05c` - reduce vault search inference time

Delivers a profiled vault search path and every inference lever that cuts its time while holding the quality gates; latency is measured and reported as indicative, never gated.

- [x] `P05c.S15` - profile vault search end to end and apply each inference lever that cuts time while holding the quality gates: attention kernel, compilation, tokenisation, candidate window, and score reuse; `src/vaultspec_rag/search/, src/vaultspec_rag/embeddings.py, src/vaultspec_rag/service.py`.

### Phase `P06` - calibrate the gate and close

Delivers calibrated gate floors, the cross-corpus re-run of the issue's query sets, the latency check, and the closing review.

- [x] `P06.S09` - record gate floors from the passing run, re-run the issue's query sets and the latency measurement, and file the results in the feature audit; `src/vaultspec_rag/tests/quality/evidence_baseline.json`.
- [x] `P06.S18` - clear the full-lint findings from the first CI run: complexity of the block scan and passage selection, the searcher's module length, and markdown formatting of the feature's records; `src/vaultspec_rag/_markdown_passages.py, src/vaultspec_rag/search/_searcher.py, src/vaultspec_rag/search/_result_shaping.py, src/vaultspec_rag/_gpu.py, .vault/`.

## Parallelization

- **P01 goes first.** Its gate must measure today's behaviour before anything changes.
  S01's blind authoring can run as a dispatched worker in parallel with P02 and S04,
  because it touches only the new query file and must not see search output.
- **P02 and S04 are independent** of each other and may run in parallel.
- **The rest is ordered.**
  - S05 needs S04.
  - P04 needs S05.
  - P05 needs P04, because it measures against the fp16 and passage baseline.
  - P06 runs last.
- **Shared files.** P02 and P04 both edit `src/vaultspec_rag/search/_searcher.py`.
  Serialize their commits.

## Verification

- **Gate.** The evidence gate passes on the frozen corpus:
  - Every vault hit's snippet occurs verbatim in its file at the reported line span.
  - Evidence-in-snippet and section-match rates meet the recorded floors and exceed the
    P01 pre-change measurement.
  - Gold-record hit@1 and MRR do not fall below the P01 measurement.
- **fp16.** The existing intent-ranking and testimonial quality gates still pass.
- **Cross-corpus.** The issue's two query sets, re-run against the vaultspec-core vault,
  show evidence-in-snippet above 0/21 and 1/18, with no hit@1 or MRR loss. Results are
  recorded in the feature audit.
- **Latency.** Server-side vault search time at ten results, passage scoring included,
  is measured on the same host and corpus as the fp32 baseline and reported in the
  feature audit. Half the fp32 baseline is the indicative target; it is not a test gate,
  because the figure depends on the host.
- **Migration.** A vault index built before the point-schema bump reports
  `full_reindex_required` with the rebuild command, and keeps serving until rebuilt.
- **Hygiene.** Lint, format, type-check and the touched unit and integration tests pass
  on each Step.
- **Review.** Phase-close reviews and the final integrated review pass. All Steps are
  closed.
