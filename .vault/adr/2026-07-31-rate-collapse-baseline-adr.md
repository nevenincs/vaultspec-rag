---
tags:
  - '#adr'
  - '#rate-collapse-baseline'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
related:
  - '[[2026-07-29-encode-batch-adaptivity-adr]]'
  - '[[2026-07-29-encode-batch-adaptivity-research]]'
  - '[[2026-07-31-issue-triage-research]]'
---

# `rate-collapse-baseline` adr: `high-percentile rate-collapse baseline` | (**status:** `proposed`)

## Problem Statement

The degraded verdict compares a running job's windowed progress rate to the
median of the job's own retained rate history
(`src/vaultspec_rag/server/_routes_jobs.py:403-424`,
`src/vaultspec_rag/jobs.py:615-629`). The retained history is a bounded ring of
spaced window-rate observations that keeps filling during a collapse, because a
collapsed job still advances; once collapsed observations occupy more than half
the retained history, the 50th percentile is the collapsed rate, the ratio
returns toward 1, and the verdict reads `healthy` until throughput falls
further. Incident replay confirmed onset detection about two minutes into a
collapse and confirmed this blind spot (GitHub issue 306); lowering
`RATE_COLLAPSE_RATIO` (`src/vaultspec_rag/_job_errors.py:63`) cannot close it.
The gap lives in the baseline statistic. This record decides that statistic -
the amendment the governing record and the issue both anticipated.

## Considerations

- The governing record decided a rate-vs-self-baseline classifier keyed to the
  run median (`2026-07-29-encode-batch-adaptivity-adr`, Implementation); the
  classifier's direction stands, and only the statistic is in question.
- The verdict must be earned by the evidence published beside it: the
  enrichment (`src/vaultspec_rag/server/_routes_jobs.py:637-643`) and the
  summary tally (`src/vaultspec_rag/server/_routes_jobs.py:828-833`) both
  consume one locked read (`src/vaultspec_rag/jobs.py:632-652`). Commit
  `78aa1ba0` fixed exactly the two-read defect; the invariant is load-bearing.
- The no-guess contract: a young job (below the minimum spaced observations,
  `src/vaultspec_rag/jobs.py:627-628`), a job on a never-measured step (history
  discarded on step change or count regression,
  `src/vaultspec_rag/jobs.py:541-546`), and a job with an unknown baseline
  (`src/vaultspec_rag/server/_routes_jobs.py:419-423`) all decline the
  comparison and report `healthy`.
- The history is a bounded self-healing ring - 120 observations spaced at
  least 30 s apart (`src/vaultspec_rag/jobs.py:181-188`), so at minimum spacing
  it remembers the last hour of sustained reporting, and until it fills it is
  the whole run. Any order statistic over it eventually heals to a persistent
  regime; statistics differ only in how much ring occupancy a collapse needs
  before the baseline goes blind.
- The median was chosen so a single stalled window cannot move the reference
  (`src/vaultspec_rag/jobs.py:616-621`). The symmetric hazard at the top is a
  single anomalously fast window - a coalesced burst after an unblock, a
  replayed count, a cache-warm first slice - setting a reference the run can
  never legitimately match.
- Healthy inter-slice variation moves throughput by tens of percent, not
  fourfold (`src/vaultspec_rag/_job_errors.py:56-59`), so the 0.25 threshold
  leaves a wide margin between any upper-order statistic of a healthy run and
  the collapse verdict.
- The baseline is a published contract: the shaped block names it
  `median_per_second` (`src/vaultspec_rag/server/_routes_jobs.py:381-385`), the
  evidence reader table narrows that key (`src/vaultspec_rag/jobs.py:1570`),
  and the CLI renders "run median" prose
  (`src/vaultspec_rag/cli/_service_jobs_presentation.py:389-392`). A statistic
  change makes that name a lie unless the key is renamed.
- Triage confirmed the shipped behaviour implements the accepted decision
  faithfully; this is a decision-needed follow-up, not a defect
  (`2026-07-31-issue-triage-research`).

## Considered options

- **Median of the retained history (status quo).** Robust in both directions
  and self-healing, but blind once a collapse occupies half the retained
  history; the originating incident class outlasts that horizon. Rejected.
- **90th percentile of the retained history.** Extends the blind horizon to
  nine-tenths occupancy while keeping top-end trimming, so one burst window
  cannot set the reference; the ratio semantics, the 0.25 threshold, and the
  no-guess gates survive unchanged; still heals after a full ring turnover, so
  a legitimate regime shift cannot latch the verdict. CHOSEN.
- **Sustained maximum (max of the retained history).** Widest in-ring horizon
  (blind only at full occupancy) but zero top-end robustness: under the
  fourfold threshold, one window at four times the sustained rate flags a
  healthy run degraded for up to an hour until that observation ages out. The
  single-window-immunity rationale that picked the median applies symmetrically
  here. Rejected.
