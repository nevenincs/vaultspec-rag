---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:39836260ca22ca442910985121526bef4049b9a18662acb73e6a74880692c143'
step_id: 'S05'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# measure ingest wall-clock before and after the wait-policy change on a rebuild-class corpus and record the numbers

## Scope

- `measured run`
- `Step Record`

## Description

- Measure the shipped wait policy through the production store, not a hand
  rolled client: a fresh managed qdrant per cell on a temp storage dir,
  production collection geometry via the real ensure path, and 100 slices of
  512 code chunks (51,200 points, code-rebuild-class batch count) driven
  through the production code-chunk upsert entry point.
- Arm before: every slice upserted with the blocking apply handshake, no
  barrier - the semantics the path had before the change.
- Arm after: every slice upserted with the deferred handshake, then one
  application barrier with the exact-count assertion.
- Four pairs, cell order reversed on alternate reps, so drift and the
  machine's background load fall on both arms symmetrically.
- Verify each cell landed all 51,200 points by exact count before reporting
  its timing.

## Outcome

Measured. Per-run totals for 51,200 points in 100 slices:

- blocking handshake: 80.1 s, 112.7 s, 80.0 s, 72.2 s (median 80.1 s);
  per-slice p50 779, 853, 800, 696 ms.
- deferred plus barrier: 78.0 s, 90.7 s, 73.8 s, 78.2 s (median 78.1 s);
  per-slice p50 769, 879, 733, 779 ms.
- barrier cost, after 100 unwaited batches: 0.073 s, 0.076 s, 0.060 s,
  0.242 s.
- applied-point count: 51,200 of 51,200 in all eight cells.

Verdict: the wait-policy change is throughput-neutral at rebuild-class
volume. The 2 s difference between the arm medians is far inside the spread
within a single arm (72.2 s to 112.7 s for the blocking arm alone), so it
cannot be read as a win. The barrier costs a quarter of a second at worst -
0.3% of a 78 s ingest - which is the number that matters, because the barrier
is the correctness surface the change exists to add.

This reproduces the pre-implementation isolated benchmark and confirms the
decision record's re-scoping of this part: the acknowledgement already
includes the WAL write, so deferring it buys nothing by itself. The value of
the wait policy is that it let the writer-side overlap move upserts off the
encode thread, and that gain belongs to the overlap Steps, not here.

## Notes

- The machine was not quiet: the resident daemon was running index jobs
  against four roots throughout, and nine agents were working the tree. That
  inflates variance (visible as the 112.7 s outlier, which contained a single
  16.6 s slice stall) but does not bias the comparison, because the cells
  alternate and each pair runs back to back.
- Synthetic vectors and payloads, not encoded ones: this Step measures ingest,
  and vector content does not change what qdrant does with a point. Encode
  cost is deliberately outside the measurement.
- Not measured here: the WAL geometry question. The bounded 16 MB WAL was
  measured at 10-13% versus default geometry during research and no geometry
  change shipped, so no re-measurement was owed.
