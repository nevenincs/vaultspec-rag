---
tags:
  - '#adr'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
related:
  - "[[2026-07-29-encode-batch-adaptivity-research]]"
  - "[[2026-07-28-index-observability-adr]]"
  - "[[2026-07-24-index-throughput-adr]]"
  - "[[2026-07-24-index-cuda-ceiling-adr]]"
  - "[[2026-07-24-index-cuda-shared-device-adr]]"
---

# `encode-batch-adaptivity` adr: `token-budget encode batching with sub-batch retry and encode-stage truth` | (**status:** `accepted`)

## Problem Statement

Encode throughput collapses by an order of magnitude when a fixed-count encode
batch collides with the CUDA ceiling: the OOM backoff halves a learned batch
ceiling that then oscillates - climbing back, re-colliding, discarding a full
slice forward and flushing the allocator on every cycle - while the degradation
verdict reads `healthy` throughout (`2026-07-29-encode-batch-adaptivity-research`).
The count-based batch is the root defect: its token footprint is unbounded, so no
per-count ceiling can be simultaneously safe for long-chunk slices and efficient
for short-chunk ones. A decision is needed on how encode batches are sized, what
an OOM costs, and what truth the encode stage owes the jobs surface.

## Considerations

- Activation memory scales with items × padded sequence length; a count ceiling
  learned on one length regime is wrong for every other
  (`2026-07-29-encode-batch-adaptivity-research`).
- The OOM ladder's retry unit is the whole slice (up to 512 chunks), so one OOM
  discards minutes of completed GPU work (research, retry-granularity finding).
- The canonical-code rule forbids mirroring library logic: a hand-rolled
  tokenize/forward/pool loop would duplicate `sentence-transformers` behaviour
  and drift; `sentence-transformers>=5.0` is the pinned encode surface.
- GPU rules are invariant: one consumer thread; the GPU lock brackets forward
  passes only; slice chunks arrive already length-sorted.
- The index-observability record rejected sub-batching the encode call *as a
  progress heartbeat*, on padding-efficiency and cadence-coupling grounds; its
  verdict mechanism and jobs-projection contract are accepted and shipped.
- The service-surface rule requires encode telemetry to live in the service
  domain and reach CLI, TUI, and MCP through the one existing projection.
- The derived absolute CUDA ceiling and baseline-net enforcement
  (index-cuda-ceiling, index-cuda-shared-device) stay authoritative; this
  decision operates inside the headroom they define.

## Considered options

- **Token-budget bucket planning over per-bucket library encode calls, with the
  learned ceiling re-denominated in tokens and OOM retry scoped to one bucket.**
  Pro: bounds activation memory by construction, makes the ceiling regime-aware
  with one number, caps OOM waste at one bucket, keeps the library owning
  tokenise/forward/pool. Con: needs a chars-to-tokens estimate for planning and
  a calibration guard. CHOSEN.
- **Fully custom encode loop (own tokenise/forward/pool).** Maximum control and
  the same memory bound, but duplicates library behaviour the canonical-code
  rule forbids and adds permanent divergence risk for marginal gain over
  per-bucket calls. Rejected.
- **Ceiling hysteresis or regime keying alone (keep count batching).** Cheapest;
  stops the oscillation but leaves clamped-size throughput overhead-dominated
  and the count-vs-length mismatch unfixed - it caps the loss instead of
  recovering it (research, pathway C). Rejected as primary; its regime insight
  is absorbed by the token-denominated ceiling.
- **Headroom recovery (unload the reranker during encode-bearing jobs).** Raises
  the collision threshold without bounding the footprint; interacts with search
  availability on the shared device. Deferred to its own decision (research,
  pathway D).
- **Do nothing beyond the shipped degradation verdict.** The verdict cannot see
  a rate collapse with recent forwards; the incident class recurs silently.
  Rejected.

## Constraints

- `sentence-transformers>=5.0` `encode` accepts an explicit `batch_size` per
  call and length-sorts internally; per-bucket calls must pass buckets that are
  already length-homogeneous so the internal sort is a no-op in effect.
