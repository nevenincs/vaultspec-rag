---
generated: true
tags:
  - '#index'
  - '#incremental-publication-cost'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:4e3ceb1b7e13ddeaa7af77d9a0e38a8bc53a4cc72d469b47a4aaa3a46ad517d6'
related:
  - '[[2026-09-08-incremental-publication-cost-W01-P01-S01]]'
  - '[[2026-09-08-incremental-publication-cost-W01-P01-S02]]'
  - '[[2026-09-08-incremental-publication-cost-W01-P01-S53]]'
  - '[[2026-09-08-incremental-publication-cost-W01-P02-S03]]'
  - '[[2026-09-08-incremental-publication-cost-W01-P02-S04]]'
  - '[[2026-09-08-incremental-publication-cost-W01-P02-S05]]'
  - '[[2026-09-08-incremental-publication-cost-W01-P02-S06]]'
  - '[[2026-09-08-incremental-publication-cost-W01-P02-S07]]'
  - '[[2026-09-08-incremental-publication-cost-W01-P02-S54]]'
  - '[[2026-09-08-incremental-publication-cost-W01-P02-S68]]'
  - '[[2026-09-08-incremental-publication-cost-W01-P02-S70]]'
  - '[[2026-09-08-incremental-publication-cost-adr]]'
  - '[[2026-09-08-incremental-publication-cost-plan]]'
  - '[[2026-09-08-incremental-publication-cost-reference]]'
  - '[[2026-09-08-incremental-publication-cost-research]]'
---

# `incremental-publication-cost` feature index

Auto-generated index of all documents tagged with `#incremental-publication-cost`.

## Documents

### adr

- `2026-09-08-incremental-publication-cost-adr` - `incremental-publication-cost` adr: `publish exact completeness proofs from committed deltas` | (**status:** `accepted`)

### exec

- `2026-09-08-incremental-publication-cost-W01-P01-S01` - Define publication proof identities, path deltas, aggregate arithmetic, receipt states, provenance, and typed failures
- `2026-09-08-incremental-publication-cost-W01-P01-S02` - Prove add, modify, delete, rename, empty, ignored, rejected, and no-op delta behavior
- `2026-09-08-incremental-publication-cost-W01-P01-S53` - Correct proof compatibility, streaming mutation, and reader-transition contracts
- `2026-09-08-incremental-publication-cost-W01-P02-S03` - Extend ledger value and schema contracts for proof revisions, rows, aggregates, receipts, and provenance
- `2026-09-08-incremental-publication-cost-W01-P02-S04` - Create and migrate normalized proof, receipt, mutation-unit, and tombstone tables with post-migration schema verification
- `2026-09-08-incremental-publication-cost-W01-P02-S05` - Implement bounded proof reads, compare-and-swap revision commits, active-receipt lookup, read tokens, and canonical RunLedger composition
- `2026-09-08-incremental-publication-cost-W01-P02-S06` - Persist mutation intent before storage, confirm after acknowledgement, and replay or roll back deterministic retained-point units
- `2026-09-08-incremental-publication-cost-W01-P02-S07` - Prove exact current-schema creation, typed rebuild refusal for old formats, corrupt-schema refusal, revision mismatch, tombstones, receipt replay, atomic proof commit, and zero-copy start
- `2026-09-08-incremental-publication-cost-W01-P02-S54` - Implement receipt-bound single-snapshot canonical-proof reads with sparse run-local overrides, deletion tombstones, bounded path and candidate inputs, and exact retained-point ownership without generation ancestry or a second authority
- `2026-09-08-incremental-publication-cost-W01-P02-S68` - Hard-bump and gate the publication ledger format, create only an empty current schema, reject old or pre-proof databases without mutation, and remove legacy proof statuses
- `2026-09-08-incremental-publication-cost-W01-P02-S70` - Require backend identity in run signatures and checkpoint requests, delete legacy defaults and decoder fallbacks, and update every constructor

### plan

- `2026-09-08-incremental-publication-cost-plan` - `incremental-publication-cost` plan

### reference

- `2026-09-08-incremental-publication-cost-reference` - `incremental-publication-cost` reference: `publication proof seams`

### research

- `2026-09-08-incremental-publication-cost-research` - `incremental-publication-cost` research: `exact delta publication`
