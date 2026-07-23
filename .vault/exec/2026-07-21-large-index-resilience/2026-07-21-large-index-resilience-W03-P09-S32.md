---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S32'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Record generation, commit, replay, memory, deadline, circuit, profile, and terminal fields in canonical job snapshots

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Confirm the canonical job snapshot carries the full resilience projection -
  generation, commit, replay, memory, deadline, circuit, profile, and terminal
  fields (`src/vaultspec_rag/job_models.py:218`).
- Confirm the snapshot is populated from the real runtime and flows into every
  emitted record through `to_dict` (`src/vaultspec_rag/jobs.py:646`).

## Outcome

The canonical job snapshot records every resilience field this step requires,
and this record confirms it rather than producing it - the implementation landed
through other commits ahead of this plan's execute phase, and the honest thing
is to verify it against the step's contract, not to claim authorship of it.

The typed `IndexResilienceSnapshot` carries all eight field groups the step
names: the checkpoint generation, the committed and replayed unit counts, the
memory high-water and ceiling for RSS and CUDA, the no-progress deadline and its
remaining budget, the retry circuit state and next-retry time, the support
profile, and the terminal outcome. Each was confirmed present by round-tripping
a populated snapshot through the serializer and checking every group appears.

The snapshot is real, not a placeholder. It is constructed from the running job
from the dispatch, manager, and watcher paths, persisted across a daemon restart
by the persistence layer, and projected into every emitted record through the
snapshot's own `to_dict`, which the registry snapshot builds on. So a consumer
reading a canonical job record sees the checkpoint and liveness state the job
actually reached, which is the property the rest of this phase - the response
shaping, the health rollup, and the CLI render - depends on.

## Notes

This step was verified and recorded, not executed here. The field model and its
population were already committed when this plan's execute phase reached the
step, so no code was written for it; the record exists so the plan's history is
honest about what closed the step - a confirmation against the contract, backed
by a serializer round-trip that checks every named field group is present.

The field validation lives on the snapshot dataclass itself, which rejects a
negative unit count or a non-finite memory measure at construction, so a
malformed resilience projection cannot enter a canonical record in the first
place. That guard was confirmed present; it is exercised by the existing
resilience unit tests rather than by anything added here.
