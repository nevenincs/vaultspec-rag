---
generated: true
tags:
  - '#index'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:dfa2dd269ff1a992e27a2a67b1b39a5ccbbb18e2636f6292fc5b64cea7760e7d'
related:
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S01]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S02]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S03]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S04]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S05]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S06]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S07]]'
  - '[[2026-09-08-qdrant-collection-sprawl-P01-S08]]'
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

### plan

- `2026-09-08-qdrant-collection-sprawl-plan` - `qdrant-collection-sprawl` plan

### research

- `2026-09-08-qdrant-collection-sprawl-research` - `qdrant-collection-sprawl` research: `why 138 qdrant collections accumulate and never converge`
