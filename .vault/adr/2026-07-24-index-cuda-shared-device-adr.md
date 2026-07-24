---
tags:
  - '#adr'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - "[[2026-07-24-index-cuda-shared-device-research]]"
  - "[[2026-07-24-index-cuda-ceiling-adr]]"
---

# `index-cuda-shared-device` adr: `derive the ceiling from free device memory and drop the runtime peak from corpus admission` | (**status:** `accepted`)

## Problem Statement

The CUDA-ceiling fix proved out under S19 but the same run surfaced two residual
gaps in the indexing memory model, both grounded in
`2026-07-24-index-cuda-shared-device-research`: the auto-derived ceiling is
computed from total device memory rather than free, so it overstates capacity on
a shared GPU; and the codebase indexer rejects the runtime CUDA allocated peak as
a corpus-sizing dimension, over-refusing a legitimate forward on the small
profile. A decision is needed now because both landed with the just-shipped
ceiling work, one is a correctness gap in that work, and the corpus-dimension
rejection actively blocks indexing on the `embedded-local` profile.

## Considerations

- Runtime CUDA allocation is already governed by the per-job forward-peak capture
  and the allocator OOM backoff shipped in `2026-07-24-index-cuda-ceiling-adr`,
  so a second, static-looking runtime check is redundant.
- The desktop/other-process GPU baseline is variable, not a constant that a fixed
  headroom could cover (`2026-07-24-index-cuda-shared-device-research`).
- The device-memory probes must stay guarded and torch-tolerant on the read-only
  paths (`torch-loads-through-centralized-gpu-gate`) and must not pull torch into
  a spawn worker (`index-workers-stay-cpu-only`).
- The bidirectional operator override on the ceiling is an existing affordance
  that must survive unchanged.
- The static corpus dimensions (source files, chunks, weighted/extracted bytes)
  remain the honest admission gate and are not in question.

## Considered options

Ceiling derivation:

- **Derive an ABSOLUTE ceiling from free plus the resident baseline, clamped
  below total-minus-headroom.** The enforcement subtracts the baseline from both
  the captured peak and the ceiling, so the ceiling must be absolute (inclusive
  of the resident models); free measured after the models are resident already
  excludes them, so the baseline is added back:
  `min(baseline + free - headroom, total - headroom)`. A contended device lowers
  the ceiling toward reality; an idle one recovers the current value. Chosen. A
  naive `min(free - headroom, total - headroom)` was rejected in review: used as
  an absolute ceiling it double-subtracts the models (once inside free, once via
  the baseline-net comparison) and re-rejects legitimate forwards - the exact
  defect this feature exists to remove, mirrored from the opposite side.
- **Subtract a larger fixed headroom from total to "cover" the desktop.** No
  constant is right, because the baseline varies with the remote session, browser,
  and any second GPU app. Rejected.
- **Leave the derivation on total and rely on the OOM backoff.** Keeps the
  pre-emptive guard lying about capacity; the backoff becomes the only real
  protection, defeating the fail-fast intent. Rejected.

Corpus CUDA dimension (code path only):

- **Remove the runtime CUDA peak from the corpus-sizing rejection in the code
  indexer, matching the document indexer, which already treats it as a diagnostic
  counter and never rejects on it.** Runtime memory is not corpus size and is
  already enforced by the ceiling and per-job capture. The measurement field and
  its JSON reporting stay; only the rejection is removed. Chosen.
- **Keep the hard rejection.** Over-refuses legitimate work on the small profile
  and duplicates the runtime guard. Rejected.

## Constraints

- Free memory is a point-in-time reading. It must be sampled after the resident
  models are loaded AND after the per-job admission cache flush (empty_cache), so
  the reading excludes only genuinely-pinned memory and is not depressed by this
  process's own allocator retention - the reserved-ratchet history that the
  codified guard forbids from deciding job outcome. The two indexers currently
  derive the ceiling on opposite sides of that flush (the code path derives
  before its reset, the document path after); both must sample after it.
