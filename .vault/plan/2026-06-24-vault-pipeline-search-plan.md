---
tags:
  - '#plan'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
tier: L3
related:
  - '[[2026-06-24-vault-pipeline-search-adr]]'
---

# `vault-pipeline-search` plan

## Wave `W01` - Validation instrument and baseline

Build the intent-aware graded-relevance instrument (ADR D8) and capture a baseline on the current ranking before any ranking change lands; every downstream Wave is measured against this baseline.

### Phase `W01.P01` - Rubric and labeled query set

Author the graded-relevance rubric and the intent-tagged labeled query set as committed data, and enrich the synthetic corpus to express status and pipeline role.

- [x] `W01.P01.S01` - Author the graded-relevance rubric table keyed on intent x doc_type x status; `src/vaultspec_rag/tests/quality/rubric.py`.
- [x] `W01.P01.S02` - Author the intent-tagged labeled query set with hand-graded gold judgments; `src/vaultspec_rag/tests/quality/intent_queries.toml`.
- [x] `W01.P01.S03` - Enrich the synthetic corpus generator with status markers and pipeline-role edges; `src/vaultspec_rag/synthetic.py`.

### Phase `W01.P02` - Metrics, harness, and baseline

Implement the role-aware metrics and the quality-marked integration harness, then capture and commit the baseline on the current ranking.

- [x] `W01.P02.S04` - Implement role-aware NDCG, Authoritative-at-k, MRR, and role-precision metrics; `src/vaultspec_rag/tests/quality/metrics.py`.
- [x] `W01.P02.S05` - Add the quality-marked integration harness driving a real index against the gold set; `src/vaultspec_rag/tests/integration/test_intent_ranking.py`.
- [x] `W01.P02.S06` - Capture and commit the baseline ranking report on the current reranker; `src/vaultspec_rag/tests/quality/baseline.json`.

## Wave `W02` - Status and result data layer

Surface document status and related-document edges end-to-end (ADR D5, D7): extract status from the ADR H1, carry status and related on the result and payload, and reindex. Depends on W01 for its regression gate; required by W03 for the status-aware prior.

### Phase `W02.P03` - Status extraction and payload

Parse status from the H1, clean the title, carry status and related through the document, chunk, payload, and result, then reindex and regression-test.

- [x] `W02.P03.S07` - Parse status from the ADR H1 and strip the status suffix from the displayed title; `src/vaultspec_rag/indexer/_vault_prep.py`.
- [x] `W02.P03.S08` - Carry status on VaultDocument and VaultChunk and write it to the Qdrant payload; `src/vaultspec_rag/store.py`.
- [x] `W02.P03.S09` - Add related and status fields to SearchResult; `src/vaultspec_rag/search/_models.py`.
- [x] `W02.P03.S10` - Map related and status from Qdrant rows in the vault search path; `src/vaultspec_rag/search/_searcher.py`.
- [x] `W02.P03.S11` - Reindex and regression-test that status and related are present on results; `src/vaultspec_rag/tests/integration/test_vault_payload_fields.py`.

## Wave `W03` - Intent-conditioned ranking prior

Compose the multiplicative per-(type x status) ranking prior with config weight profiles and a per-type cap (ADR D2, D3, D4), tuned against the W01 instrument. Depends on W02 for the status field; required by W04 for intent selection.

### Phase `W03.P04` - Config weight profiles

Add the orientation and debug intent weight profiles (per-type and per-status multipliers) and the per-type cap as inspectable configuration.

- [x] `W03.P04.S12` - Add orientation and debug intent weight profiles and the per-type cap to config; `src/vaultspec_rag/config.py`.

### Phase `W03.P05` - Prior composition and tuning

Implement and compose the multiplicative type x status reweight and per-type cap post-rerank, then tune the weights against the W01 instrument and record the improvement.

- [x] `W03.P05.S13` - Implement the multiplicative per-(type x status) reweight function; `src/vaultspec_rag/search/_intent_rank.py`.
- [x] `W03.P05.S14` - Compose the intent prior post-rerank and select the active profile in vault search; `src/vaultspec_rag/search/_searcher.py`.
- [x] `W03.P05.S15` - Implement the per-type result cap to prevent one type crowding the top-k; `src/vaultspec_rag/search/_intent_rank.py`.
- [x] `W03.P05.S16` - Tune the weight profiles against the gold set and record the improvement over baseline; `src/vaultspec_rag/tests/quality/baseline.json`.

