---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S09'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Prove a losing real HTTP daemon exits nonzero before listener, Qdrant, pointer, watcher, or maintenance startup

## Scope

- `src/vaultspec_rag/tests/integration/test_machine_singleton.py`

## Description

- Hold the machine singleton with a real foreign lock holder, then launch a real HTTP
  daemon process against the same managed storage.
- Assert the loser exits nonzero, names the live holder, and refuses from the singleton
  claim itself.
- Assert component startup never appears in the failure trace, and that no service
  listener, managed Qdrant listener, machine pointer, or status view was created.
- Assert the incumbent still owns the singleton afterwards.

## Outcome

The boundary holds as specified, so B6 closes on evidence with no production lifecycle
change. A speculative second start cannot disturb the incumbent's listener, Qdrant child,
discovery records, watcher, or maintenance loop.

## Notes

Two false negatives had to be removed before the proof meant anything. The daemon
redirects its own standard streams into the managed log, so the captured pipes were empty
and the first version asserted against nothing; the assertions now read the managed log.
The managed Qdrant port also had to be relocated, because on the shared default the loser
failed against the operator's live Qdrant before it ever reached the singleton claim,
which would have proven nothing about this boundary.

The startup assertion is made against the absence of the component-startup frame rather
than against log keywords. The refusal message names the very resources it protects, so a
keyword scan matched its own prose and reported a component start that never happened.
