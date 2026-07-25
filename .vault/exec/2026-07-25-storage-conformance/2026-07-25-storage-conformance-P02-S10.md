---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S10'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Report a namespace carrying no stamped identity as unverifiable, never as a failure

## Scope

- `src/vaultspec_rag/store.py`

## Description

## Outcome

A collection with no stamped identity, or one whose geometry could not be read,
verdicts `unverifiable`: it does not raise, does not degrade, and does not
authorise reclamation.

This is the state every existing namespace on every machine enters on first
upgrade, so it had to be the cheap and quiet path. The two mutations that would
break it in opposite directions are both covered - scoring it `conforming`
restores the silent pass this feature exists to remove, and scoring it
`nonconforming` degrades every host the moment it upgrades.

## Notes
