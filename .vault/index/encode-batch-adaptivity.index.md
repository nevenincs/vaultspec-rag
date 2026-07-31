---
generated: true
tags:
  - '#index'
  - '#encode-batch-adaptivity'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
related:
  - '[[2026-07-29-encode-batch-adaptivity-P01-S01]]'
  - '[[2026-07-29-encode-batch-adaptivity-P01-S02]]'
  - '[[2026-07-29-encode-batch-adaptivity-P01-S03]]'
  - '[[2026-07-29-encode-batch-adaptivity-P01-S04]]'
  - '[[2026-07-29-encode-batch-adaptivity-P01-S05]]'
  - '[[2026-07-29-encode-batch-adaptivity-P01-S06]]'
  - '[[2026-07-29-encode-batch-adaptivity-P01-S07]]'
  - '[[2026-07-29-encode-batch-adaptivity-P01-S08]]'
  - '[[2026-07-29-encode-batch-adaptivity-P01-summary]]'
  - '[[2026-07-29-encode-batch-adaptivity-P02-S09]]'
  - '[[2026-07-29-encode-batch-adaptivity-P02-S10]]'
  - '[[2026-07-29-encode-batch-adaptivity-P02-S11]]'
  - '[[2026-07-29-encode-batch-adaptivity-P02-S12]]'
  - '[[2026-07-29-encode-batch-adaptivity-P02-S13]]'
  - '[[2026-07-29-encode-batch-adaptivity-P02-S14]]'
  - '[[2026-07-29-encode-batch-adaptivity-P02-S15]]'
  - '[[2026-07-29-encode-batch-adaptivity-P02-summary]]'
  - '[[2026-07-29-encode-batch-adaptivity-adr]]'
  - '[[2026-07-29-encode-batch-adaptivity-audit]]'
  - '[[2026-07-29-encode-batch-adaptivity-final-branch-review-audit]]'
  - '[[2026-07-29-encode-batch-adaptivity-plan]]'
  - '[[2026-07-29-encode-batch-adaptivity-research]]'
---

# `encode-batch-adaptivity` feature index

Auto-generated index of all documents tagged with `#encode-batch-adaptivity`.

## Documents

### adr

- `2026-07-29-encode-batch-adaptivity-adr` - `encode-batch-adaptivity` adr: `token-budget encode batching with sub-batch retry and encode-stage truth` | (**status:** `accepted`)

### audit

- `2026-07-29-encode-batch-adaptivity-audit` - `encode-batch-adaptivity` audit: `feature branch review, token-budget encode core and degradation truth`
- `2026-07-29-encode-batch-adaptivity-final-branch-review-audit` - `encode-batch-adaptivity` audit: `final branch review before pull request`

### exec

- `2026-07-29-encode-batch-adaptivity-P01-S01` - implement the token-estimate bucket planner partitioning length-sorted texts under a token budget with the chars-per-token calibration constant and the item-count cap
- `2026-07-29-encode-batch-adaptivity-P01-S02` - re-denominate the learned encode ceiling from item count to token footprint, recording the failing footprint on OOM and probing recovery in token units
- `2026-07-29-encode-batch-adaptivity-P01-S03` - rework the dense encode output path to execute one library encode call per planned bucket, retaining completed bucket outputs and scoping OOM discard, split, and cache flush to the failing bucket
- `2026-07-29-encode-batch-adaptivity-P01-S04` - adopt the bucket planner and token ceiling on the sparse encode path through the shared ceiling class
- `2026-07-29-encode-batch-adaptivity-P01-S05` - move the GPU-lock bracket from the whole-slice encode to per-bucket forward holds in the slice vector-field encoder
- `2026-07-29-encode-batch-adaptivity-P01-S06` - add the encode token-budget and calibration settings with derivation defaults
- `2026-07-29-encode-batch-adaptivity-P01-S07` - wire the new encode settings through the env-var schema map
- `2026-07-29-encode-batch-adaptivity-P01-S08` - author bucket-planner and token-ceiling unit tests plus the bucket-scoped OOM retry guard proven able to fail on slice-scoped regression
- `2026-07-29-encode-batch-adaptivity-P01-summary` - `encode-batch-adaptivity` `P01` summary
- `2026-07-29-encode-batch-adaptivity-P02-S09` - emit per-bucket sub-slice progress and live token-budget state through the forward-entry and forward-exit runtime reporting
- `2026-07-29-encode-batch-adaptivity-P02-S10` - carry the per-job OOM counter and encode budget state on the job record runtime block
- `2026-07-29-encode-batch-adaptivity-P02-S11` - enrich the jobs projection with the encode budget fields and a recent-rate-versus-run-median baseline
- `2026-07-29-encode-batch-adaptivity-P02-S12` - add the rate-vs-self-baseline degraded input to the service degradation verdict with ceiling state attached as evidence
- `2026-07-29-encode-batch-adaptivity-P02-S13` - extend degradation evidence assembly with encode budget, OOM count, and rate-baseline lines
- `2026-07-29-encode-batch-adaptivity-P02-S14` - render the encode budget, OOM, and rate-baseline evidence in the jobs presentation and TUI detail
- `2026-07-29-encode-batch-adaptivity-P02-S15` - author degradation rate-baseline verdict tests proven able to fail when the baseline input is removed
- `2026-07-29-encode-batch-adaptivity-P02-summary` - `encode-batch-adaptivity` `P02` summary

### plan

- `2026-07-29-encode-batch-adaptivity-plan` - `encode-batch-adaptivity` plan

### research

- `2026-07-29-encode-batch-adaptivity-research` - `encode-batch-adaptivity` research: `encode tail throughput collapse: remediation pathways`
