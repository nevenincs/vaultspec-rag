---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:489e899d27830b3e17ed6514c3fe0af10c2d14867150829a3e9b25981ccbd8bd'
step_id: 'S37'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Expose ledger commit units, protected spans, and typed safety signals through the run-policy safe-point contract

## Scope

- `src/vaultspec_rag/indexer/_run_policy.py`

## Description

- Expose labeled protected spans through the checkpoint-owned run policy.
- Check liveness and pending control at each protected-span entry and exit.
- Route clean publication and incremental replacement through the same authority that records ledger commits and finalization progress.
- Preserve typed no-progress and cooperative control signals without acknowledging inside indivisible mutations.

## Outcome

Ledger progress, storage retry budget, protected publication, and cooperative control now share one run-policy authority. Replacement spans defer control until their durable exit while ordinary bounded waits remain interruptible.

## Notes

The real-token run-policy suite passed 17 cases, including protected cancellation, deadline latching, bounded queue operations, cleanup delivery, and thread joins. Static type checking passed; the single style finding was corrected before commit.
