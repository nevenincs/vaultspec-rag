---
tags:
  - '#exec'
  - '#index-throughput'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S11'
related:
  - "[[2026-07-24-index-throughput-plan]]"
---

# run the before/after measurement: a contended multi-job window and a solo rebuild-class job, comparing wall-clock and queue-wait telemetry against the research baselines

## Scope

- `measured runs`
- `Step Record`

## Description

- Measure the gated system from the resident daemon's own persisted job
  records rather than by staging a synthetic contended window: the daemon has
  been running the gated build for hours across four watched roots, so the
  contended window the Step asks for already happened, repeatedly, on real
  corpora. Read-only analysis; no live state was touched.
- Decompose every terminal index job carrying an admission stamp into
  admission wait (start to admission), post-admission run window (admission
  to finish), the run's own internal work timer, and the accumulated in-run
  GPU-lock wait the telemetry Step added.
- Check encode-slot exclusivity directly: pairwise overlap of every
  [admission, finish] hold window.
- Compare against the pre-gate baselines measured on this same machine during
  research.

## Outcome

PARTLY OBSERVED, STEP LEFT OPEN. The Step asks for two things: a contended
multi-job window and a solo rebuild-class job. The contended window is
answered, from the daemon's own persisted telemetry rather than from timings
taken by this session - no GPU was seized, no run was timed against a busy
device, and every figure below was recorded by the daemon about itself. The
solo rebuild-class arm was NOT run and no number for it exists anywhere in
this record. The machine's owner declined a quiesce window so the release
could ship; that half of the Step therefore stays open by decision, and the
Step row stays unchecked to say so.

Population: 253 terminal gated index jobs (239 succeeded, 11 failed, 3
interrupted) across the watched roots.

Encode-slot exclusivity: 0 overlapping hold windows out of 31,878 pairs. At
most one encode-bearing index job was ever in flight - in production, not
only under test.

In-run GPU-lock wait, the sink the gate exists to remove: p50 0.000 s, p95
0.000 s over 239 jobs (typical values are single-digit microseconds), with
one 251.6 s outlier. Pre-gate baseline for comparison: individual jobs
blocked 2,489 s, 2,456 s and 2,139 s inside their own run windows. The
outlier is expected and is not a gate failure - interactive searches take the
same process-wide GPU lock and are deliberately not gated, so a job that
overlaps a busy search window still waits.

Per-job wall inflation, run window divided by the run's own work timer
(193 jobs whose work exceeded 1 s): p50 1.029x, p95 1.427x, max 1.975x.
Pre-gate baseline: 5.0x (622 s work against 3,110 s wall, incremental code),
3.7x (796 s against 2,935 s, incremental vault), 2.3x (1,892 s against
4,348 s, incremental document). Post-admission wall-clock now tracks the work
the job actually did.

Solo behaviour is not penalised: admission wait is p50 0.178 s and min
0.063 s, so an uncontended job pays sub-second gate cost. The largest run in
the population (1,685.3 s incremental code) took 0.1 s of admission wait,
1,683.7 s of work and 0.0017 s of lock wait - wall equals work.

Waiting became visible instead of disappearing into "running": admission wait
reaches p95 1,308 s and max 1,986 s, and up to 8 jobs were queued behind one
admitted job. The same 8-job pile the research found running concurrently now
queues honestly, one holder at a time.

SOLO ARM NOW MEASURED, in a later coordinated window. The open half of this
Step has numbers. Automatic updates were stopped for the one watched root and
the admitted queue was allowed to drain first; cells ran as fresh interpreters
driving the production index entry points directly, against a worktree whose
content equals the tree the research baselines were taken on.

Solo, device quiet:

- code rebuild: 60.7 s of run-reported work (83.9 s wall including model load),
  444 files and 7,450 chunks, peak CUDA reserved 7,484 MB, peak allocated
  5,208 MB.
- vault rebuild: 108.1 s of work (128.6 s wall), 1,965 documents, peak reserved
  3,622 MB, peak allocated 3,568 MB.

Against the pre-gate solo baselines measured on this machine during research -
157 s code and 337 s vault - neither path regressed, which is the narrow
acceptance question this arm exists to answer. The margin is large enough to
look like a win and is deliberately not claimed as one: the baseline records
neither their corpus size nor how quiet the machine was when they were taken,
so "not regressed" is what the evidence supports and "2.6x faster" is not.

Contended, same corpus, same harness: a second vault rebuild overlapping
restarted watcher jobs took 299.1 s of work against the quiet run's 108.1 s for
byte-identical output - 2.77x inflation. This is UNGATED contention and must not
be read as a gate measurement: these cells drive the indexer in their own
process and never pass through the daemon's admission gate, so nothing mediated
them. The figure sits between the research's pre-gate 4-6x and the gated
production population's 1.029x p50 above, and is consistent with both.

