---
generated: true
tags:
  - '#index'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:2b0a30e7ca2214aa5b473653a8577d2db172de80ae78cc68215387515236e8b1'
related:
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S01]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S02]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S03]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S04]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S05]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S06]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S07]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S08]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S09]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S10]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S11]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S12]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S13]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S14]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S15]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S16]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S17]]'
  - '[[2026-09-08-qdrant-collection-sprawl-adr]]'
  - '[[2026-09-08-qdrant-collection-sprawl-plan]]'
  - '[[2026-09-08-qdrant-collection-sprawl-research]]'
---

# `qdrant-collection-sprawl` feature index

Auto-generated index of all documents tagged with `#qdrant-collection-sprawl`.

## Documents

### adr

- `2026-09-08-qdrant-collection-sprawl-adr` - `qdrant-collection-sprawl` adr: `retention discrimination for the ephemeral namespace class, and the prerequisites that let it execute` | (**status:** `accepted`)

### exec

- `2026-09-08-qdrant-collection-sprawl-P01-S01` - Make the qdrant readiness wait treat observable recovery progress as liveness, keeping the existing fixed budget as a hard ceiling
- `2026-09-08-qdrant-collection-sprawl-P01-S02` - Add a guard test proving a child still recovering collections survives past the old fixed budget
- `2026-09-08-qdrant-collection-sprawl-P01-S03` - Add a guard test proving a wedged child making no progress is still stopped at the hard ceiling
- `2026-09-08-qdrant-collection-sprawl-P01-S04` - Widen the archive-call guard to catch the qdrant client transport failures so a snapshot timeout marks one namespace failed
- `2026-09-08-qdrant-collection-sprawl-P01-S05` - Widen the pre-drop re-count guard to catch the qdrant client transport failures so a timeout defers that namespace
- `2026-09-08-qdrant-collection-sprawl-P01-S06` - Widen the active-index-job probe guard to catch the qdrant client transport failures
- `2026-09-08-qdrant-collection-sprawl-P01-S07` - Add a guard test proving a snapshot read timeout marks that namespace failed and the cycle continues to the next candidate
- `2026-09-08-qdrant-collection-sprawl-P01-S08` - Add a guard test proving a re-count read timeout defers the namespace rather than aborting the cycle
- `2026-09-08-qdrant-collection-sprawl-P02-S09` - Add the ephemeral-orphan grace window as a configuration default alongside the existing autoprune knobs
- `2026-09-08-qdrant-collection-sprawl-P02-S10` - Add the ephemeral-orphan window field to the reclaim policy with its documented default
- `2026-09-08-qdrant-collection-sprawl-P02-S11` - Select the ephemeral window in the orphan decision when the namespace root was temp-rooted, keeping point count as the tier selector
- `2026-09-08-qdrant-collection-sprawl-P02-S12` - Thread the configured ephemeral window into the policy the maintenance tick constructs
- `2026-09-08-qdrant-collection-sprawl-P02-S13` - Add a test proving an orphaned temp-rooted point-bearing namespace draws the ephemeral window, not the data window
- `2026-09-08-qdrant-collection-sprawl-P02-S14` - Add a test proving an orphaned non-temp point-bearing namespace still draws the full data window
- `2026-09-08-qdrant-collection-sprawl-P02-S15` - Add a guard test proving the ephemeral window does not bypass the archive-before-destroy gate
- `2026-09-08-qdrant-collection-sprawl-P02-S16` - Add a guard test proving the ephemeral window does not bypass the pre-drop point re-count
- `2026-09-08-qdrant-collection-sprawl-P02-S17` - Add a guard test proving an unknown or unverifiable namespace is still never reached by the ephemeral path

### plan

- `2026-09-08-qdrant-collection-sprawl-plan` - `qdrant-collection-sprawl` plan

### research

- `2026-09-08-qdrant-collection-sprawl-research` - `qdrant-collection-sprawl` research: `why 138 qdrant collections accumulate and never converge`
