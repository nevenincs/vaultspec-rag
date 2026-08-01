---
tags:
  - '#exec'
  - '#index-lifecycle-consolidation'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:6694838e27be0a427f391378004c1168d0d7a03b6a6f99206837b85cfcff7e7a'
step_id: 'S01'
related:
  - "[[2026-07-25-index-lifecycle-consolidation-plan]]"
---

# Extract the shared index run lifecycle into its own module, owning the activity stamp, the event triple, and the incremental mode label

## Scope

- `src/vaultspec_rag/indexer/_index_lifecycle.py`

## Description

- Add `run_index_lifecycle`, which emits the started event, stamps the activity
  clock, calls the run body exactly once, stamps again, and emits completion;
  on any exception it emits the failure event and re-raises unchanged.
- Take the store through a narrow `ActivityClock` protocol declaring only
  `touch_manifest_last_indexed`, so the wrapper can be driven against the real
  stamp without constructing an indexer.
- Take the calling module's logger as a parameter rather than emitting through
  this module's own, so an event keeps the record name of the indexer that
  produced it and the extraction stays invisible to the log contract.
- Build the completion event as one ordered mapping passed as `fields`, so the
  per-kind extras land after the shared counters exactly as they did when each
  site spelled them out as keyword arguments.
- Add `incremental_mode`, deriving the scoped and unscoped incremental labels in
  one place.
- Keep the four attempt-control checkpoints around the stamp and the body that
  each copy carried, so cancellation still lands between the stamp and the work
  rather than only inside it.

## Outcome

The lifecycle exists as one implementation, with no callers yet. `ruff check`
and `basedpyright` clean over the indexer package.

## Notes

The wrapper deliberately takes no lock and expresses no opinion about lock
ordering: the code and vault paths call it under their writer lock while the
document path takes its writer lock inside the body. Unifying that was out of
scope and carries its own risk.
