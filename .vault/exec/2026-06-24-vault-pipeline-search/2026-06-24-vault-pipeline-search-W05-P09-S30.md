---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S30'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---

# Run the full acceptance gate and produce the A/B delta report

## Scope

- `src/vaultspec_rag/tests/quality/ab_report.md`

## Description

- Wrote the A/B delta report (`ab_report.md`) recording per-intent baseline vs intent-prior
  metrics and the reading of each result.
- Ran the full acceptance gate (module by module, on the real GPU index): intent-ranking
  harness (3), persona testimonials (1, three personas), payload fields (4), result shape (5),
  and the existing needle-precision/quality suite (15).

## Outcome

The gate is green: 28 tests across the five suites pass. The headline orientation
Authoritative@3 rose 0.50 -> 0.833 (the achievable ceiling), the named live regression
passes, debugging MRR is non-regressed, and the needle-precision floor is preserved (no
relevance regression from the prior). The A/B report captures the evidence.

## Notes

Running all five quality suites in a single pytest session faults with a GPU
out-of-memory-class crash because each module holds its own session-scoped real-vault index
and CrossEncoder simultaneously; the gate must be run module-by-module (each passes). This is
a test-harness resource constraint, not a code defect, and is worth a future note in the
testing docs. The live manual persona run is W06. No blockers.
