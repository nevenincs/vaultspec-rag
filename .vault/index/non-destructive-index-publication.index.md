---
generated: true
tags:
  - '#index'
  - '#non-destructive-index-publication'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
related:
  - '[[2026-07-25-non-destructive-index-publication-P01-S01]]'
  - '[[2026-07-25-non-destructive-index-publication-P01-S02]]'
  - '[[2026-07-25-non-destructive-index-publication-P01-S03]]'
  - '[[2026-07-25-non-destructive-index-publication-P01-S04]]'
  - '[[2026-07-25-non-destructive-index-publication-P02-S05]]'
  - '[[2026-07-25-non-destructive-index-publication-P02-S06]]'
  - '[[2026-07-25-non-destructive-index-publication-P02-S07]]'
  - '[[2026-07-25-non-destructive-index-publication-P02-S08]]'
  - '[[2026-07-25-non-destructive-index-publication-P03-S09]]'
  - '[[2026-07-25-non-destructive-index-publication-P03-S10]]'
  - '[[2026-07-25-non-destructive-index-publication-P03-S11]]'
  - '[[2026-07-25-non-destructive-index-publication-P03-S12]]'
  - '[[2026-07-25-non-destructive-index-publication-P04-S13]]'
  - '[[2026-07-25-non-destructive-index-publication-P04-S14]]'
  - '[[2026-07-25-non-destructive-index-publication-P04-S15]]'
  - '[[2026-07-25-non-destructive-index-publication-P05-S16]]'
  - '[[2026-07-25-non-destructive-index-publication-P05-S17]]'
  - '[[2026-07-25-non-destructive-index-publication-adr]]'
  - '[[2026-07-25-non-destructive-index-publication-plan]]'
  - '[[2026-07-25-non-destructive-index-publication-research]]'
---

# `non-destructive-index-publication` feature index

Auto-generated index of all documents tagged with `#non-destructive-index-publication`.

## Documents

### adr

- `2026-07-25-non-destructive-index-publication-adr` - `non-destructive-index-publication` adr: `publish a rebuilt index without destroying the served one` | (**status:** `accepted`)

### exec

- `2026-07-25-non-destructive-index-publication-P01-S01` - Route the embed-format and config-drift escalation gates to failure-safe reconciliation so no watcher-driven run reaches a destructive rebuild
- `2026-07-25-non-destructive-index-publication-P01-S02` - Record the superseded-regime condition when a gate escalates non-destructively, and carry it on the code search path beside the existing breadth shortfall
- `2026-07-25-non-destructive-index-publication-P01-S03` - Render the superseded-regime warning on the command-line search surface and carry the same fact in the search summary so an adapter without a renderer reports it
- `2026-07-25-non-destructive-index-publication-P01-S04` - Prove by real-storage test that an unattended incremental over a drifted config leaves the served point count intact, and that the same run under an explicit operator rebuild still drops the collection
- `2026-07-25-non-destructive-index-publication-P02-S05` - Introduce a per-root served-collection pointer in the store, persisted alongside the existing per-root identity, defaulting to today's derived name where absent
- `2026-07-25-non-destructive-index-publication-P02-S06` - Resolve every read path's collection name through the pointer rather than deriving it from the root, leaving write paths on the derived name for now
- `2026-07-25-non-destructive-index-publication-P02-S07` - Route the survey and storage-operation surfaces at the pointer so no caller outside the store derives a collection name for itself
- `2026-07-25-non-destructive-index-publication-P02-S08` - Prove by real-storage test that a root whose pointer is absent resolves to the derived name unchanged, and that a root whose pointer names another collection is read from that collection
- `2026-07-25-non-destructive-index-publication-P03-S09` - Name each rebuild generation's collection so a name is never reused, defeating the local-mode directory-survival behaviour on create
- `2026-07-25-non-destructive-index-publication-P03-S10` - Write a clean rebuild into its generation collection, leaving the served collection untouched for the duration of the build
- `2026-07-25-non-destructive-index-publication-P03-S11` - Move the pointer to the new generation only after its breadth is recorded, so a reader never resolves a collection that has not reconciled
- `2026-07-25-non-destructive-index-publication-P03-S12` - Prove by real-storage test that a rebuild interrupted mid-build leaves the previously served point count fully readable, and that the pointer still names the old collection
- `2026-07-25-non-destructive-index-publication-P04-S13` - Estimate the duplicate a generation build needs and refuse the build with a stated reason when headroom cannot cover it, never falling back to rebuilding in place
- `2026-07-25-non-destructive-index-publication-P04-S14` - Drop a superseded generation collection from read-and-drop maintenance once the pointer no longer names it and no reader holds it
- `2026-07-25-non-destructive-index-publication-P04-S15` - Prove by real-storage test that a refused build leaves the served index intact and reports the refusal, and that maintenance drops only collections the pointer does not name
- `2026-07-25-non-destructive-index-publication-P05-S16` - Remove the interim superseded-regime mitigation and its reporting now that an unattended gate publishes non-destructively
- `2026-07-25-non-destructive-index-publication-P05-S17` - Prove by real-storage test that an unattended gate now reaches generation-scoped publication, reaching neither the destructive rebuild nor the interim compromise

### plan

- `2026-07-25-non-destructive-index-publication-plan` - `non-destructive-index-publication` plan

### research

- `2026-07-25-non-destructive-index-publication-research` - `non-destructive-index-publication` research: `how a clean rebuild empties a served index and why the cheap fix is wrong`
