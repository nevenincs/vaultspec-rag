---
generated: true
tags:
  - '#index'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:58cd6e81ebd1b7acebc95bcbbb66b61151e27f6cf9af11286b0defe4e608861e'
related:
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S01]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S02]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S03]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S04]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S05]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S06]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S07]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S08]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S27]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S28]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S29]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S30]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S31]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S32]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S09]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S10]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S11]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S12]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S13]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S14]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S15]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S16]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P02-S17]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P03-S18]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P03-S19]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P03-S20]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P03-S21]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P03-S22]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P04-S23]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P04-S24]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P04-S25]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P04-S26]]'
  - '[[2026-09-08-qdrant-collection-sprawl-adr]]'
  - '[[2026-09-08-qdrant-collection-sprawl-plan]]'
  - '[[2026-09-08-qdrant-collection-sprawl-research]]'
  - '[[2026-09-09-qdrant-collection-sprawl-audit]]'
---

# `qdrant-collection-sprawl` feature index

Auto-generated index of all documents tagged with `#qdrant-collection-sprawl`.

## Documents

### adr

- `2026-09-08-qdrant-collection-sprawl-adr` - `qdrant-collection-sprawl` adr: `retention discrimination for the ephemeral namespace class, and the prerequisites that let it execute` | (**status:** `accepted`)

### audit

- `2026-09-09-qdrant-collection-sprawl-audit` - `qdrant-collection-sprawl` audit: `retention discrimination and its prerequisites`

### exec

- `2026-09-08-qdrant-collection-sprawl-P01-S01` - Make the qdrant readiness wait treat observable recovery progress as liveness, keeping the existing fixed budget as a hard ceiling
- `2026-09-08-qdrant-collection-sprawl-P01-S02` - Add a guard test proving a child still recovering collections survives past the old fixed budget
- `2026-09-08-qdrant-collection-sprawl-P01-S03` - Add a guard test proving a wedged child making no progress is still stopped at the hard ceiling
- `2026-09-08-qdrant-collection-sprawl-P01-S04` - Widen the archive-call guard to catch the qdrant client transport failures so a snapshot timeout marks one namespace failed
- `2026-09-08-qdrant-collection-sprawl-P01-S05` - Widen the pre-drop re-count guard to catch the qdrant client transport failures so a timeout defers that namespace
- `2026-09-08-qdrant-collection-sprawl-P01-S06` - Widen the active-index-job probe guard to catch the qdrant client transport failures
- `2026-09-08-qdrant-collection-sprawl-P01-S07` - Add a guard test proving a snapshot read timeout marks that namespace failed and the cycle continues to the next candidate
- `2026-09-08-qdrant-collection-sprawl-P01-S08` - Add a guard test proving a re-count read timeout defers the namespace rather than aborting the cycle
- `2026-09-08-qdrant-collection-sprawl-P01-S27` - Widen the survey-time point-count guard so a transport timeout leaves that collection uncounted rather than unwinding the survey and the cycle with it
- `2026-09-08-qdrant-collection-sprawl-P01-S28` - Carry an uncountable collection through the survey as unverifiable rather than as zero points, so a failed count cannot mis-tier a data-bearing namespace as empty
- `2026-09-08-qdrant-collection-sprawl-P01-S29` - Guard the collection enumeration in the pre-drop re-count so a transport timeout yields an unverifiable count instead of escaping
- `2026-09-08-qdrant-collection-sprawl-P01-S30` - Return an unverifiable result from the active-index-job probe so a registry read failure defers the namespace instead of reporting no job busy
- `2026-09-08-qdrant-collection-sprawl-P01-S31` - Add a guard test proving a survey-time transport timeout leaves the maintenance cycle running and the namespace unreclaimed
- `2026-09-08-qdrant-collection-sprawl-P01-S32` - Add a guard test proving an unverifiable active-job probe defers the namespace rather than authorising the drop
- `2026-09-08-qdrant-collection-sprawl-P02-S09` - Add the ephemeral-orphan grace window as a configuration default alongside the existing autoprune knobs
- `2026-09-08-qdrant-collection-sprawl-P02-S10` - Add the ephemeral-orphan window field to the reclaim policy with its documented default
- `2026-09-08-qdrant-collection-sprawl-P02-S11` - Select the ephemeral window in the orphan decision when the namespace root was temp-rooted, keeping point count as the tier selector
- `2026-09-08-qdrant-collection-sprawl-P02-S12` - Thread the configured ephemeral window into the policy the maintenance tick constructs
- `2026-09-08-qdrant-collection-sprawl-P02-S13` - Add a test proving an orphaned temp-rooted point-bearing namespace draws the ephemeral window, not the data window
- `2026-09-08-qdrant-collection-sprawl-P02-S14` - Add a test proving an orphaned non-temp point-bearing namespace still draws the full data window
- `2026-09-08-qdrant-collection-sprawl-P02-S15` - Add a guard test proving the ephemeral window does not bypass the archive-before-destroy gate
- `2026-09-08-qdrant-collection-sprawl-P02-S16` - Add a guard test proving the ephemeral window does not bypass the pre-drop point re-count
- `2026-09-08-qdrant-collection-sprawl-P02-S17` - Add a guard test proving an unknown or unverifiable namespace is still never reached by the ephemeral path
- `2026-09-08-qdrant-collection-sprawl-P03-S18` - Raise the archive size cap default so a full ephemeral drain does not evict the evidence it writes
- `2026-09-08-qdrant-collection-sprawl-P03-S19` - State the unavailable in-place restore and name the portable recovery path on the operator-facing archive surface
- `2026-09-08-qdrant-collection-sprawl-P03-S20` - Report total collection count and the ephemeral backlog size on the storage status route
- `2026-09-08-qdrant-collection-sprawl-P03-S21` - Render the reported collection count and ephemeral backlog in the status output
- `2026-09-08-qdrant-collection-sprawl-P03-S22` - Add a test covering the reported collection count and ephemeral backlog fields
- `2026-09-08-qdrant-collection-sprawl-P04-S23` - Drop grace-ledger entries naming collections that no longer exist when the ledger is next written
- `2026-09-08-qdrant-collection-sprawl-P04-S24` - Add a test proving ledger entries for absent collections are pruned and live entries are preserved
- `2026-09-08-qdrant-collection-sprawl-P04-S25` - Point the qdrant storage-dir at a temp path in the storage-ops tests that reach the managed backend
- `2026-09-08-qdrant-collection-sprawl-P04-S26` - Point the qdrant storage-dir at a temp path in the storage-survey tests that reach the managed backend

### plan

- `2026-09-08-qdrant-collection-sprawl-plan` - `qdrant-collection-sprawl` plan

### research

- `2026-09-08-qdrant-collection-sprawl-research` - `qdrant-collection-sprawl` research: `why 138 qdrant collections accumulate and never converge`