One cell failed and the failure is kept here rather than dropped. The first code
rebuild died at `slice-6-after-dense-forward` with a CUDA allocated high-water
of 2,895.9 MiB above a 3,520.1 MiB resident baseline against a 2,667.6 MiB
ceiling. The cause is substantially the harness: an out-of-process cell loads a
second model copy while the daemon keeps its own resident, so the
capacity-derived ceiling is roughly halved against production, where the daemon
encodes in the process that already holds the model. The same rebuild fit once
the queue had drained. Read it as a property of two encoding processes sharing
one device, not as a defect in the rebuild path.

## Notes

- What this measurement is NOT: a controlled A/B of one corpus with the gate
  on and off. The before numbers come from the pre-gate records of this
  machine, and the two job populations differ in corpus mix and mode, so the
  inflation comparison is population-to-population. The exclusivity result and
  the near-zero in-run lock wait are direct observations of the gated system
  and need no comparison.
- Aggregate machine throughput (indexed chunks per hour before against after)
  was not measured and cannot be inferred from these records. The gate adds no
  GPU capacity; it removes per-job latency inflation and makes the wait
  visible.
- A full rebuild-class job does not appear in the observed population; the
  largest observations are long incremental runs. Staging a full rebuild needs
  an exclusive GPU window, which the machine's owner declined.
- The CUDA cache-flush cadence re-tune is a separate Step and stays unmeasured
  for the same reason: it needs an idle device.

What the open half needs, so a later run does not re-derive it:

- The same preconditions as the cadence Step: an idle device confirmed by
  `nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv` and by
  `uv run --no-sync vaultspec-rag server jobs` reporting nothing active or
  waiting, then automatic updates stopped per root with
  `uv run --no-sync vaultspec-rag server updates stop <root>`, taking the roots
  from `uv run --no-sync vaultspec-rag server updates status` and restoring each
  afterwards with `uv run --no-sync vaultspec-rag server updates start <root>`.
- Solo arm: one `uv run --no-sync vaultspec-rag index --type code --rebuild --json`
  and one `--type vault --rebuild --json` on a rebuild-class root with nothing
  else admitted, recording job wall-clock, the run's own work timer, admission
  wait and in-run GPU-lock wait from the job record. The acceptance question is
  narrow: a solo rebuild must not have regressed against the pre-gate solo
  baseline, since the gate is meant to cost an uncontended job nothing.
- Contended arm, if a staged one is still wanted after the production evidence
  above: submit four rebuilds within a second of each other and compare the
  window's total wall-clock and each job's admission wait against the solo arm.
  Doing this with the gate disabled would require building the encode slot's
  token count into configuration, which it deliberately is not - the slot is a
  module constant precisely so nobody can widen it at runtime. That is why the
  pre-gate side of any staged comparison can only come from the historical
  records.

Conditions and defects of the solo arm above, so its numbers are read for what
they are:

- Encode-seam vector reuse had to be turned off, and leaving it on would have
  voided the measurement silently. The measured worktree is a fork of an
  already-indexed tree, so with reuse at its default the run adopts donor
  vectors and skips the encode: a vault pass finished in 12 s against the same
  corpus that takes 108 s encoding, and never moved the allocator past model
  weights. A cadence or throughput number taken in that regime measures nothing
  and reads as an enormous win. Every cell here set the reuse off-switch.
- The runs carry no admission-wait or in-run GPU-lock telemetry. Driving the
  indexer in-process bypasses the daemon's job records, which are where those
  two figures live, so this arm answers wall-clock and memory only. The
  telemetry half is not left unanswered: it is answered above from the 239-job
  terminal population, whose largest run - 1,685.3 s of incremental code - paid
  0.1 s of admission wait and 0.0017 s of lock wait, wall equal to work. That is
  a solo rebuild-class telemetry observation from production, and it is stronger
  evidence than one staged run would be.
- A daemon-routed re-run is the better harness for wall-clock AND telemetry
  together, but it carries a trap worth naming before someone reaches for it: a
  service-routed job runs under the daemon's own configuration, where encode
  seam reuse is on by default. Rebuilding a forked worktree that way adopts
  donor vectors and returns in seconds with perfect telemetry and a meaningless
  wall-clock. Either disable reuse for the daemon's lifetime or route the run at
  a root that has no donor namespace.
- The daemon stayed up throughout with its models resident, so the device was
  never bare. Peak-memory figures here are therefore lower-bounded by a shared
  card, not by a private one.
- Conditions shifted mid-batch: the watched root's automatic updates were
  restarted externally partway through, which is what the contended vault cell
  captured. Cells are reported individually and no arm is averaged across that
  boundary.
