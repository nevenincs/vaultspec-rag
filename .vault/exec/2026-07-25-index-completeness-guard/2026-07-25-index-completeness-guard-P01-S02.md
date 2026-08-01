---
tags:
  - '#exec'
  - '#index-completeness-guard'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:d71304371da5a42aadfb52e3257392cb2f39803c23e257fd58348ce561f3889f'
step_id: 'S02'
related:
  - "[[2026-07-25-index-completeness-guard-plan]]"
---

# Replace the existence-only published-evidence check with a shortfall comparison against the published point count, retaining the absent-collection case and escalating only to failure-safe reconciliation

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Replace the existence-only predicate in
  `CodebaseIndexer._published_evidence_lost` with a four-branch decision: no
  carried file evidence is not a loss, an absent collection still is, an absent
  or unusable published count is "cannot tell", and a live count below the
  published one is a shortfall.
- Log the deficit with both figures before escalating, so an operator reading
  the log sees how much breadth went missing rather than only that a rebuild
  started.
- Treat a store that cannot be counted as "cannot tell" and trust the carried
  evidence for that run, rather than escalating on a transient store error.

## Outcome

Landed in `00ab3ef3`. A partially destroyed collection - present, non-empty,
and describing itself as whole - now escalates to full reconciliation on the
next run instead of being trusted. Escalation targets the failure-safe path, so
a spurious escalation costs GPU time and republishes the count; it cannot cause
the data loss it exists to detect.

The shortfall threshold is any deficit rather than a tolerance band. Publication
is taken after storage reconciliation at every call site, so a complete index
reads back exactly what it published, and a legitimate shrink travels the
incremental path and republishes its own count.

## Notes

Collapsed two canonical-code defects found in the work in progress: a verbatim
duplicate of the count parser had been added to the indexer's sidecar module
alongside the leaf function, and the reserved key was re-exported from that
module by alias. Both were deleted and the callers - the predicate, the atomic
writer, and the test that writes a sidecar directly - repointed at the leaf.
