---
tags:
  - '#adr'
  - '#pool-orphan-guard'
date: '2026-07-25'
modified: '2026-07-27'
body_hash: 'sha256:65850494e06a89b5731b6f7020a381e36f09b80fd019ece13137ec639464576b'
related:
  - "[[2026-06-02-index-perf-hardening-adr]]"
  - "[[2026-06-02-rag-index-performance-adr]]"
  - "[[2026-07-23-service-orphan-reaping-adr]]"
  - '[[2026-07-25-pool-orphan-guard-reference]]'
  - '[[2026-07-27-pool-orphan-guard-grounding-research]]'
---

# `pool-orphan-guard` adr: `spawn pool workers watch the parent sentinel and exit when it fires` | (**status:** `accepted`)

## Problem Statement

Chunking runs on spawn-started process pools. A worker parks in the call
queue's blocking get, and the queue's write handle is inherited by every
worker, so the read end never reaches EOF while a single sibling is still
alive. Nothing in the worker loop waits on the parent.

That costs nothing while the parent unwinds its own context manager, because
shutdown hands every worker the wake-up sentinel. It is not free when the
parent dies without reaching that path, and no supported platform rescues it
there. The inherited write handle is inherited on all of them, so a blocked
worker outlives its owner everywhere; the two platforms differ only in how
routinely they reach that state.

On Windows the designed stop path reaches it every time: a detached daemon
shares no console, so the graceful console signal cannot arrive and the verb
escalates to a pid-targeted `TerminateProcess`
(`src/vaultspec_rag/cli/_service_stop.py:238`,
`src/vaultspec_rag/cli/_process.py:916`), skipping `atexit` and the lifespan
`finally` alike. On POSIX the ordinary stop is graceful - `SIGTERM` lets the
context manager unwind - but the same verb escalates to `SIGKILL` when the
drain window expires (`src/vaultspec_rag/cli/_service_stop.py:668`), and a
crash or an external hard kill lands identically on both. Re-parenting does not
help: `init` reaps zombies, it does not terminate a live process blocked on a
queue, and the stop path targets a pid rather than a process group. The cohort
therefore survives until an operator removes it, on either platform - one full
set of live interpreters per killed run.

The decision is which party owns the cleanup - the parent, on a path it may
never reach, or the worker, which is guaranteed to be alive at the moment the
parent is not.

## Considerations

- Three construction sites build pools directly today, none passing an
  initializer, and no guard of any kind exists in the tree
  (`2026-07-25-pool-orphan-guard-reference`).
- The pool is spawn-started and its workers are CPU-only by standing decision
  (`2026-06-02-rag-index-performance-adr`), so a guard may not touch CUDA or
  pull torch onto the worker import chain.
- The pool already carries an `initializer` seam by prior decision
  (`2026-06-02-index-perf-hardening-adr`), so installing per-worker setup at
  construction is an established mechanism rather than a new one.
- The project ships and tests on both Windows and Linux, so a guard that exists
  on one of them leaves the defect standing on the other.
- The sibling qdrant child is guarded by a Windows job object in
  `src/vaultspec_rag/qdrant_runtime/_supervise.py`; that mechanism needs a
  handle to a child the parent spawned itself, which is not how a pool worker
  comes into being, and it covers only one of the two platforms.
- Each platform offers a native parent-death facility - a job object on
  Windows, `PR_SET_PDEATHSIG` on Linux - and neither spans both, so taking
  either one commits to writing and maintaining the other.
- The daemon's own orphan class is already decided
  (`2026-07-23-service-orphan-reaping-adr`), scoped to the daemon signature. It
  does not see pool workers and is not extended here.
- The parent sentinel is the only signal that survives a death the parent never
  got to handle.
- The defect and the fix are both demonstrated: with the guard removed a
  hard-killed owner leaves its full worker cohort live and named by pid; with
  the guard in place none survive.

## Considered options

- **Rely on the parent's shutdown path.** Rejected: that is precisely the path
  a `TerminateProcess` skips, so the mechanism is absent exactly when it is
  needed and present only when it is not.
- **Wrap each pool site in a `finally` that kills its children.** Rejected:
  same class as the above - a hard kill runs no `finally` - and it repeats the
  guard at every site, so a fourth site silently omits it.
- **Reap by process signature from a supervisor, as the daemon does.**
  Rejected: it needs a live supervisor the hard kill may also have taken, and
  the signature a stranded cohort presents is the signature a legitimately
  running cohort presents, so it cannot tell them apart.
