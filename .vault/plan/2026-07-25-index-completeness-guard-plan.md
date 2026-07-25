---
tags:
  - '#plan'
  - '#index-completeness-guard'
date: '2026-07-25'
modified: '2026-07-25'
tier: L2
related:
  - '[[2026-07-25-index-completeness-guard-adr]]'
  - '[[2026-07-25-index-completeness-guard-research]]'
---

# `index-completeness-guard` plan

### Phase `P01` - publish breadth and make the predicate quantitative

Persist what a code-index publication actually wrote, then replace the existence-only evidence check with a shortfall comparison that escalates a partially destroyed collection to failure-safe reconciliation so a latched index heals itself.

- [x] `P01.S01` - Persist the point count a code-index publication actually wrote as a reserved metadata key alongside the existing bookkeeping keys; `src/vaultspec_rag/_index_breadth.py, src/vaultspec_rag/indexer/_code_meta.py, src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `P01.S02` - Replace the existence-only published-evidence check with a shortfall comparison against the published point count, retaining the absent-collection case and escalating only to failure-safe reconciliation; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `P01.S03` - Prove the shortfall guard can fail by permitting a truncated collection to pass, observing the intended failure, restoring, and observing the pass; `src/vaultspec_rag/tests/test_indexer_unit.py`.

### Phase `P02` - surface incompleteness at search time

Compute the published-versus-live comparison once in the service domain and carry it to the CLI and MCP adapters so a search over a demonstrably incomplete index cannot present itself as authoritative.

- [x] `P02.S04` - Compute the published-versus-live completeness fact once on the code search path and carry it on the result envelope beside the indexed count; `src/vaultspec_rag/_index_breadth.py, src/vaultspec_rag/api.py, src/vaultspec_rag/server/_routes.py`.
- [x] `P02.S05` - Render the shortfall as a CLI warning naming the deficit and the remedy on both the service and local search paths, and confirm the MCP code search tool already carries the field without recomputing it; `src/vaultspec_rag/cli/_search.py`.
- [x] `P02.S06` - Prove the completeness warning can fail by suppressing the signal over a truncated index, observing the intended failure, restoring, and observing the pass; `src/vaultspec_rag/tests/test_cli_search_safety.py, src/vaultspec_rag/tests/test_service_search_diagnostics.py`.

### Phase `P03` - validate and close

Prove both guards can fail for their intended reason, run every gate on real Qdrant and SQLite, and close the feature with a review.

- [ ] `P03.S07` - Run the lint, type, citation, complexity, and full test gates and record actual output rather than asserting success; `gates only, no source changes`.
- [ ] `P03.S08` - Review the landed change against the decision and record the closing audit; `.vault/audit/`.

## Description

## Steps

## Parallelization

## Verification
