---
tags:
  - '#plan'
  - '#search-index-availability'
date: '2026-07-21'
modified: '2026-07-22'
tier: L3
related:
  - '[[2026-07-21-search-index-availability-adr]]'
  - '[[2026-07-21-search-index-availability-research]]'
  - '[[2026-07-21-search-index-availability-reference]]'
  - '[[2026-07-21-service-job-control-plan]]'
  - '[[2026-07-21-large-index-resilience-plan]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

<!-- RETIRED: S02, S03, S04, S05, S10, S11, S12, S13, S14, S15, S16, S17 -->

# `search-index-availability` plan

## Wave `W01` - executable regression

Sol medium, the standard-tier test executor, proves the false-negative contract through the real service before production changes. The service-contract Wave depends on this red evidence.

### Phase `W01.P01` - real-service reproduction

Create one deterministic subprocess graphics processing unit regression that observes matching index work and the Hypertext Transfer Protocol (HTTP) search outcome without test doubles.

- [x] `W01.P01.S01` - Add the red real-service regression expecting structured HTTP 503 for an empty search during matching nonterminal index work and record the current HTTP 200 failure using Sol medium; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.

### Phase `W01.P05` - availability isolation

Prove the availability decision is scoped to the exact resolved project root and normalized requested source and never suppresses usable nonempty results.

- [x] `W01.P05.S06` - Add a real-service assertion that same-source work for another resolved project root preserves empty HTTP 200 using Sol medium; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.
- [x] `W01.P05.S07` - Add a real-service assertion that same-root work for another normalized source preserves empty HTTP 200 using Sol medium; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.
- [x] `W01.P05.S08` - Add a real-service assertion that matching nonterminal work preserves usable nonempty HTTP 200 using Sol medium; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.

### Phase `W01.P06` - consumer semantics

Lock the shared service client and downstream consumer boundary to structured unavailable data without a results key.

- [x] `W01.P06.S09` - Prove the shared service client preserves the structured unavailable error without manufacturing results using Sol medium; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.
- [ ] `W01.P06.S18` - Add a real MCP stdio call proving unavailable search yields CallToolResult isError true and never structured empty results using Sol medium; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.

## Wave `W02` - service availability contract

Terra xhigh, the high-tier production executor, implements the accepted root-scoped and source-scoped boundary after the expected HTTP 200 regression failure. Local acceptance depends on this Wave.

### Phase `W02.P02` - bounded search classification

Normalize copied compatibility and canonical job snapshots, then make only non-authoritative empty responses fail with the stable structured contract.

- [x] `W02.P02.S19` - Implement bounded root and source job matching plus the structured unavailable response using Terra xhigh; `src/vaultspec_rag/server/_search_availability.py`.
- [x] `W02.P02.S20` - Integrate double job-state observation and HTTP 503 emission into the search route using Terra xhigh; `src/vaultspec_rag/server/_routes.py`.

### Phase `W02.P07` - MCP failure translation

Translate structured daemon search failures before output-schema validation so Model Context Protocol callers receive a recoverable tool error instead of synthetic empty results.

- [x] `W02.P07.S21` - Map structured daemon search failures to recoverable MCP tool errors without synthesizing results using Terra xhigh; `src/vaultspec_rag/mcp/_tools.py`.

## Wave `W03` - acceptance and review

The supervisor, the primary architect, runs local GPU acceptance and mandatory review after implementation and retains all close-out decisions.

### Phase `W03.P03` - local GPU acceptance

Verify the real-service regression, stable empty-success behavior, unrelated-job isolation, and adjacent search diagnostics on local hardware.

