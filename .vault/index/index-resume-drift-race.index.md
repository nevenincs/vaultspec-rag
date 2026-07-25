---
generated: true
tags:
  - '#index'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - '[[2026-07-25-index-resume-drift-race-W01-P01-S01]]'
  - '[[2026-07-25-index-resume-drift-race-W01-P01-S02]]'
  - '[[2026-07-25-index-resume-drift-race-W01-P01-S15]]'
  - '[[2026-07-25-index-resume-drift-race-W01-P02-S03]]'
  - '[[2026-07-25-index-resume-drift-race-W02-P03-S07]]'
  - '[[2026-07-25-index-resume-drift-race-adr]]'
  - '[[2026-07-25-index-resume-drift-race-plan]]'
  - '[[2026-07-25-index-resume-drift-race-research]]'
---

# `index-resume-drift-race` feature index

Auto-generated index of all documents tagged with `#index-resume-drift-race`.

## Documents

### adr

- `2026-07-25-index-resume-drift-race-adr` - `index-resume-drift-race` adr: `seam the codebase indexer and give drift a single owner` | (**status:** `accepted`)

### exec

- `2026-07-25-index-resume-drift-race-W01-P01-S01` - Capture the behavioural baseline: run the full suite and record the passing count and the per-module test inventory that the extractions must preserve
- `2026-07-25-index-resume-drift-race-W01-P01-S02` - Sweep the indexer for duplicate behaviour with vaultspec-rag semantic search before any extraction, recording each duplicate pair so extraction collapses it rather than carrying both across the seam
- `2026-07-25-index-resume-drift-race-W01-P01-S15` - Cover the drift-detection predicate with direct tests before it moves across a seam, since it currently has no test of its own and only its remedy is exercised
- `2026-07-25-index-resume-drift-race-W01-P02-S03` - Extract discovery and admission into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned
- `2026-07-25-index-resume-drift-race-W02-P03-S07` - Give the indexed-path upsert collision its own exception type so a racing path is distinguishable from a genuine invariant breach

### plan

- `2026-07-25-index-resume-drift-race-plan` - `index-resume-drift-race` plan

### research

- `2026-07-25-index-resume-drift-race-research` - `index-resume-drift-race` research: `resumed index over a moving tree aborts on the indexed-path upsert guard`