- **Use each platform's native facility - a job object on Windows,
  `PR_SET_PDEATHSIG` on Linux.** Rejected: two mechanisms for one decision,
  each testable only on its own platform, so the pair drifts and the weaker
  half is the one nobody notices. The job object additionally needs a handle to
  a child the parent spawned itself, which the executor does not expose, and
  `PR_SET_PDEATHSIG` is Linux-only rather than POSIX-wide.
- **Each worker watches the parent sentinel and exits when it fires, installed
  by one pool-construction seam.** Chosen. Death is observed by the party that
  survives it; the seam makes the guard impossible to omit; and the sentinel is
  a standard-library abstraction over the pipe POSIX closes and the handle
  Windows signals, so one mechanism covers both platforms.

## Constraints

- The guard installs at construction, not per task. A pool built directly from
  the executor looks correct and leaks, so pool construction gets exactly one
  home in the indexer.
- The watch runs on a daemon thread so it can never hold interpreter exit open.
- On firing, the worker leaves immediately rather than unwinding. There is no
  reader left for the result queue, and an orderly shutdown would block on the
  very queues whose reader just died.
- The mechanism depends only on the standard library's parent-process handle,
  which is meaningful solely inside a spawned child. Called anywhere else it
  must be inert rather than raising, so the seam stays safe for a direct call.
- No branch on the running platform, and no native parent-death facility from
  either one. A guard that reads differently per platform is two guards, and
  only the one the developer runs gets exercised.
- The exit status must be distinguishable from a task failure: the worker was
  healthy and merely outlived the run that owned it.

## Implementation

One module owns spawn-pool construction for the indexer and returns an
executor carrying the parent-death watch as its initializer, so every pool
inherits the guard by construction rather than by remembering. The three
existing sites call that seam instead of constructing the executor themselves.

The initializer runs once per worker before it accepts work. It resolves the
parent handle; when there is none - the process is not a spawned child - it
returns and the worker behaves exactly as before. When there is one, it starts
a single daemon thread that blocks on that handle and, when the block returns,
exits the process immediately under a status reserved for outliving its owner.

Nothing else moves. The worker task loop, the CPU-only worker contract and the
spawn start method are untouched, and no service-domain behaviour enters the
indexer.

## Rationale

Every rejected option assigns the cleanup to a party that may not be alive to
perform it, or to a supervisor that cannot distinguish a stranded cohort from a
working one. The worker is the only party guaranteed to exist at the instant
the parent stops existing, and the parent sentinel is the only signal that
outlives a death the parent never handled. That is the knockout: the other
options are all variations on asking the dead to tidy up.

Consolidating construction is what makes the guard hold rather than merely
exist. The defect's shape is a pool that reads as correct at every call site
and leaks only under a kill nobody tests by hand, so availability is not
enough - the guard has to be unavoidable.

Portability decides it against the native facilities. The defect is a property
of the inherited queue handle, not of any one kernel, so it is present wherever
the project runs; the native mechanisms are not. Choosing them would mean two
implementations of one decision, each exercised only on the platform its author
happened to be using, which is the arrangement that produces a guard that is
real on one platform and decorative on the other. The parent sentinel is the
standard library's single abstraction over both, so the decision stays one
decision.

The mechanism is proven in both directions rather than merely present. Removing
the initializer strands a full cohort and the guard test fails on the assertion
that names the surviving pids; restoring it returns the test to green. A guard
whose failure direction was never observed would be the same class of defect as
the one being fixed.

## Consequences

A hard-killed run stops stranding memory, and the orphaned cohorts operators
currently discover by hand cease to accumulate. Pool construction gains a
single home, so a fourth content domain inherits the guard instead of having to
remember it.

The immediate exit skips cleanup by design. That is correct here because no
reader remains, but it makes the seam wrong to reuse anywhere a flush or a
final write matters, and that limit is easy to miss when reaching for it later.
A worker mid-task when the parent dies loses that work with no record; the run
that wanted the work is gone, so there is nobody to report to, but a future
reader should not mistake the silence for the work having completed.

The guard is invisible while it works. Its only honest evidence is a test that
hard-kills a real owner and inspects real pids; a cheaper test asserting the
initializer was passed would pass against a guard that never fires and prove
nothing. That test is slow, and it is the one part of this that is genuinely
platform-sensitive - the kill it issues and the pid liveness it checks differ
per platform even though the guard does not, so it has to be written to run on
both rather than on the author's.

The both-directions evidence behind this record was taken on Windows only
(`2026-07-25-pool-orphan-guard-reference`). The POSIX case is reasoned from the
same inherited-handle mechanics rather than measured, so the Linux run is
outstanding and is the first thing that should be demanded of the
implementation.
