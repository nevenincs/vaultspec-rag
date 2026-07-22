---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S10'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Define typed machine resolution with holder and pointer identity, freshness, source, and reasoned degraded states

## Scope

- `src/vaultspec_rag/serviceclient/_discovery.py`

## Description

- Define a frozen resolution record carrying holder identity, pointer identity, port,
  token, heartbeat freshness, staleness window, source, and refusal reason.
- Add the ready, absent, and degraded state vocabulary with a named reason for each way
  a live holder's pointer can be untrustworthy.
- Resolve the singleton through the OS lock first, then classify the holder's published
  pointer as ready or as one of the reasoned degraded outcomes.
- Restrict the status-file view to the no-holder compatibility case and re-express the
  legacy payload and port helpers on top of the typed resolution.
- Replace the boolean staleness predicate with freshness evidence the caller can report.

## Outcome

A live holder whose pointer is missing, unparseable, portless, foreign, or stale now
resolves degraded with the evidence behind the refusal, instead of collapsing into the
same absence a genuinely stopped machine produces.

## Notes

The status-file fallback is now unreachable while a holder is live. That is a deliberate
behaviour change: the fallback could otherwise hand a caller an address the singleton
owner never published, which is worse than reporting that the owner's own publication
cannot be trusted. Absence remains reserved for the case where no singleton is held at
all.
