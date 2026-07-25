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

NO MEASUREMENT WAS TAKEN. There is no wall-clock number, no estimate and no
expected figure for the cadence change anywhere in this record, deliberately.
The owner of the machine declined a quiesce window so the release could ship,
which is the right trade: an honestly open Step beats a number that is really
scheduler noise, because the noise would be trusted later.

## Notes

Deferred by decision, not dropped. What a later run needs, so none of this is
re-derived:

Preconditions:

- An idle device. Confirm with `nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv`
  that only the daemon's resident models hold memory, and with
  `uv run --no-sync vaultspec-rag server jobs` that no index job is active or
  waiting.
- Quiesce automatic updates for every watched root, one call per root, taking
  the roots from `uv run --no-sync vaultspec-rag server updates status`:
  `uv run --no-sync vaultspec-rag server updates stop <root>`. Restore each of
  them afterwards with `uv run --no-sync vaultspec-rag server updates start <root>`.
  This holds searches up while stopping new index work, so other consumers of
  the service keep working; the index simply goes stale for the window.
- Budget 60-90 minutes for both arms plus model load, on a rebuild-class
  corpus. This repository's own vault rebuilds in roughly 337 s and its code in
  roughly 157 s, so a rebuild-class corpus means the PDF-heavy sibling root, not
  this one.

The prerequisite that outranks the window: give the vault run a memory-budget
snapshot so its peak CUDA reserved and allocated reach the job record. The peaks
travel to the record through the code and document run-checkpoint projections
and the vault run has neither, so today a vault A/B produces a wall-clock number
with no safety reading beside it. Measuring the timing without the memory
reading would answer the cheap half of the question and leave the dangerous half
open.

Procedure once both hold:

- Arm one, current default: `VAULTSPEC_RAG_VAULT_CACHE_FLUSH_SLICES=1` and
  `VAULTSPEC_RAG_DOCUMENT_CACHE_FLUSH_SLICES=1`, then
  `uv run --no-sync vaultspec-rag index --type vault --rebuild --json` against
  the rebuild-class root.
- Arm two, candidate cadence: the same two variables set to 8, same command,
  same root, immediately after.
- Repeat with the arm order reversed, so allocator state and thermals fall on
  both arms.
- Record per arm: job wall-clock and the run's own work timer from the job
  record, peak CUDA reserved, peak CUDA allocated, the derived CUDA ceiling, and
  whether the OOM ladder fired at all.
- Acceptance: the cadence rises only if peak reserved does not climb materially
  toward the ceiling and no OOM ladder event appears. The code path already
  recorded 13,074 MB peak reserved against a 12,895 MB ceiling at cadence 8, so
  treat any climb as disqualifying rather than as headroom.

A measurement harness for the encode-side A/B (fixed slice list, alternating
cadence arms, peak reserved and allocated per arm) was written and deliberately
left out of the repository: it only produces a number in a window this machine
did not have, and a committed benchmark nobody can run invites someone to run it
under contention and believe the result.

Nothing regressed: the shipped defaults preserve the historical per-slice flush
on both paths.
