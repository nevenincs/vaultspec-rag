---
tags:
  - '#audit'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-code-document-index-boundary-adr]]"
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# `code-document-index-boundary` audit: `p06 resource bounds`

## Scope

Reviewed the `W03.P06` implementation commits `5b4f20fc`, `c6d6e971`,
`0ce5527e`, and `6ac06a56` against decisions D2, D5, and D8 in the approved
architecture decision and steps S38-S46 and S107 in the implementation plan.
The review covered source admission and decoding, extractor subprocess bounds,
failure convergence, document resource accounting, cancellation, service job
admission, retry ownership, and the focused real-behavior tests.

## Findings

### p06-resource-bounds | high | Raw document paths retain the complete source in memory

`_stream_source` appends every block to a `bytearray` whenever `retain_bytes`
is true. `chunk_document_and_hash_file` selects that mode for both documents
without an extractor and extractor passthrough, while the named document
profile permits aggregate source ceilings of tens or hundreds of GiB. A single
explicitly admitted document can therefore exhaust process RSS before generated
chunk or weighted-byte admission runs. The same streaming loop has no run-control
checkpoint, so cancellation is not observed while the source is read. This
violates D8 and S42/S44's bounded, interruptible source processing requirement.

### p06-resource-bounds | high | Failed code preprocessing still publishes a converged hash

`CodebaseIndexer._enqueue_code_result` writes the file's content hash into the
publication metadata before recording its preprocessing disposition and before
any segment is confirmed. A skipped extractor result, or an undecodable admitted
source that produces no chunks, can consequently publish a stable hash despite
having produced no indexed content. A subsequent incremental run sees that hash
as unchanged and need not retry the source. This is the exact non-success
convergence prohibited by D5 and S40.

### p06-resource-bounds | medium | Document admission omits cancellation checkpoints

`_run_code_attempt` checkpoints immediately before and after model-free policy
and support-profile admission. `_run_document_attempt` performs the analogous
full-tree document preflight without either checkpoint and then loads the model.
A cancellation requested during document discovery or source-size measurement
is therefore not acknowledged before GPU/model work begins. The admission scan
itself also uses synchronous file status calls without cooperative checkpoints.

### p06-resource-bounds | medium | The named document profile omits required resource dimensions

`SupportProfileLimits` declares only source files, source bytes, generated
chunks, and one combined weighted-byte value. It does not independently declare
or report extracted bytes, queue bytes, RSS, or CUDA ceilings required by D8.
The runtime weighted budget is useful, but it cannot establish which of those
independent support dimensions was admitted, measured, or exceeded.

### p06-resource-bounds | medium | Extractors have a wall timeout but no no-progress watchdog

The subprocess polling path checks cancellation and total elapsed time only.
Pipe readers deliberately drain output without updating a progress clock, and
batch execution merely scales the wall timeout up to its hard cap. An extractor
that emits or computes without producing a valid completion is bounded by the
wall timeout, but the distinct no-progress bound required by D8 and S44 is not
implemented or verified.

### p06-resource-bounds | medium | Focused tests do not exercise failed code convergence

The document failure test correctly proves that a failed document extractor is
retried on the next run. The code failure tests assert only the first run's skip
count and diagnostic; they do not execute a second unchanged incremental run or
inspect published hash metadata. That leaves the high-severity code convergence
regression above undetected by S46's claimed failure-visibility coverage.

## Recommendations

1. Replace whole-source retention with bounded streaming decode/chunk input, or
   enforce a separately declared safe per-file RSS ceiling before allocating;
   checkpoint between read blocks.
1. Publish code hashes only from durable indexed file states or explicit stable
   policy rejections. Keep skipped extraction, decode failure, I/O failure, and
   other retryable outcomes unresolved and retain their reasons.
1. Thread run control through document discovery, source measurement, and hash
   loops, and checkpoint on both sides of admission before model loading.
1. Expand the named profile and status surface to distinct extracted, queue,
   RSS, and CUDA dimensions, with enforcement at the earliest measurable edge.
1. Add a no-progress clock to extractor execution and real-process coverage for
   a child that stays alive without advancing valid output.
1. Add a two-run code extraction failure test proving that unchanged failed
   input is attempted again and never appears in converged hash metadata.

## Remediation re-review

Status: cleared on `main`.

The exact remediation diffs `3257d2b2`, `c1329d87`, `2b4ebff7`, and
`be196f7b` were re-reviewed against all six findings above.

- Production document ingestion now streams raw and passthrough content in
  bounded blocks, checkpoints reads, and verifies the source digest before
  completing publication.
- Failed or empty code preprocessing records an unresolved typed file state and
  raises before metadata publication. The unchanged source is retried in the
  same durable generation.
- Document discovery, scoped normalization, policy classification, and support
  measurement now consume the real run-control token and checkpoint within the
  scan as well as on both sides of admission.
- Named profiles, admission responses, and runtime document enforcement cover
  source, extracted, chunk, weighted queue, RSS, and CUDA dimensions
  independently.
- Extractor polling consumes the production no-progress clock and terminates a
  non-advancing child with a typed timeout.
- Real-process coverage proves bounded raw-source memory, cooperative
  cancellation, admission cancellation, child termination, independent runtime
  ceilings, and two-run non-convergence after extraction failure.

Verification completed with scoped Ruff and Ty checks plus the ten-test
real-process P06 boundary. All ten tests passed. No high, medium, or low finding
remains open from this audit.
