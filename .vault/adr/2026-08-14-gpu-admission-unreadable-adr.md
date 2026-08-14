---
tags:
  - '#adr'
  - '#gpu-admission-unreadable'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:e0fcd2f73cea821903c8406da68f7e15391788826b839f12f855574e190f2a08'
related:
  - "[[2026-07-29-gpu-admission-gate-adr]]"
  - "[[2026-07-24-index-cuda-shared-device-adr]]"
  - '[[2026-08-14-gpu-admission-unreadable-reference]]'
---

# `gpu-admission-unreadable` adr: `refuse a device that is present but persistently unreadable` | (**status:** `proposed`)

## Problem Statement

The load-admission gate treats an unreadable free-memory figure as a reason to
admit. On a device whose driver answered presence and then refused every memory
query for sixty-nine minutes, that produced seventy-nine admissions and one
hundred and twelve `cudaErrorUnknown` job failures against hardware that no
longer existed, ending only when an operator killed the daemon by hand.

The fail-open is not wrong about the case it was written for. It reads an
unreadable figure as a hiccup and declines to convert one bad query into a
refusal of all GPU work, which is correct for a hiccup. What it cannot do is
tell a hiccup from a permanent fault, because the check holds no state: one
failed query and seventy-nine consecutive ones present identically, and both
are answered `admit`. A decision is needed because the parent record fixed the
predicate only for the case where a figure was obtained, leaving the unreadable
branch to an implementation comment that has now been shown to be load-bearing.

## Considerations

- The parent record specifies the predicate as free-against-floor and never
  states what an absent free figure means, so this is a gap it left rather than
  a decision it took (`2026-07-29-gpu-admission-gate-adr`).
- The two safeguards the fail-open leans on - the per-job CUDA ceiling and the
  allocator's backoff - both assume a device that answers, and neither fires
  when every call raises (`2026-07-24-index-cuda-ceiling-adr`).
- Every other unverifiable-state decision in this project fails closed:
  reclamation refuses to delete on an unverifiable snapshot and resets its
  grace clock, and the borrower lease refuses an unrecognised quiesce envelope.
  Admission is the only one that fails open.
- A verdict carrying no free figure never latches, so the gate re-evaluates at
  every load site - which is what makes a counted streak observable at all
  rather than a single verdict the process rides forever.
- "Present but unreadable" and "no CUDA at all" send an operator to different
  places: one to the driver, one to the installation.
- The measurement and the judgement are already separate in this gate, and the
  separation is what makes every branch exercisable without a machine that
  presents it. A remedy that hid mutable state inside the judgement would spend
  that property.

## Considered options

Detecting persistence:

- **A consecutive-unreadable count, reset by any successful reading (chosen).**
  Needs no clock, so the verdict stays a pure function of the count and the
  reading, and a hiccup costs nothing because the next good reading clears it.
- **An elapsed-time window.** Seventy-nine warnings over sixty-nine minutes is
  a slow trickle, so a time-only window can be re-armed indefinitely by an idle
  period; it also puts a clock inside a predicate that is currently
  deterministic. Rejected.
- **Refuse on the first unreadable reading.** Simple and safe, but discards the
  parent's correct instinct about transients and converts a single driver blip
  into a refusal of all GPU work. Rejected.

Where the count lives:

- **In the observation path, passed to the judgement as a value (chosen).**
  Keeps the verdict pure and the threshold exercisable over a supplied count,
  with no global state to reset between exercises.
- **A counter mutated inside the judgement.** Makes every exercise of the
  predicate order-dependent and forecloses the supplied-reading testing the
  gate was built around. Rejected.

Naming the refusal:

- **A distinct reason token with its own remediation prose (chosen).**
- **Reuse the existing no-CUDA or contended token.** Points the operator at the
  installation or at a competing tenant when the fault is the driver. Rejected.

## Constraints

- The threshold is a code constant, not configuration. The floor is
  configurable because cards differ in size; this figure describes driver
  behaviour, and there is no calibration evidence a knob could act on.