- **Peak-hold outside the ring (maximum ever observed for the step, never
  evicted).** The only option that fully closes the blind spot - and that is
  its failure mode: a step that legitimately slows on harder content latches
  `degraded` with no escape, and it adds a second baseline carrier beside the
  history the ring already owns. Rejected.
- **Absolute throughput thresholds.** Already rejected by the shaped-baseline
  design: throughput normal for one corpus is a tenfold collapse for another
  (`src/vaultspec_rag/server/_routes_jobs.py:365-369`). Not re-litigated.

## Constraints

- Parent features are shipped and stable: the rate window, the retained
  history, the shaped baseline, the single-read rate accessor, and the
  three-way verdict are all landed under the governing record
  (`2026-07-29-encode-batch-adaptivity-adr`) and verified in triage
  (`2026-07-31-issue-triage-research`).
- The statistic must change inside the single producer
  (`src/vaultspec_rag/jobs.py:615-629`), reached only through the one locked
  read, so the one-computation invariant (`78aa1ba0`) holds by construction;
  no consumer may take a second read.
- A percentile over few observations degenerates toward the sample maximum: at
  the current eight-observation minimum a 90th percentile is effectively the
  max, so the minimum-observation constant likely rises for the trimming
  property to be real. Tuning it is implementation, informed by the production
  telemetry the shipped implementation emits - the calibration the issue asked
  to wait for.
- Present-and-null key semantics are established
  (`src/vaultspec_rag/server/_routes_jobs.py:646-648`, `:667-670`): absent
  means a daemon predating the key, null means the service declined the
  comparison. The renamed key inherits both meanings unchanged.

## Implementation

The run-baseline statistic changes from the median to the 90th percentile of
the retained rate-history ring, computed inside the existing single producer;
every consumer keeps receiving it through the one locked read, so the verdict,
the evidence attached to it, the published projection, and the summary tally
continue to describe the same moment. The no-guess gates are untouched: the
baseline is stated only after enough spaced observations, is discarded on step
change or count regression, and is null wherever the service declines to
compare - young jobs, never-measured steps, and unknown baselines keep
reporting `healthy`. The published member renames from `median_per_second` to
the statistic-neutral `baseline_per_second` across the shaped block, the
evidence reader table, and the CLI phrase; no compatibility alias is kept, and
no new key is added - the statistic's identity lives in the constant's
documentation, not the wire contract, so a later re-tuning of the percentile
is not another wire migration. `RATE_COLLAPSE_RATIO` stays at 0.25. The
minimum-observation constant is re-examined during implementation so the
percentile has something to trim.

## Rationale

No statistic over a bounded self-healing history closes the blind spot
entirely; that is structural. The one option that does close it - peak-hold -
trades it for a permanent false-degraded latch, and a latched verdict trains
operators to ignore the tier, which is a worse outcome than a verdict that
arrives late. Within the self-healing statistics, the 90th percentile
dominates: it extends the detection horizon from half the retained history to
nine-tenths - beyond the originating incident's occupancy - while retaining
exactly the outlier immunity that motivated the median, now applied at the top
where the hazard moved. The sustained maximum forfeits that immunity for the
marginal horizon between nine-tenths and full occupancy, and under the
fourfold threshold a single burst observation is enough to spend the verdict's
credibility on a healthy run. Because the percentile is at least the median,
the verdict fires no later than today, and because healthy variation is tens
of percent against a fourfold threshold, no new flapping is expected - a claim
the published evidence pair falsifies cheaply in production. The threshold and
the no-guess behaviours surviving unchanged is what keeps this a one-statistic
amendment rather than a re-tuning cascade.

This record amends `2026-07-29-encode-batch-adaptivity-adr` in its
degradation-classifier facet - the run median named there becomes the 90th
percentile on acceptance - and does not supersede it: the token-budget
decision, the classifier's rate-vs-self direction, and the observability
contract all stand.

## Consequences

- Onset detection survives collapse regimes occupying up to nine-tenths of the
  retained history (roughly 54 of the minimum 60 retained minutes once the
  ring is full) instead of half; the incident class that motivated the verdict
  stays visible for its measured duration.
- The blind spot is narrowed, not eliminated: a collapse outlasting the full
  ring still becomes the baseline and the verdict heals. If production
  telemetry shows collapses routinely outlasting the ring, the next knob is
  the ring's span (observation count times spacing), not the statistic.
- The verdict fires no later than today and possibly earlier; new
  false-positive exposure is bounded by the fourfold threshold against
  tens-of-percent healthy variation, and the published recent/baseline pair
  makes any flapping directly observable.
- Renderers pay a one-key migration (`median_per_second` to
  `baseline_per_second`) and a one-word prose change; external consumers of
  the enriched projection see the same rename once. That is the honest cost of
  not letting a key named median publish a percentile.
- Until the minimum-observation constant is retuned, the percentile sits near
  the sample maximum early in a run; raising the minimum trades baseline
  availability in the first minutes of a step for real trimming - the
  verdict's recency signals cover that window regardless.
- The one-computation invariant and the no-guess contract are preserved by
  construction; no new state carrier, key, or vocabulary is introduced.
