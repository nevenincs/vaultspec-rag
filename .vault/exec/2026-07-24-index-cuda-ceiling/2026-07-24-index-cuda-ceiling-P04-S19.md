---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S19'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# restart the service on the built code and confirm a live feature-profile corpus rebuild completes with no spurious cuda_memory_ceiling failures under concurrency

## Scope

- `src/vaultspec_rag`

## Description

- Stopped the stale resident service (it had loaded the pre-fix code in
  memory at an earlier redeploy) and restarted it on current code with a
  CLEAN environment - no encode-batch or ceiling overrides - so the shipped
  defaults were what was exercised.
- Queued a full `feature-profile` corpus rebuild (`--type all --rebuild`) and
  monitored the service log for `cuda_memory_ceiling`, then re-ran the
  document index alone.

## Outcome

Ceiling criterion MET. Across the whole run there were ZERO
`cuda_memory_ceiling` failures - a log search returned none, and every
ceiling failure still on record is timestamped to the pre-fix run or belongs
to a different root. The feature-profile document index embedded content for
the first time: document sections went from 0 - which they had been through
every prior attempt, each killed on the ceiling - to 418, on shipped defaults
with no workaround. The code index completed clean repeatedly (+6424 each).
Together with the 28 GPU integration tests that exercise the captured-peak
enforcement with real models, the fix is verified on hardware.

## Notes

Full-corpus completion was NOT reached, and the cause was not the ceiling.
The document job was interrupted partway (418 sections) by concurrent
multi-tenant load: the same shared daemon was simultaneously indexing
`proto-spike` (a second session) and `aeat-worktrees/main`, and their watcher
and code jobs superseded / starved the feature-profile document rebuild. A
second document-only rerun could not even get a slot against the saturated
daemon. This is the exact cross-tenant contention the sibling service-quiesce
feature exists to resolve, so this run is also live motivation for it.

Two orthogonal findings surfaced, both follow-ups rather than ceiling
regressions: a `proto-spike` code job hit `corpus_limit_exceeded` on the
`embedded-local` profile (6 GiB) because the allocated projection into the
corpus-sizing dimension is tight on the smaller profile; and a donor-read
404 (`Collection ..._document_docs doesn't exist`) came from another
session's uncommitted store/streaming changes that the freshly started
service loaded off the working tree. Neither is on the ceiling path.
