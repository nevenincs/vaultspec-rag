---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S12'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Author the nonconforming verdict as a live-service degraded reason where degradation is already authored

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

## Outcome

`ServiceHealth` gains a `nonconforming` list, populated in `ServiceRegistry.health`
from the verdicts the ensure path already recorded, and `_service_health_status`
appends a reason and flips a ready service to degraded when it is non-empty.

No backend call happens on the health path. The registry reads each warm slot's
recorded verdicts under the lock it already holds, so a health poll stays cheap;
a collection nobody has opened contributes nothing rather than a guess, and an
`unverifiable` one contributes nothing either.

The reason names up to three affected collections so an operator can tell which
index to rebuild. Proven by mutation: with the branch removed the service
reports `ready` while returning rankings computed against another model's
vectors (`assert 'ready' == 'degraded'`), and with the collection names dropped
the naming assertion fails.

## Notes