## Wave `W04` - Search surface and result rendering

Expose the explicit intent mode, doc-type union, and status control across CLI, HTTP route, and MCP, and render frontmatter-enriched results (ADR D1, D6, D7). Depends on W03 for the ranking behavior it surfaces.

### Phase `W04.P06` - Intent, doc-type union, and status surface

Add the explicit intent flag, doc-type union selection, and status control, threaded consistently across CLI, HTTP route, searcher, and MCP.

- [x] `W04.P06.S17` - Add the explicit --intent orientation or debug flag and its validation; `src/vaultspec_rag/cli/_search.py`.
- [x] `W04.P06.S18` - Add doc-type union selection with audit included and index excluded; `src/vaultspec_rag/search/_validation.py`.
- [x] `W04.P06.S19` - Add the --status control with the default active set and opt-in widening; `src/vaultspec_rag/cli/_search.py`.
- [x] `W04.P06.S20` - Thread intent, status, and doc-type-union params through the HTTP search client; `src/vaultspec_rag/cli/_http_search.py`.
- [x] `W04.P06.S21` - Accept and validate the new search params in the server route; `src/vaultspec_rag/server/_routes.py`.
- [x] `W04.P06.S22` - Thread the new params into the searcher entry points and apply them; `src/vaultspec_rag/search/_searcher.py`.
- [x] `W04.P06.S23` - Mirror the new params on the MCP search_vault tool for adapter parity; `src/vaultspec_rag/mcp/_tools.py`.

### Phase `W04.P07` - Frontmatter-enriched result rendering

Render the feature, status, date, doc-type, and related edges on each vault hit in human and JSON output, with tests.

- [x] `W04.P07.S24` - Render the frontmatter metadata line with doc_type, feature, status, date, related; `src/vaultspec_rag/cli/_render.py`.
- [x] `W04.P07.S25` - Add human and JSON result-shape tests for the enriched fields; `src/vaultspec_rag/tests/integration/test_search_result_shape.py`.

## Wave `W05` - Production CLI cleanup and acceptance

Remove dev-only quality/benchmark verbs from the production CLI as a discrete breaking change (ADR D9) and run the full acceptance gate: graded metrics, persona testimonials, and the A/B delta report. Depends on all prior Waves.

### Phase `W05.P08` - Production CLI cleanup

Remove the dev-only quality and benchmark verbs from the production command group, relocate their capability under the test tree, and regenerate the bundled CLI reference.

- [x] `W05.P08.S26` - Remove the quality and benchmark verbs from the production CLI command group; `src/vaultspec_rag/cli/_app.py`.
- [x] `W05.P08.S27` - Relocate run_quality_probe and run_benchmark capability under the test tree; `src/vaultspec_rag/api.py`.
- [x] `W05.P08.S28` - Regenerate the bundled CLI reference for the removed verbs; `reference/cli.md`.

### Phase `W05.P09` - Acceptance and testimonials

Run the persona testimonials and the full acceptance gate, producing the A/B delta report that proves the rework against the baseline.

- [x] `W05.P09.S29` - Add the per-intent persona ranking-testimonial integration test; `src/vaultspec_rag/tests/integration/test_ranking_testimonial.py`.
- [x] `W05.P09.S30` - Run the full acceptance gate and produce the A/B delta report; `src/vaultspec_rag/tests/quality/ab_report.md`.

## Wave `W06` - Live persona validation

Validate the shipped ranking against the real, existing project vault through live agent-persona searches, capturing qualitative testimonials as an audit. Depends on all prior Waves; this is the human-credible gate complementing the automated suite.

### Phase `W06.P10` - Live testimonials

Reindex the real vault on the new code, run orientation and debugging persona searches against the live service, and persist the verdicts.

- [x] `W06.P10.S31` - Reindex the real vault on the new code and capture orientation persona live-search testimonials; `.vault/audit/2026-06-24-vault-pipeline-search-live-testimonials-audit.md`.
- [x] `W06.P10.S32` - Capture debugging persona live-search testimonials and the consolidated verdict; `.vault/audit/2026-06-24-vault-pipeline-search-live-testimonials-audit.md`.

