---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
modified: '2026-07-27'
body_hash: 'sha256:92ea2b3ac65c6cf3c05638e4f2358a4c8b4d2dc9fa6d5043f8f52ebc503ec82d'
step_id: 'S08'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Convert the post-rerank multiplicative graph boost into a bounded additive nudge

## Description

### Scope

- `src/vaultspec_rag/search/_rerank.py`

- Replace the multiplicative post-rerank graph boost (up to x2.3 on
  calibrated scores) with bounded additive nudges: 0.005 per in-link capped
  at 10 links plus 0.03 for a feature-tagged neighbor.

## Outcome

Structural priors now break ties instead of overriding semantic relevance;
the cap stays at or below one typical rank gap, asserted by a unit test
against a real VaultGraph.

## Notes

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.
