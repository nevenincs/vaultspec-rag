---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S09'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# re-tune the CUDA cache flush cadence under overlap and record the measured effect

## Scope

- `src/vaultspec_rag/config.py`
- `measured run`

## Description

- Read the shipped state: the codebase path flushes the caching allocator
  every 8 slices, and the vault and document paths carry their own cadence
  knobs defaulting to 1, which is byte-for-byte the historical per-slice
  flush. Raising either is what this Step means by re-tuning.
- Establish the current regime's peak reserved memory from the resident
  daemon's persisted job records rather than from a synthetic run, since the
  decision record gates the flip on real peak-reserved and OOM validation.
- Attempt the controlled A/B (cadence 1 against cadence 8 on the same corpus,
  recording encode wall-clock and peak reserved).

## Outcome

REPORT-BLOCKED. The knobs and their conservative defaults are shipped; the
flip is not taken, and this Step stays open. Two findings, both measured, say
why taking it now would be unsafe rather than merely unmeasured.

First: the one path already running the raised cadence sits at its memory
ceiling. Across 131 finished code index jobs the daemon recorded peak CUDA
reserved p50 7,196 MB and max 13,074 MB against a derived ceiling of
12,895 MB for that run - the peak crossed the ceiling and the job still
succeeded. A second job peaked 11,290 MB against an 8,320 MB ceiling. The 19
document jobs, which run cadence 1, peaked 3,622 MB p50 and 3,676 MB max. The
two populations differ in corpus, batch size and activation footprint, so this
is not a clean attribution of the difference to cadence - but it does
establish that the raised-cadence regime already runs within a gigabyte of the
ceiling that counts reserved memory, which is precisely the fragmentation
hazard the decision record warned about.

Second: the vault path publishes no CUDA peak telemetry at all. Of 100
finished vault index jobs, zero recorded peak CUDA reserved or allocated,
because the peak numbers reach the job record through the code and document
run-checkpoint snapshots and the vault run has neither. The vault cadence is
the one the research flagged as a per-slice device sync worth removing, and
its safety gate is currently unobservable in production. Raising that knob
would be flipping a default whose validation signal does not exist.

The controlled A/B was not run. It needs an idle device: the resident daemon
held models and was running index jobs against four watched roots throughout
this session, and a second CUDA process on the remaining headroom would both
contaminate the measurement and risk pushing the live jobs into their OOM
ladder.

## Notes

- Recommendation for whoever takes this next: give the vault run a memory
  budget snapshot so its peak reserved reaches the job record, then run the
  A/B on a real full rebuild in an exclusive window. Until then the vault and
  document cadences stay at 1.
- A measurement harness for the encode-side A/B (fixed slice list, alternating
  cadence arms, peak reserved and allocated per arm) was written and left out
  of the repository, since it only produces a number in a window this machine
  did not have.
- Nothing regressed: the shipped defaults preserve the historical per-slice
  flush on both paths.
