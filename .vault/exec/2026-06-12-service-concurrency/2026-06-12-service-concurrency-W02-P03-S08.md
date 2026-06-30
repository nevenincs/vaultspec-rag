---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-06-30'
step_id: 'S08'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Convert the post-rerank multiplicative graph boost into a bounded additive nudge

## Scope

- `src/vaultspec_rag/search/_rerank.py`

## Description

- Replace the multiplicative post-rerank graph boost (up to x2.3 on
  calibrated scores) with bounded additive nudges: 0.005 per in-link capped
  at 10 links plus 0.03 for a feature-tagged neighbor.

## Outcome

Structural priors now break ties instead of overriding semantic relevance;
the cap stays at or below one typical rank gap, asserted by a unit test
against a real VaultGraph.

## Notes