- The ceiling is derived at three sites - the two indexer budget builders and the
  admission snapshot in dispatch. Only the two budget builders enforce; the
  dispatch snapshot is reported and persisted and is a point-in-time diagnostic
  that may legitimately differ from the later per-job enforcing value. The record
  accepts that divergence rather than forcing the admission snapshot to match.
- `mem_get_info` runs only on the GPU compute path behind the existing guard; the
  torch-free service-client and worker paths never reach it and keep their
  profile fallback.
- Removing the CUDA dimension from `exceeded_by` must not disturb the other
  dimensions' ordering or messages; the change is scoped to the one dimension.
- No parent feature is unstable: the ceiling and per-job capture this builds on
  are landed, reviewed, and S19-verified.

## Implementation

The device probe gains a guarded free-memory reading from `mem_get_info`. The
auto ceiling becomes an ABSOLUTE figure - `min(baseline + free - headroom,
total - headroom)` - where `baseline` is the resident-model allocation the budget
already tracks and `free` is sampled after models are resident and after the
admission cache flush. Adding the baseline back is what keeps the result
absolute: because enforcement subtracts the baseline from both the peak and the
ceiling, a free reading that already excludes the models must have them restored,
or the models are charged twice. Off the GPU path the reading is unavailable and
the profile fallback stands, exactly as today; the operator override remains
authoritative above the derived value. The derivation moves to run after the
per-job `empty_cache` at both budget-building sites so allocator retention does
not depress `free`, and the two indexers' currently-opposite orderings are
reconciled to that.

The codebase indexer's support measurement stops treating the runtime CUDA peak
as a corpus dimension: `cuda_bytes` is dropped from the set `exceeded_by`
rejects on, so a job is never refused as `corpus_limit_exceeded` for a runtime
allocation the ceiling and per-job capture already govern. The document indexer
needs no change here - it already retains the projected `cuda_bytes` as a
diagnostic counter only and never feeds it back through the corpus rejection - so
this is a code-path change that brings the code indexer to match the document
indexer. The measurement field and its JSON reporting are kept on both; only the
code path's rejection is removed.

## Rationale

Deriving from free wins on the knockout that a ceiling above actual free memory
does not protect anything - it admits work the device cannot hold, leaving only
the backoff, which is the failure mode the pre-emptive ceiling exists to prevent
(`2026-07-24-index-cuda-shared-device-research`). Free memory measures the real
remainder directly where any fixed headroom is guaranteed wrong on a variable
baseline, and the total-minus-headroom clamp preserves today's behaviour on an
idle device so the change only ever tightens toward reality.

Removing the corpus CUDA dimension wins because the quantity was miscategorised:
it is a runtime peak wearing a corpus-size label, and the runtime guard that
should own it now exists and is verified. Deleting the duplicate removes a false
rejection without removing any real protection.

## Consequences

Indexing admits correctly on a contended shared GPU - the ceiling tracks free
memory instead of overstating it - and the `embedded-local` profile stops
refusing legitimate forwards as corpus-limit failures. The two indexers agree on
how runtime CUDA memory is treated.

The absolute-ceiling arithmetic is the sharp edge and must be pinned by a guard
test: the free-derived value has the baseline added back precisely so the
existing baseline-net enforcement does not subtract the models twice, and a test
must fail if the derivation reverts to a bare `free - headroom` (which would
re-reject a legitimate net forward on a contended device). This is the same
double-count the sibling ceiling work guards against, approached from the free
side.

The costs are modest and honest. A free-based ceiling is only as current as its
sampling point; if the desktop baseline grows sharply after sampling, the ceiling
can again sit above free, and the OOM backoff remains the final net - this change
narrows that window rather than closing it absolutely, which is the ceiling's
nature as a coarse guard. Dropping the corpus CUDA dimension means a genuinely
oversized runtime allocation is caught by the ceiling and backoff rather than
pre-emptively at corpus admission; that is the correct owner, but it moves the
detection point later. The multi-tenant case - several roots' jobs competing for
one device's free memory - is explicitly not addressed here and remains the
province of the sibling quiesce work.
