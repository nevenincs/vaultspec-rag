---
generated: true
tags:
  - '#index'
  - '#index-lifecycle-consolidation'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:2a815781f87476cbd42adf471f65c038b23da052e7c9f503d7d025d133bde515'
related:
  - '[[2026-07-25-index-lifecycle-consolidation-S01]]'
  - '[[2026-07-25-index-lifecycle-consolidation-S02]]'
  - '[[2026-07-25-index-lifecycle-consolidation-S03]]'
  - '[[2026-07-25-index-lifecycle-consolidation-S04]]'
  - '[[2026-07-25-index-lifecycle-consolidation-adr]]'
  - '[[2026-07-25-index-lifecycle-consolidation-plan]]'
  - '[[2026-07-25-index-lifecycle-consolidation-research]]'
---

# `index-lifecycle-consolidation` feature index

Auto-generated index of all documents tagged with `#index-lifecycle-consolidation`.

## Documents

### adr

- `2026-07-25-index-lifecycle-consolidation-adr` - `index-lifecycle-consolidation` adr: `one shared run lifecycle for every index entry point` | (**status:** `accepted`)

### exec

- `2026-07-25-index-lifecycle-consolidation-S01` - Extract the shared index run lifecycle into its own module, owning the activity stamp, the event triple, and the incremental mode label
- `2026-07-25-index-lifecycle-consolidation-S02` - Route the codebase and vault entry points through the shared lifecycle, preserving event fields, ordering, and emitting logger identity
- `2026-07-25-index-lifecycle-consolidation-S03` - Extract the document run bodies and route both document entry points through the shared lifecycle so the stamp and the events arrive by construction
- `2026-07-25-index-lifecycle-consolidation-S04` - Add the cross-indexer parity test binding every entry point to the shared lifecycle, and mutation-prove each guard can fail

### plan

- `2026-07-25-index-lifecycle-consolidation-plan` - `index-lifecycle-consolidation` plan

### research

- `2026-07-25-index-lifecycle-consolidation-research` - `index-lifecycle-consolidation` research: `activity clock and index event reachability across the three indexers`
