---
generated: true
tags:
  - '#index'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
related:
  - '[[2026-06-30-qdrant-store-resilience-P01-S01]]'
  - '[[2026-06-30-qdrant-store-resilience-P02-S02]]'
  - '[[2026-06-30-qdrant-store-resilience-P03-S03]]'
  - '[[2026-06-30-qdrant-store-resilience-P04-S04]]'
  - '[[2026-06-30-qdrant-store-resilience-P05-S05]]'
  - '[[2026-06-30-qdrant-store-resilience-adr]]'
  - '[[2026-06-30-qdrant-store-resilience-plan]]'
  - '[[2026-06-30-qdrant-store-resilience-research]]'
---

# `qdrant-store-resilience` feature index

Auto-generated index of all documents tagged with `#qdrant-store-resilience`.

## Documents

### adr

- `2026-06-30-qdrant-store-resilience-adr` - `qdrant-store-resilience` adr: `Detect, quarantine, and retry a corrupt collection on supervised start` | (**status:** `accepted`)

### exec

- `2026-06-30-qdrant-store-resilience-P01-S01` - Add \_quarantine_collection that moves collections/<name> to collections/.quarantine/<name>.<timestamp>
- `2026-06-30-qdrant-store-resilience-P02-S02` - Add \_corrupt_collection_from_output that returns an on-disk collection name found in the failure tail or None
- `2026-06-30-qdrant-store-resilience-P03-S03` - Wrap supervised start with a bounded detect-quarantine-retry loop, on by default, abstaining when no culprit is identified
- `2026-06-30-qdrant-store-resilience-P04-S04` - Add a server qdrant quarantine CLI verb that lists collections and quarantines a named one
- `2026-06-30-qdrant-store-resilience-P05-S05` - Add real-behavior tests for quarantine move, detection parser, bounded retry, and the CLI verb under an isolated storage dir

### plan

- `2026-06-30-qdrant-store-resilience-plan` - `qdrant-store-resilience` plan

### research

- `2026-06-30-qdrant-store-resilience-research` - `qdrant-store-resilience` research: `Corrupt-collection resilience for the shared Qdrant store`
