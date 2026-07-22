---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S20'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Expose an idempotent non-destructive server reconcile command with structured outcomes

## Scope

- `src/vaultspec_rag/cli/_service_reconcile.py`

## Description

- Expose the reconcile verb with a bounded timeout option and both output modes.
- Emit one structured envelope carrying the outcome, the attempts, and the discovery
  evidence, and exit nonzero only when discovery did not converge.
- Render the human form with the evidence and follow-up actions on a failure.

## Outcome

The bounded reconcile is now an operator command whose success is idempotent: running it
against an already-agreeing machine reports that and exits zero, so a supervising caller
can invoke it speculatively without testing first.

## Notes

The verb is deliberately incapable of destruction. It holds no lease, so it cannot publish
or delete discovery, and it never stops, restarts, or signals a process; the worst outcome
is a bounded wait that reports it did not converge.
