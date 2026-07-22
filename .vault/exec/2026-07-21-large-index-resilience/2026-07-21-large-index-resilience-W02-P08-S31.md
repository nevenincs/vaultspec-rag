---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S31'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Interrupt each finalization phase and prove restart converges to exact point IDs and metadata

## Scope

- `src/vaultspec_rag/tests/integration/test_indexer_integration.py`

## Description

- Interrupt generations independently after stale reconciliation, metadata publication, and generation publication.
- Reopen each exact generation and resume only its remaining durable phases.
- Verify committed point identities remain attached to the resumed generation.
- Verify the atomic metadata sidecar exists before successful generation completion and compaction.

## Outcome

Every finalization interruption point converges through the same idempotent production methods to a compacted successful generation with retained point evidence and published metadata.

## Notes

The phase matrix uses real SQLite transactions and the production metadata publisher. Real-store full idempotence and clean-recovery cases provide the external storage convergence boundary without test doubles.