## Description

This plan implements the accepted decisions D1 through D9 of the vault-pipeline-search ADR:
making vault semantic search intent-aware so results mirror the vaultspec pipeline
hierarchy instead of ranking every document on flat topical relevance. The work is grounded
in the sibling research, which reproduced the core failure live (an execution step record
out-ranking the accepted ADR it implements for an orientation query).

The sequencing is deliberately instrument-first. Wave W01 builds the graded-relevance
validation instrument and captures a baseline on the current ranking, because the intent
prior is a tuning surface whose correctness is only knowable through measurement, and a
baseline captured after the change would be worthless. Wave W02 surfaces document status
(parsed from the ADR H1) and the already-persisted related edges through the payload and
the result object, the data the prior and the enriched results both depend on. Wave W03
composes the multiplicative per-(type x status) ranking prior with config weight profiles
and a per-type cap, tuned against W01. Wave W04 exposes the explicit intent mode, doc-type
union, and status control across the CLI, HTTP route, and MCP, and renders the enriched
result frontmatter. Wave W05 removes the dev-only quality and benchmark verbs from the
production CLI as a discrete breaking change and runs the full acceptance gate.

The central technical tension, recorded in the ADR, is that the existing post-rerank
reweighters are bounded to break ties only and never override semantic relevance; the
intent prior deliberately and inspectably overrides relevance on the type x status axis
under an explicitly declared intent. All ranking and status logic lives in the search and
service domain with the CLI as a thin adapter; no GPU-lock or reranker-content rule is
disturbed because the prior composes after the forward pass.

## Steps

## Parallelization

The five Waves are strictly sequenced: each must land before the next begins. W01 produces
the baseline that gates W03's tuning; W02 produces the status field that W03's prior and
W04's rendering consume; W03 produces the ranking behavior that W04 surfaces; W05 cleans up
and gates on all prior Waves.

Within Waves, some Phases and Steps parallelize. In W01, Phase P01 (rubric, query set,
synthetic-corpus enrichment) is independent across its three Steps and must complete before
P02's harness and baseline. In W02, P03 is a hard chain: status extraction (S07) feeds the
payload write (S08), which feeds the result mapping (S09, S10), which the regression test
(S11) verifies after a reindex. In W03, the config Phase P04 (S12) precedes the composition
Phase P05; within P05 the reweight function (S13) and the per-type cap (S15) are independent
and precede the searcher composition (S14), with tuning (S16) last. In W04, the surface
Steps S17 through S23 share the searcher and validation files so they land in dependency
order (flag and validation before threading before MCP parity); the rendering Phase P07
depends on the result fields from W02 but is otherwise independent of P06. In W05, the
cleanup Phase P08 and the acceptance Phase P09 are sequential, acceptance last.

## Verification

The plan is complete when every Step is closed and all of the following hold:

- The intent-aware harness (`src/vaultspec_rag/tests/integration/test_intent_ranking.py`)
  passes its per-intent thresholds against the committed gold set, and the named live
  regression (the orientation query for gpu lock scope ranks the accepted
  `service-concurrency` ADR at rank 1, not the matching exec record) is green.
- Role-aware NDCG at 10 and orientation Authoritative-at-3 improve over the committed
  baseline; debugging MRR does not regress; the existing needle-precision floor stays at or
  above 0.75.
- Every vault search result carries `status` and `related` in both human and JSON output,
  verified by the result-shape test, with status parsed correctly for modern, legacy, and
  no-marker ADR headings.
- The explicit intent mode, doc-type union (audit included, index excluded), and status
  control behave identically across the CLI, the HTTP route, and the MCP `search_vault`
  tool, with a stable JSON envelope.
- The production CLI no longer exposes the quality or benchmark verbs; the bundled CLI
  reference regenerates clean; the relocated capability still runs under the test suite.
- The per-intent persona testimonials record satisfied verdicts against pre-declared
  expected-authority documents, and the A/B delta report is produced and embedded in the
  verification audit.
- The full unit and quality suites pass with zero lint or type violations, honoring the
  no-mock, real-GPU, real-Qdrant test mandate.
