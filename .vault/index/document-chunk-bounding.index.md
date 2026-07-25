---
generated: true
tags:
  - '#index'
  - '#document-chunk-bounding'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - '[[2026-07-23-document-chunk-bounding-P01-S01]]'
  - '[[2026-07-23-document-chunk-bounding-P01-S02]]'
  - '[[2026-07-23-document-chunk-bounding-P01-S03]]'
  - '[[2026-07-23-document-chunk-bounding-P01-S04]]'
  - '[[2026-07-23-document-chunk-bounding-P01-S05]]'
  - '[[2026-07-23-document-chunk-bounding-P02-S06]]'
  - '[[2026-07-23-document-chunk-bounding-P02-S07]]'
  - '[[2026-07-23-document-chunk-bounding-P02-S08]]'
  - '[[2026-07-23-document-chunk-bounding-P02-S09]]'
  - '[[2026-07-23-document-chunk-bounding-P02-S10]]'
  - '[[2026-07-23-document-chunk-bounding-P03-S11]]'
  - '[[2026-07-23-document-chunk-bounding-P03-S12]]'
  - '[[2026-07-23-document-chunk-bounding-P03-S13]]'
  - '[[2026-07-23-document-chunk-bounding-P03-S14]]'
  - '[[2026-07-23-document-chunk-bounding-P04-S15]]'
  - '[[2026-07-23-document-chunk-bounding-P04-S16]]'
  - '[[2026-07-23-document-chunk-bounding-P04-S17]]'
  - '[[2026-07-23-document-chunk-bounding-P04-S18]]'
  - '[[2026-07-23-document-chunk-bounding-P04-S19]]'
  - '[[2026-07-23-document-chunk-bounding-P04-S20]]'
  - '[[2026-07-23-document-chunk-bounding-adr]]'
  - '[[2026-07-23-document-chunk-bounding-plan]]'
  - '[[2026-07-23-document-chunk-bounding-research]]'
---

# `document-chunk-bounding` feature index

Auto-generated index of all documents tagged with `#document-chunk-bounding`.

## Documents

### adr

- `2026-07-23-document-chunk-bounding-adr` - `document-chunk-bounding` adr: `bound hook-emitted document units and enforce the CUDA ceiling on demand` | (**status:** `accepted`)

### exec

- `2026-07-23-document-chunk-bounding-P01-S01` - add an explicit maximum length to the unit text field so the schema stops advertising an unbounded payload
- `2026-07-23-document-chunk-bounding-P01-S02` - derive the character split budget from the dense model sequence window by a declared chars-per-token ratio instead of a literal
- `2026-07-23-document-chunk-bounding-P01-S03` - route hook-emitted unit text through the shared bounded splitter in the units branch
- `2026-07-23-document-chunk-bounding-P01-S04` - carry title, section, anchor, locator, and unit metadata onto every fragment produced from one unit
- `2026-07-23-document-chunk-bounding-P01-S05` - give the document splitter configuration a non-zero overlap so a fragment boundary does not sever context
- `2026-07-23-document-chunk-bounding-P02-S06` - add a fragment discriminator to the location component so it applies to both the locator and unit-ordinal identity branches
- `2026-07-23-document-chunk-bounding-P02-S07` - bump the document identity version because the derivation changes for units that split
- `2026-07-23-document-chunk-bounding-P02-S08` - pass the fragment discriminator from chunk construction into point identity derivation
- `2026-07-23-document-chunk-bounding-P02-S09` - add a guard test driving a multi-page locator-bearing unit through the splitter and asserting every fragment id is distinct
- `2026-07-23-document-chunk-bounding-P02-S10` - add a test asserting fragment ids are stable across a repeated run of an unchanged unit so ledger replay stays idempotent
- `2026-07-23-document-chunk-bounding-P03-S11` - remove the reserved high-water comparison from ceiling enforcement leaving the allocated comparison as the sole gate
- `2026-07-23-document-chunk-bounding-P03-S12` - keep sampling and reporting reserved on job resilience records and metrics as a diagnostic
- `2026-07-23-document-chunk-bounding-P03-S13` - release the allocator cache immediately before rebasing peak counters so a job's peaks describe that job
- `2026-07-23-document-chunk-bounding-P03-S14` - update the budget class contract prose to state that allocated alone gates and reserved is reported
- `2026-07-23-document-chunk-bounding-P04-S15` - fold the unit text bound and the splitting parameters into the document content epoch so a bound change triggers rebuild
- `2026-07-23-document-chunk-bounding-P04-S16` - prove the fragment-id uniqueness guard fails against the pre-fix identity construction and record both directions
- `2026-07-23-document-chunk-bounding-P04-S17` - prove the unit text maximum-length rejection fails when the bound is removed and record both directions
- `2026-07-23-document-chunk-bounding-P04-S18` - add a test asserting a unit above the token window yields multiple fragments rather than one truncated chunk
- `2026-07-23-document-chunk-bounding-P04-S19` - add a test asserting a reserved high-water above the ceiling no longer fails a job while an allocated high-water above it still does
- `2026-07-23-document-chunk-bounding-P04-S20` - run the full unit suite and the citation-gate lint over every changed file

### plan

- `2026-07-23-document-chunk-bounding-plan` - `document-chunk-bounding` plan

### research

- `2026-07-23-document-chunk-bounding-research` - `document-chunk-bounding` research: `unbounded hook-emitted document units and the reserved-memory ceiling guard`
