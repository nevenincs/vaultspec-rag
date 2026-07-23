---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S33'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Shape bounded job collection and detail responses from canonical resilience fields

## Scope

- `src/vaultspec_rag/server/_routes_jobs.py`

## Description

- Add a bounded resilience shaper that projects the canonical snapshot into an
  explicit, named response shape, rounding the megabyte and second measures and
  deriving a remediation hint (`src/vaultspec_rag/server/_routes_jobs.py:293`).
- Replace the raw snapshot pass-through in the per-job liveness enrichment with
  the shaped projection, so both the collection and detail responses carry it
  (`src/vaultspec_rag/server/_routes_jobs.py:343`).
- Export the shaper and add focused coverage that it bounds, rounds, derives
  remediation, and is absent without a snapshot
  (`src/vaultspec_rag/tests/test_job_resilience.py`).

## Outcome

The job responses now shape the resilience snapshot explicitly instead of
leaking it raw, which is the one surface in this cluster that faces a broker and
so needed it most.

Before this, the per-job enrichment copied the whole record and passed the
resilience snapshot through untouched. That is exactly the raw pass-through the
bounded-operator-view rule exists to prevent: every field the snapshot carries,
at full float precision, reaches any broker or API consumer, and any field a
future snapshot grows would reach them too without anyone deciding it should.
The three sibling surfaces all shape their resilience view - the health rollup
projects it, the CLI renders each field - and only the REST response did not.

The shaper closes that in the three ways the raw copy fell short. It names each
canonical field explicitly, so the response is a bounded subset that cannot leak
a later-added snapshot field without a deliberate edit here - the coverage seeds
an unexpected field and asserts it does not appear. It rounds the megabyte and
second measures to one decimal, the same operator precision the CLI renders,
because a broker reading a reserved high-water does not need fifteen digits of
allocator noise. And it derives a remediation hint from the terminal outcome
through the shared error-remediation helper, so a broker that reads a failed
job's response can act on it without re-deriving the remedy the CLI already
shows.

One insertion point covers both required surfaces. The per-job liveness
enrichment is the single function behind both the bounded job collection and
the single-job detail response, so shaping there shapes both at once, and a job
with no recorded resilience simply carries no resilience block rather than a
null one.

The timestamps are deliberately not rounded. A last-durable-progress or
next-retry epoch is a point in time, not a measure, so rounding it to a tenth
of a second would corrupt it rather than bound it; only the byte and duration
magnitudes are reduced to operator precision.

## Notes

This is the one genuine build in the S32-S35 cluster. The other three surfaces -
the canonical snapshot, the health rollup, and the CLI render - were found
already implemented in the codebase, having landed through other commits without
passing this plan's execute phase; their Step Records are being written
separately to record that honestly. This step's route surface was the real gap:
it had no explicit shaping at all, only the raw copy.

The shaper's coverage is proven to fail against a regression, not just to pass.
Reverting the shaper to a raw pass-through makes the bounding assertion red - the
seeded internal field leaks and the rounded values come back at full precision -
so the test guards the bounded contract rather than merely exercising the happy
path.

One consistency point is flagged for the verify step that follows. The response
now rounds its megabyte and second measures while the health rollup still
spreads the snapshot at full precision, so the two surfaces expose the same
resilience state but not byte-identical numbers. The step that verifies jobs,
health, and CLI expose identical resilience state must treat that rounding as
semantic equivalence, or the health surface should round consistently; that is a
deliberate call for that step, recorded here so it is met rather than
discovered. The health file also carries an unrelated uncommitted change owned
elsewhere, so it was left untouched here.
