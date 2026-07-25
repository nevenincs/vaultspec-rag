---
tags:
  - '#reference'
  - '#pool-orphan-guard'
date: '2026-07-25'
modified: '2026-07-25'
related: []
---

# `pool-orphan-guard` reference: `how a spawn pool worker survives its owner, and what proves it`

Grounding for the parent-death guard on the indexer's spawn-started chunk
worker pools: where the pools are built, why a worker outlives a hard-killed
owner, how that differs between the two supported platforms, what the adjacent
mechanisms already cover, and the observed evidence in both directions. Sources
are the tree at the time of writing and a live mutation run on Windows 11 with
CPython 3.13. The Windows-only scope of that run is a real limit on the
evidence and is stated again below.

## Summary

### Where the pools are built

Three sites construct a pool directly from `ProcessPoolExecutor`, each with a
`spawn` context and no `initializer`:

- `src/vaultspec_rag/indexer/_codebase_indexer.py:986` - batch-group chunking.
- `src/vaultspec_rag/indexer/_codebase_indexer.py:1192` - the streaming
  windowed path.
- `src/vaultspec_rag/indexer/_vault_prep.py:314` - vault document splitting.

Two further constructions exist under
`src/vaultspec_rag/tests/integration/test_adversarial_singleton.py:66` and
`:82`; they are test-owned and out of scope.

A tree-wide search for `parent_process`, `initializer=` and any parent-death
watch returns nothing outside these sites, so no guard of any kind is present.

### Why the worker survives

A pool worker blocks in the call queue's `get`. The call queue's write handle
is inherited by every worker, so the read end cannot reach EOF while any
sibling remains alive, and the worker loop waits on no parent signal. The
normal exit is the parent's `shutdown`, which feeds each worker the `None`
wake-up item as the context manager unwinds.

Any death that skips that unwind strands the cohort. Nothing about this is
platform-specific: the inherited write handle is inherited on every supported
platform, and the worker's blocking `get` waits on no parent signal anywhere.
What differs is how often the stop path reaches that state, and what the
operating system does with the survivors.

On Windows it is the designed stop path rather than an exceptional one. The
graceful console signal cannot reach a detached daemon that shares no console,
so the stop verb escalates to a pid-targeted `TerminateProcess`
(`src/vaultspec_rag/cli/_service_stop.py:238`, with the direct pid-targeted
path at `src/vaultspec_rag/cli/_process.py:916`), running neither `atexit` nor
the lifespan `finally`. Windows has no orphan reaper and no process-group
teardown on parent death, so the cohort simply persists.

On POSIX the ordinary stop is graceful - `SIGTERM` reaches the daemon and the
context manager unwinds, so the workers get their sentinel and exit normally.
The leak appears on the escalation instead: the same verb escalates to
`SIGKILL` when the drain window expires
(`src/vaultspec_rag/cli/_service_stop.py:668`), and `SIGKILL` skips the unwind
exactly as `TerminateProcess` does. Re-parenting to `init` does not rescue
anything - `init` reaps zombies, meaning already-exited children, and never
terminates a live process blocked on a queue read. A process-group signal would
reach the cohort, but the stop path targets a pid, and a daemon is deliberately
detached from any controlling terminal, so no hangup arrives either.

Both platforms therefore leak one `os.process_cpu_count()`-sized set of live
interpreters per killed run; Windows reaches that state on every stop, POSIX on
the escalation, a crash, or an external hard kill.

### What the adjacent mechanisms cover

- The qdrant child is supervised via a Windows job object in
  `src/vaultspec_rag/qdrant_runtime/_supervise.py` (terminate and kill paths at
  `:803` and `:816`). A job object needs a handle to a child the parent spawned
  itself; `ProcessPoolExecutor` owns its own spawning and exposes no such
  handle, so the mechanism does not transfer - and it covers only one of the
  two supported platforms.
- The Linux counterpart, `PR_SET_PDEATHSIG`, has the kernel signal a child on
  parent death. It is Linux-specific rather than POSIX-wide, so pairing it with
  the job object would mean two implementations of one decision, each
  exercisable only on its own platform.
- `2026-07-23-service-orphan-reaping-adr` decides the daemon's orphan class
  with a bounded, signature-scoped reap. It targets the daemon signature and
  never sees pool workers.
- `2026-06-02-index-perf-hardening-adr` established the pool as a `spawn`
  executor carrying an `initializer`, and
  `2026-06-02-rag-index-performance-adr` fixes the workers as CPU-only with
  torch kept off the worker import chain. The `initializer` seam therefore
  already exists as a decided mechanism; the current sites simply pass none.

### Portability of the chosen mechanism

The project is built and tested on both platforms - the pipeline runs
self-hosted Linux jobs alongside a Windows GPU job (`.github/workflows/ci.yml`
at `:29` and `:174`) - and the codebase branches on `sys.platform` wherever
behaviour genuinely differs, including the stop path itself.

The guard needs no such branch. Every primitive it uses is portable:

- The parent-process handle and its blocking join are standard library, present
  on all platforms since CPython 3.8, and are the library's own abstraction
  over two different kernel facilities - a pipe whose write end closes at
  parent death on POSIX, a waitable process handle on Windows.
- Immediate process exit and daemon threads are universal.
- Nothing in the guard touches CUDA, torch, signals, process groups, job
  objects, or `prctl`.

Consequently the guard is a single implementation with no platform branch. The
one part that is unavoidably platform-sensitive is the *test*, which must issue
a hard kill and check pid liveness, both of which differ per platform.

### Observed evidence

Measured on Windows against current `origin/main` with the candidate guard
applied, using a test that starts a real pool, hard-kills the owning process,
and inspects real pids rather than stubbing the executor.

- Guard present: the test passes; no worker survives the killed owner.
- Guard removed (the `initializer` argument deleted from the pool
  construction): the test fails on its own named assertion,
  `pool workers outlived their owner`, reporting four live pids
  (`[16924, 32488, 35592, 64660]`) on a four-worker cohort.
- Guard restored: the test passes again, and the tree is clean.

The failing direction takes roughly a minute, since it waits out the window in
which a correctly guarded worker would have exited. Both directions were
observed in one uninterrupted sequence and the mutation was reverted
immediately; nothing was left on disk.

The measurement matters beyond confirming the fix: it establishes that a test
asserting only that an `initializer` was passed would report clean against a
guard that never fires, because the surviving-pid count is the only
observable that separates the two states.

Limit of this evidence: both directions were observed on Windows only. The
POSIX behaviour described above is reasoned from the inherited-handle mechanics
and the `SIGKILL` escalation in the stop path, not measured. The equivalent
Linux run - guard removed, cohort survives a `SIGKILL`ed owner; guard restored,
cohort exits - is outstanding, and until it is done the Linux half of this
grounding is an argument rather than an observation.
