---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# `encode-batch-adaptivity` `P02` summary

All seven Steps closed. The Phase made a throughput collapse visible: the encode
stage now publishes per-bucket progress and budget state, and the service
degradation verdict gained a rate-versus-self-baseline input, so a job running
at a fraction of its own opening rate no longer reports as healthy.

- Modified: `src/vaultspec_rag/jobs.py`
- Modified: `src/vaultspec_rag/server/_routes_jobs.py`
- Modified: `src/vaultspec_rag/_job_errors.py`
- Modified: `src/vaultspec_rag/cli/_service_jobs_presentation.py`
- Modified: `src/vaultspec_rag/indexer/_streaming.py`
- Modified: `src/vaultspec_rag/indexer/_consumer_pipeline.py`
- Modified: `src/vaultspec_rag/tests/test_jobs_degradation.py`
- Modified: `src/vaultspec_rag/tests/test_code_consumer_progress.py`
- Created: `src/vaultspec_rag/tests/test_jobs_degradation_display.py`

## Description

The job record carries an encode OOM counter and encode budget state, reported
through producer seams that mirror the existing forward-boundary helpers. A
bounded run-spanning progress-rate history sits alongside them, derived from
samples the reporter already takes rather than any new sampler or thread; it was
necessary because the pre-existing short rate window refills with a collapsed
rate within seconds and is structurally incapable of seeing a collapse at all.
The jobs projection publishes the encode fields together with a recent rate, a
run median, and their ratio, and the degradation classifier treats a large
shortfall against a job's own median as degraded while leaving the forward
recency and hard stall verdicts untouched.

The threshold was set from evidence, not taste: replaying the originating
incident's measured rates through the real registry put collapse onset at about
seven times under median roughly two minutes in, so a fourfold collapse is the
conservative trigger. The same replay exposed a limitation inherent to the
chosen statistic rather than to the threshold, and it is recorded rather than
papered over: once a collapsed regime occupies more than half a run's duration,
the median is the collapsed rate and the verdict returns to healthy until
throughput falls further. Closing that gap means changing the baseline statistic,
which is a decision for an amendment to the governing record informed by
production telemetry.

Evidence assembly and presentation carry the new facts through the one existing
envelope, with the CLI formatting numbers the service published and computing no
verdict of its own. The unhealthy row summary gained a throughput phrase, because
without it a rate-collapse verdict rendered as a fresh progress stamp and named
the wrong cause. Sub-slice progress reaches the same surfaces from the encode
bucket loop through a callback that fires outside every GPU-lock hold, never
raises, and is null-safe when no reporter is attached, so a reporting failure can
never discard buckets the pipeline has already encoded.

Verification: gates ran alone with exit codes captured separately and were green
at each commit. Two guards were proven able to fail and restored - the verdict
input, which reverts to healthy when the baseline check is neutralized, and the
row summary, which loses the throughput phrase when its part is dropped. The
sub-slice progress guard was proven the same way by disconnecting the adapter,
with the restore verified byte-identical afterwards. Coverage was added for the
rendering shipped one Step earlier, since that Step had none.
