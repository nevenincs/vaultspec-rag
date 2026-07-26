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

SECOND ATTEMPT, ALSO ABANDONED, AND STILL NO CADENCE NUMBER. A later session
did get a window: automatic updates were stopped for every watched root and the
admitted queue was allowed to drain. The A/B was launched, four cells, arms
alternating. Arm one at the shipped cadence completed clean - 131.9 s wall,
peak CUDA reserved 3,626 MB, peak allocated 3,572 MB, read from the allocator
directly. Arm two at the candidate cadence ran more than fifteen minutes
without completing and was killed unfinished.

The arm-two figure is NOT a cadence result and must never be quoted as one. A
daemon code index job admitted at 00:44:18 was still running when arm two
started and spanned the whole cell, and the watched root's automatic updates
were restarted by another session at 00:57:02 while the cell was mid-encode.
Arm one ran comparatively quiet and arm two ran contended, so the two arms
differ by device load and by cadence at once and nothing can be attributed to
either. The run was abandoned rather than reported, and it was killed partly
because the contention was mutual: the daemon's own 61-chunk job made no
progress for fifteen minutes while the two processes fought over the device.

The window could not be held, and the reason is mechanical rather than social.
Automatic updates came back three times - 00:20:31, 00:38:37 and 00:57:02 -
each within ten to twenty minutes of being stopped. This was first written up
as other sessions deliberately reclaiming the machine. That reading was wrong
and is corrected here, because it would send the next run off to negotiate with
people over a problem no negotiation can fix.

Stopping automatic updates for a root does not keep its watcher stopped. The
search and reindex routes warm a project slot and re-register its watcher as a
side effect, so any search issued against that root by anyone re-arms it within
seconds. On a machine where other sessions are searching, a quiesce is undone by
ordinary read traffic.

Idle eviction pulls in the same direction from the other side. A project slot
untouched for the idle TTL is evicted, and eviction stops that project's
watcher, so a watched root can also go quiet with nobody having asked. The
service log records these as an eviction with reason `idle` beside the watcher
stop, which is how the two causes are told apart after the fact.

The consequence for this Step: stopping watchers is not a sufficient quiesce.
An exclusive window on a shared machine means stopping the service itself for
the duration, and any slowdown must be checked against the active job list
before it is attributed to a cadence change.

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

Established by the abandoned second attempt, so the next run does not re-derive
it:

- The knob is wired correctly and the A/B has a real lever. The vault slice loop
  computes its flush cadence from the config knob and passes
  `release_cache=(is_last or (slice_index + 1) % flush_slices == 0)` into each
  slice, so raising the knob genuinely removes device syncs rather than being
  read and ignored.
- The A/B is adequately powered on this repository's own vault, which removes
  the assumption that only the PDF-heavy sibling corpus is large enough. The
  vault collection holds roughly 4,248 chunks and the slice size is the
  embedding batch size, giving about 133 slices: roughly 133 flushes at the
  shipped cadence against roughly 17 at the candidate, a difference of over a
  hundred device syncs inside a run that takes under two minutes when quiet.
- Encode-seam vector reuse MUST be disabled for any cadence measurement, and
  forgetting it produces a silent false win rather than an error. On a worktree
  forked from an indexed tree the default-on reuse adopts donor vectors and
  skips the encode entirely: the same vault corpus returned in 12 s against
  108 s of real encoding, never moving the allocator past model weights. Cache
  flush cadence has no meaning when nothing is being encoded.
- The missing vault peak telemetry can be worked around for the A/B itself, but
  not for production. Reading the allocator high-water directly in the measuring
  process gives the safety number the acceptance rule needs without shipping
  anything. The production gap is unchanged and still real: vault job records
  carry null peak CUDA reserved, allocated and ceiling, so a raised vault
  cadence would ship with no observable safety signal in the field. Closing that
  gap is its own Step, not a rider on a measurement.
- Prefer a device with no second encoder. Cells driving the indexer out of
  process load a model copy alongside the daemon's resident one, which roughly
  halves the capacity-derived CUDA ceiling and already failed one code rebuild
  outright at that ceiling. Either stop the service for the window or route the
  runs through it.
- The quiesce precondition listed above is necessary but NOT sufficient, and
  following it alone will produce another contaminated run. Stopping automatic
  updates per root does not keep those watchers stopped: a search or reindex
  against a root re-registers its watcher as a side effect of warming the
  project slot, so any other session's read traffic re-arms it. Treat "stop
  updates for every watched root" as step one, then confirm the job list is
  actually empty immediately before each arm and again after it, and discard any
  arm that overlapped an admitted job. Where the measurement genuinely needs the
  device to itself, stop the service for the window instead.