- Bucket planning must not tokenise twice: the planner uses a character-based
  token estimate under the existing 8,000-char truncation, and the learned
  token ceiling - not the estimate - is the safety authority.
- The GPU lock must bracket each bucket's forward, not the whole slice, and the
  single-consumer rule is untouched.
- Telemetry additions ride the existing enriched jobs projection and the
  forward-entry/exit runtime block; no second vocabulary, no entry-point-owned
  verdicts.
- Guard tests must prove they can fail: the OOM-retry guard goes red when retry
  scope regresses to the slice; the calibration guard goes red when the
  estimator under-plans by more than its stated margin; the telemetry guard
  goes red when a bucket completes without advancing the sub-slice counter.
- Parent features are stable: the ceiling derivation, forward telemetry, and
  jobs projection are landed and verified; nothing here depends on unshipped
  work.

## Implementation

The encode path gains a bucket planner: the length-sorted slice is partitioned
into sub-batches where estimated tokens (items × padded length, chars-to-tokens
calibrated) stay within a token budget, capped by the existing item batch-size
knob. The learned ceiling is re-denominated from items to tokens: an OOM records
the failing token footprint, and future buckets are planned under it; recovery
probes raise the token budget, not an item count, so a probe on short chunks no
longer certifies a size that long chunks will fail. Each bucket runs as one
library `encode` call under its own GPU-lock hold; an OOM discards and splits
only that bucket, retaining every completed bucket's output. `empty_cache` runs
only on an actual OOM. The dense and sparse ceilings both adopt the token
denomination through the shared ceiling class.

The owned bucket loop emits encode-stage truth as a by-product: per-bucket
sub-slice progress (chunks encoded within the current slice), the live token
budget and bucket size, and a per-job OOM counter, published through the
existing runtime block and jobs projection. The degradation classifier gains a
rate-vs-self-baseline input: a job whose recent chunk rate falls a large factor
below its own run median reports `degraded` with the ceiling state attached as
evidence, while the existing forward-recency and stall verdicts stay unchanged.

## Rationale

Token-budget bucketing wins on a knockout: it is the only option that bounds
what the OOM ladder exists to guard, so the ladder stops being load-bearing and
its oscillation cost disappears for planned batches
(`2026-07-29-encode-batch-adaptivity-research`, root-collision and oscillation
findings). Per-bucket library calls beat a custom loop because the bucket
planner adds no mirrored logic - planning stays outside, execution stays in the
library - which is the canonical-code rule applied to the frontier risk. Scoping
retry to a bucket converts the residual OOM cost from minutes of discarded work
to one sub-batch. The observability additions reconcile rather than reverse the
index-observability record: that record rejected sub-batching *motivated by*
padding efficiency and cadence coupling; buckets cut from a length-sorted slice
preserve length grouping by construction, and the heartbeat is a by-product of a
loop owned for memory correctness, so the rejection's motivation is honoured
while its conclusion narrows to its original scope (heartbeat-motivated
sub-batching remains rejected).

## Consequences

- The OOM class driving the ladder disappears for correctly-planned buckets;
  residual OOMs (estimate error, foreign VRAM pressure) cost one bucket and
  tighten the token ceiling with regime-correct information.
- Tail slices encode at a throughput bounded by tokens, not by a count learned
  on a different regime; the measured 10-20x collapse mode is structurally
  removed, to be verified by the rate telemetry this record adds.
- Per-bucket GPU-lock holds shorten worst-case search wait during indexing.
- Operators see sub-slice progress, budget state, and OOM counts instead of a
  multi-minute silent slice; a rate collapse reports `degraded` with cause.
- New surface: a calibration constant (chars-to-tokens) that can be wrong for
  exotic content - mitigated by the learned token ceiling being the enforcement
  authority and the calibration guard bounding the estimator's error.
- Per-bucket call overhead (repeated `encode` entry, per-bucket device moves)
  replaces per-32-item overhead; at sane budgets this is noise against the
  collapse it removes, and the rate telemetry will catch a regression.
- The index-observability record's rejected-option scope is narrowed by this
  record; both records stay accepted, linked, and non-contradictory.
- Headroom recovery (reranker residency) remains undecided and is not blocked.
