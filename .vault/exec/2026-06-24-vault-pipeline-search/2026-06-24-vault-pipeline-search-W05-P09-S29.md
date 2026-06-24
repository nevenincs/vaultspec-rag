---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S29'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Add the per-intent persona ranking-testimonial integration test

## Scope

- `src/vaultspec_rag/tests/integration/test_ranking_testimonial.py`

## Description

- Authored `test_ranking_testimonial.py`: per-intent personas (`orienting newcomer` x2,
  `debugging maintainer`) each declare an `expected_authority` doc before searching, run a
  live query against a real GPU index of the project vault, and record a structured
  `_Testimonial` (persona, intent, query, expected, observed top-5, verdict, note).
- Asserted every persona is `satisfied` (its expected authority leads the top 3), with the
  full ranked list surfaced on any failure for diagnosis.

## Outcome

All three personas pass on the real GPU index in ~89s: the orientation personas get the
accepted service-concurrency and qdrant-provisioning ADRs leading, and the debugging persona
gets the gpu-lock exec record leading. `ruff` and `ty` pass. This is the codified qualitative
gate; the live manual persona run is W06.

## Notes

The fixture builds its own real-vault copy (a small duplicate of the harness fixture) to keep
the testimonial test self-contained and not perturb the passing intent-ranking harness. No
blockers.