- The gate keeps its existing torch-freedom: the count is integer state in a
  module that imports no torch, and the observation path is unchanged.
- The refusal must not latch. A verdict that never reached the floor comparison
  retires nothing, and that rule is what stops an unreadable device from
  permanently disabling the floor check.
- Both directions of the new guard must be proven able to fail on the assertion
  they name, per the project's guard-test discipline; an admission guard that
  only ever admits proves nothing.
- Parent stability: the gate, the guarded memory probe, and the reason
  vocabulary are all landed and exercised. This record extends the reason set
  and one branch; it re-litigates no arithmetic the ceiling records own.

## Implementation

The observation path gains a small ledger: one integer counting consecutive
readings that reported a present device and no free figure, cleared by any
reading that produced one, and untouched by readings that never reached the
question. The judgement takes that count as an argument alongside the reading
and the floor, so what a count and a reading mean together stays a pure
function of its inputs.

Below the threshold the branch behaves as it does today - admit, and warn. At
or above it the branch refuses with a new reason token whose rendered message
names the condition and the remedy, pointing the operator at the driver rather
than at a competing tenant or a missing installation. The token joins the set
the load gate raises on, so a refused verdict stops the load instead of being
reported and ignored.

The refusal renderer stops being contention-specific: one renderer dispatches
on the reason it is given, because a second renderer for the second refusal is
the drift the canonical-code discipline exists to prevent.

## Rationale

Counting wins on a knockout the alternatives cannot clear: it is the only
option that distinguishes the transient case from the permanent one without
introducing a clock. Because any successful reading resets the count, a genuine
hiccup is free - it never approaches the threshold - while a device that has
stopped answering reaches it in the first handful of load attempts and stays
there. The predicate remains deterministic, so both directions are exercisable
over supplied values rather than only on a machine that happens to be faulty,
which is precisely the property that let the original branch be written and
then never be proven wrong.

Keeping the count outside the judgement follows the gate's existing and
deliberate split between measuring and deciding. That split is why an absent
torch, a CPU-only build, and a refused query are all exercisable today; hiding
a counter inside the predicate would have bought the same behaviour and spent
that.

Failing closed after persistence also restores consistency with the rest of the
project. The reclamation and lease paths already treat "I cannot tell" as a
reason to refuse, and the argument for admission being the exception rested
entirely on safeguards that this incident showed do not apply when the device
answers nothing.

## Consequences

- A device that stops answering now refuses GPU work after a few attempts, with
  a message naming the driver, instead of admitting an unbounded run of jobs
  that each crash on `cudaErrorUnknown`.
- New refusal behaviour on a host that was previously admitted: a machine whose
  driver is intermittently unreadable at a rate faster than its successful
  readings will now be refused where it previously ran degraded. That is the
  intended trade, and the reset-on-success rule is what keeps it narrow.
- The threshold will be wrong in some direction until evidence accumulates -
  too low refuses a device recovering from a long blip, too high extends the
  crash-loop window. The shape is fixed here precisely so the numeral can move
  without reopening the design.
- The count is per-process, so a short-lived CLI process may exit before
  reaching the threshold while the long-lived daemon reaches it quickly. That
  asymmetry is acceptable and arguably correct: the daemon is the process that
  crash-loops, and a one-shot command that fails once has already told its
  operator.
- Every reading the process takes feeds the ledger, diagnostics included, not
  only the readings a load asked for. A refused memory query is evidence about
  the device whoever asked, so an operator polling health on a failing card
  reaches the refusal sooner than a silent one does - which is the useful
  direction. The cost is that the threshold is not calibrated against load
  attempts alone, and that a faster observation cadence shortens the real-time
  window three consecutive failures span. This is the known weakness of
  counting rather than timing, accepted with the trade the alternative would
  have made worse.
- Pathway opened: the ledger is the natural place for any later per-device
  health signal - a reading that says which device stopped answering, once more
  than one is supported.