- [ ] `W03.P03.S22` - Run the targeted subprocess-GPU regression and adjacent service search diagnostics under supervisor observation; `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.
- [ ] `W03.P03.S23` - Run formatting lint typing unit integration client CLI and MCP checks under supervisor observation; `src/vaultspec_rag`.
- [ ] `W03.P03.S24` - Validate research ADR plan and execution records with canonical vault checks; `.vault`.

### Phase `W03.P04` - mandatory code review

Audit the completed work against the ADR, repository rules, concurrent campaign boundaries, and test-integrity requirements before reporting completion.

- [ ] `W03.P04.S25` - Audit ADR conformance response safety campaign compatibility and test integrity and route required corrections to Terra xhigh; `.vault/audit/2026-07-21-search-index-availability-code-review-audit.md`.

## Description

Implement the accepted search-index availability contract from the related
research, reference, and architectural decision record (ADR). The work begins
with a real-service regression. It proves an empty result is non-authoritative
while a matching root-and-source convergence job is nonterminal.

Production code classifies copied job snapshots at the Hypertext Transfer
Protocol (HTTP) boundary. The route observes them before retrieval and again
before returning an empty response. It emits HTTP 503 with `ok: false`,
`error: index_unavailable`, the exact ADR-defined `index_state`, bounded job
references, and no `results` member. Stable empty searches, unrelated index
work, and usable nonempty results remain HTTP 200.

The implementation must consume both the compatibility snapshot shape and the
canonical service-job-control snapshot shape without modifying either job
registry. Future generation-ledger state may supply stronger evidence such as
`rebuild_incomplete` for an otherwise-empty result, but this plan does not
create that ledger.

Sol medium is the standard-tier test executor restricted to W01 and its test
file. Terra xhigh is the high-tier production executor restricted to W02 and
its three production files. The supervisor is the primary architect; it owns
the ADR, campaign-boundary decisions, acceptance evidence, and formal review.

## Steps

The Wave, Phase, and Step sections form the executable work graph.
The plan is updated with the vault plan CLI after every execution run so that
identifiers and completion state remain append-only and auditable.

## Parallelization

Waves execute in strict order. Sol medium owns all W01 phases and must preserve
the initial expected-failure evidence before W02 begins. Terra xhigh owns W02,
with S19 preceding S20 because the route integration depends on the bounded
classifier. S21 follows the HTTP contract because the Model Context Protocol
(MCP) adapter consumes its structured failure. Before editing `_routes.py`,
Terra must re-read the current working tree and preserve concurrent
service-job-control changes. W03 remains under the supervisor. Any review
correction is returned to Terra as a new CLI-created Step rather than folded
into a completed Step.

Within W01, Steps extend
`test_search_index_unavailable_during_matching_rebuild`. They share one real
subprocess service, one synthetic corpus of 256 documents with seed 252, and
one clean-index lifecycle. Each invariant remains a distinct Step and commit.

## Verification

- The pre-implementation real-service regression fails only because the
  matching nonterminal rebuild returns HTTP 200 with an empty `results` array.
- After implementation, a matching nonterminal convergence job makes an
  otherwise-empty search return HTTP 503 with the exact ADR-defined body and
  no `results` member.
- The same request returns HTTP 200 with an empty `results` array after the
  matching job succeeds and neither observation finds matching nonterminal
  work.
- Nonterminal work for another resolved project root or normalized source does
  not alter the stable HTTP 200 empty-result contract.
- A usable nonempty response remains HTTP 200 while matching work is
  nonterminal.
- The shared service client preserves `index_unavailable` as structured failure
  data. A real MCP stdio call returns `CallToolResult.isError is True` with
  actionable text and no structured `results` member.
- The local graphics processing unit regression passes with
  `uv run pytest -m subprocess_gpu src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py -k search_index_unavailable_during_matching_rebuild -vv -s`.
- Adjacent tests pass with
  `uv run pytest src/vaultspec_rag/tests/test_service_search_diagnostics.py src/vaultspec_rag/tests/test_cli_search.py src/vaultspec_rag/tests/test_cli_search_safety.py src/vaultspec_rag/tests/test_mcp_conformance_surface.py src/vaultspec_rag/tests/test_mcp_no_local_fallback.py src/vaultspec_rag/tests/integration/test_stdio_lifetime_e2e.py -vv`.
- Formatting passes with
  `uv run ruff format --check src/vaultspec_rag/server/_search_availability.py src/vaultspec_rag/server/_routes.py src/vaultspec_rag/mcp/_tools.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.
- Lint passes with
  `uv run ruff check src/vaultspec_rag/server/_search_availability.py src/vaultspec_rag/server/_routes.py src/vaultspec_rag/mcp/_tools.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.
- Strict typing passes with
  `uv run basedpyright src/vaultspec_rag/server/_search_availability.py src/vaultspec_rag/server/_routes.py src/vaultspec_rag/mcp/_tools.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`.
- `uv run vaultspec-core vault plan check .vault/plan/2026-07-21-search-index-availability-plan.md`
  and `uv run vaultspec-core vault check all --feature search-index-availability`
  pass.
- Every Step has one commit and one execution record. The formal
  `vaultspec-code-review` audit reports no unresolved critical or high finding,
  no ADR or safety violation, no campaign overwrite, and no prohibited test
  double.
