---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:37f4f374ead4ea021a7d812e8cd0752a09530ff8745b1c15cce8cb81ede3d70e'
related:
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` audit: `s34 restart lifecycle`

## Scope

Audited `W05.P16.S34`: persisted generation capture, production restart
orchestration, queued dispatch, paused intent, interruption conversion, retry
lineage, terminal deletion, cross-generation cleanup, and store-close ordering.

## Findings

### restart-production-path | medium | resolved startup-path bypass

The first draft manually rebound and dispatched restored work. It was replaced
with the production service startup entry point, including canonical restore,
rebinding, runnable selection, dispatch, and callbacks.

### restart-real-attempt | medium | resolved synthetic interrupted attempt

The first draft persisted an inert task. It was replaced with a real production
indexing attempt held at the real writer boundary before its running generation
was captured.

### restart-teardown | high | resolved stale manager ownership

The fixture originally retained only the pre-reset manager. Teardown now drains
both that generation and the current singleton before closing project stores.

### restart-cancel-order | medium | resolved post-snapshot execution window

Old-generation cancellation is now requested while the writer remains blocked;
the lock is then released and the exact attempt is joined before restart.

Final review status: pass with no open findings.

## Recommendations

Accept S34. Keep the production lifecycle entry point and cross-generation
drain assertions intact when startup orchestration changes.
