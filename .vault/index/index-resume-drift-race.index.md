---
generated: true
tags:
  - '#index'
  - '#index-resume-drift-race'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - '[[2026-07-25-index-resume-drift-race-W01-P01-S01]]'
  - '[[2026-07-25-index-resume-drift-race-W01-P01-S02]]'
  - '[[2026-07-25-index-resume-drift-race-W01-P01-S15]]'
  - '[[2026-07-25-index-resume-drift-race-W01-P01-S16]]'
  - '[[2026-07-25-index-resume-drift-race-W01-P02-S03]]'
  - '[[2026-07-25-index-resume-drift-race-W01-P02-S04]]'
  - '[[2026-07-25-index-resume-drift-race-W01-P02-S05]]'
  - '[[2026-07-25-index-resume-drift-race-W01-P02-S06]]'
  - '[[2026-07-25-index-resume-drift-race-W02-P03-S07]]'
  - '[[2026-07-25-index-resume-drift-race-W02-P03-S08]]'
  - '[[2026-07-25-index-resume-drift-race-W02-P04-S09]]'
  - '[[2026-07-25-index-resume-drift-race-W02-P04-S10]]'
  - '[[2026-07-25-index-resume-drift-race-W03-P05-S12]]'
  - '[[2026-07-25-index-resume-drift-race-W03-P06-S13]]'
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
- `2026-07-25-index-resume-drift-race-W01-P01-S16` - Repair the test construction pattern that bypasses the indexer constructor, so a collaborator can be held as constructor state instead of rebuilt per access
- `2026-07-25-index-resume-drift-race-W01-P02-S03` - Extract discovery and admission into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned
- `2026-07-25-index-resume-drift-race-W01-P02-S04` - Extract chunk production and submission into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned
- `2026-07-25-index-resume-drift-race-W01-P02-S05` - Extract generation and ledger lifecycle into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned
- `2026-07-25-index-resume-drift-race-W01-P02-S06` - Extract drift ownership into its own collaborator that holds the drop-points-then-remove-units ordering as a property of the type
- `2026-07-25-index-resume-drift-race-W02-P03-S07` - Give the indexed-path upsert collision its own exception type so a racing path is distinguishable from a genuine invariant breach
- `2026-07-25-index-resume-drift-race-W02-P03-S08` - Add the cheap pre-record drift re-check that keeps the common case off the signal path entirely
- `2026-07-25-index-resume-drift-race-W02-P04-S09` - Route the drift signal to the drift owner so it supersedes the racing path and the run re-records it instead of aborting
- `2026-07-25-index-resume-drift-race-W02-P04-S10` - Bound the per-path retry and defer on exhaustion, emitting a warning that names the path and the exhausted budget
- `2026-07-25-index-resume-drift-race-W03-P05-S12` - Turn the module-length gate from advisory to failing at a threshold the post-seam tree actually meets, and record the full offender census in the same change so the remaining ratchet is visible rather than implied
- `2026-07-25-index-resume-drift-race-W03-P06-S13` - Prove the upsert guard bidirectionally: permit the forbidden write, watch the test fail on its own assertion, restore, watch it pass, and record both directions

### plan

- `2026-07-25-index-resume-drift-race-plan` - `index-resume-drift-race` plan

### research

- `2026-07-25-index-resume-drift-race-research` - `index-resume-drift-race` research: `resumed index over a moving tree aborts on the indexed-path upsert guard`
