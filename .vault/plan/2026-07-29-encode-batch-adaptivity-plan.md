---
tags:
  - '#plan'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_hash: 'sha256:93295b9aee85bb3697068886d3458b46f91e7e05d87aaba2c4a50b739668ffdf'
tier: L2
related:
  - '[[2026-07-29-encode-batch-adaptivity-adr]]'
  - '[[2026-07-29-encode-batch-adaptivity-research]]'
---

# `encode-batch-adaptivity` plan

### Phase `P01` - token-budget bucket core

Deliver the bucket planner, the token-denominated learned ceiling, per-bucket encode execution with bucket-scoped OOM retry, and per-bucket GPU-lock holds.

- [x] `P01.S01` - implement the token-estimate bucket planner partitioning length-sorted texts under a token budget with the chars-per-token calibration constant and the item-count cap; `src/vaultspec_rag/embeddings.py`.
- [x] `P01.S02` - re-denominate the learned encode ceiling from item count to token footprint, recording the failing footprint on OOM and probing recovery in token units; `src/vaultspec_rag/embeddings.py`.
- [x] `P01.S03` - rework the dense encode output path to execute one library encode call per planned bucket, retaining completed bucket outputs and scoping OOM discard, split, and cache flush to the failing bucket; `src/vaultspec_rag/embeddings.py`.
- [x] `P01.S04` - adopt the bucket planner and token ceiling on the sparse encode path through the shared ceiling class; `src/vaultspec_rag/embeddings.py`.
- [x] `P01.S05` - move the GPU-lock bracket from the whole-slice encode to per-bucket forward holds in the slice vector-field encoder; `src/vaultspec_rag/indexer/_streaming.py`.
- [x] `P01.S06` - add the encode token-budget and calibration settings with derivation defaults; `src/vaultspec_rag/config/_settings.py`.
- [x] `P01.S07` - wire the new encode settings through the env-var schema map; `src/vaultspec_rag/config/_schema.py`.
- [x] `P01.S08` - author bucket-planner and token-ceiling unit tests plus the bucket-scoped OOM retry guard proven able to fail on slice-scoped regression; `src/vaultspec_rag/tests/test_encode_bucket_planner.py`.

### Phase `P02` - encode-stage telemetry and degradation truth

Publish sub-slice progress, token-budget and OOM telemetry through the jobs projection, and add the rate-vs-self-baseline degradation input with its evidence and presentation.

- [x] `P02.S09` - emit per-bucket sub-slice progress and live token-budget state through the forward-entry and forward-exit runtime reporting; `src/vaultspec_rag/indexer/_streaming.py`.
- [x] `P02.S10` - carry the per-job OOM counter and encode budget state on the job record runtime block; `src/vaultspec_rag/jobs.py`.
- [x] `P02.S11` - enrich the jobs projection with the encode budget fields and a recent-rate-versus-run-median baseline; `src/vaultspec_rag/server/_routes_jobs.py`.
- [x] `P02.S12` - add the rate-vs-self-baseline degraded input to the service degradation verdict with ceiling state attached as evidence; `src/vaultspec_rag/server/_routes_jobs.py`.
- [x] `P02.S13` - extend degradation evidence assembly with encode budget, OOM count, and rate-baseline lines; `src/vaultspec_rag/jobs.py`.
- [x] `P02.S14` - render the encode budget, OOM, and rate-baseline evidence in the jobs presentation and TUI detail; `src/vaultspec_rag/cli/_service_jobs_presentation.py`.
- [x] `P02.S15` - author degradation rate-baseline verdict tests proven able to fail when the baseline input is removed; `src/vaultspec_rag/tests/test_jobs_degradation.py`.

## Description

Executes the accepted decision to replace count-based encode batching with
token-budget bucket planning, scope OOM retry to a single bucket, and surface
encode-stage truth through the jobs projection. Phase `P01` delivers the encode
core: the planner, the token-denominated learned ceiling shared by the dense and
sparse paths, per-bucket library encode calls with bucket-scoped OOM handling,
per-bucket GPU-lock holds, and the settings surface. Phase `P02` delivers the
observability half: per-bucket sub-slice progress through the forward runtime
block, encode budget and OOM state on the job record, projection enrichment, the
rate-vs-self-baseline degradation input with evidence, presentation, and the
verdict guard tests. Both phases are governed by the single authorizing ADR in
`related:`; the research document carries the incident evidence and pathway
comparison.

## Steps

Structured above as two Phase blocks per the L2 tier; the leaf rows are the
canonical Step records.

## Parallelization

`P01.S01` through `P01.S04` are one cohesive hard-reasoning lane over
`src/vaultspec_rag/embeddings.py` and execute strictly in order within one
executor. `P01.S05` depends on `P01.S03`; `P01.S06` and `P01.S07` may proceed in
parallel with the encode work once the knob names are fixed by `P01.S01`;
`P01.S08` closes the phase. In `P02`, steps `S10` through `S15` are independent
of `P01` and may run in parallel with it in a separate executor lane; `P02.S09`
alone depends on the bucket-loop callback seam defined in `P01.S03` and executes
after it. The two file-sharing edges (`src/vaultspec_rag/indexer/_streaming.py`
touched by `P01.S05` and `P02.S09`; `src/vaultspec_rag/jobs.py` touched by
`P02.S10` and `P02.S13`) are serialized within their lane to avoid concurrent
edits to one file.

## Verification

- The bucket-scoped OOM retry guard fails when retry scope regresses to the
  slice, and passes restored - both directions recorded in the Step Record.
- The rate-baseline verdict test fails when the baseline input is removed from
  the degradation classifier, and passes restored.
- Lint, format, type-check, and the test files named in the Step rows pass on
  the touched paths before every commit; commits use explicit pathspecs.
- A live incremental code index of a long-chunk corpus completes with zero
  whole-slice re-encodes (OOM counter telemetry shows bucket-scoped retries
  only), and sub-slice progress advances between slice boundaries on the jobs
  surface.
- A run whose chunk rate is artificially collapsed reports `degraded` with
  encode budget evidence instead of `healthy`.
- The plan is complete when every Step row above is closed and the
  vaultspec-code-review audit for the feature is clean.
