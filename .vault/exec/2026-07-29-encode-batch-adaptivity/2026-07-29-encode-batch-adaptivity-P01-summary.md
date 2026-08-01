---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:bd13335fdba2c5d0a8bee8ba01273361ea3a471675f58383efc3a4eab0a05a1a'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# `encode-batch-adaptivity` `P01` summary

All eight Steps closed. The Phase replaced count-based encode batching with
token-budget bucket planning across both the dense and sparse encode paths, and
converted the OOM backoff from a whole-slice ladder into a bucket-scoped retry.

- Modified: `src/vaultspec_rag/embeddings.py`
- Modified: `src/vaultspec_rag/indexer/_streaming.py`
- Modified: `src/vaultspec_rag/config/_settings.py`
- Modified: `src/vaultspec_rag/config/_schema.py`
- Modified: `src/vaultspec_rag/config/_types.py`
- Modified: `src/vaultspec_rag/tests/test_encode_hygiene_unit.py`
- Modified: `src/vaultspec_rag/tests/test_adr_regression.py`
- Created: `src/vaultspec_rag/tests/test_encode_bucket_planner.py`

## Description

A pure, torch-free bucket planner partitions an already length-sorted slice into
contiguous sub-batches whose estimated token footprint (items times the bucket's
padded per-item estimate) stays under a budget, capped by the existing item
count. The learned encode ceiling was re-denominated from item count to token
footprint: an OOM records the failing bucket's footprint, halves it, and returns
the new budget so the caller replans without a second probe; recovery doubles a
token number rather than an item count, which is what removes the regime
mismatch that let a ceiling learned on short chunks fail on long ones.

Each bucket now runs as exactly one library encode call, so no tokenise, forward
or pool loop is mirrored in this codebase. An OOM discards only the failing
bucket and the unstarted tail, retains every completed bucket's output, and
flushes the allocator only on a genuine OOM; a single-item bucket re-raises,
which is the floor that makes the retry provably terminate. The sparse path uses
the same planner, the same shared ceiling, and one shared replan implementation,
so no count-denominated remnant survives. The GPU lock moved from wrapping the
whole slice encode to wrapping each bucket's forward, which also shortens the
worst-case wait a concurrent search sees during indexing.

Two settings carry the new surface: a token budget and a chars-per-token
calibration constant. The calibration was fixed by measurement rather than
assumption, after a review found the first value contradicted the project's own
deliberately conservative chunking divisor in the unsafe direction. Measured
against the pinned dense tokenizer, ordinary source runs about 3.8 characters
per token and prose about 6, while digit tables reach the 1.0 floor because the
tokenizer splits every digit. The divisor is therefore 3, equal to the document
chunking divisor, and the guard that pins it states its margin explicitly: one
re-clamp halves the planning budget, so two absorb a fourfold under-plan, and
the margin sits below that bound so drift is caught while the measured worst
case still costs at most two discarded buckets.

Verification: every gate ran alone with its exit code captured separately;
all green at each commit. Three guards were proven able to fail and restored in
one uninterrupted sequence each - the dense and sparse bucket-scoped retry
guards, which fail on their call-log assertion when retry scope regresses to the
slice, and the calibration guard, which fails naming the offending corpus text
and its measured factor when the divisor is loosened. The OOM floor guard was
repointed from a retired string scan to an AST check that locates every CUDA-OOM
handler and requires a conditional bare re-raise in each, with a staleness
tripwire so the scan cannot silently rot to zero matches; it too was proven to
fail, reporting the mutated handler by line number.
