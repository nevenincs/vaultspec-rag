---
tags:
  - '#adr'
  - '#jobs-tui'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-27-jobs-tui-research]]"
  - "[[2026-06-11-service-jobs-operability-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-24-operator-feedback-hardening-adr]]"
  - "[[2026-07-21-managed-log-contract-adr]]"
---
# `jobs-tui` adr: `the live jobs view becomes an owned-screen interface` | (**status:** `accepted`)

## Problem Statement

The live jobs view is a reprint loop, and a reprint loop cannot be made into an operator
interface by improving its strings. Selection, per-row action, a log pane, and a status bar
all require input and a retained screen, and the current channel has neither. The evidence
for what is missing, what the service already publishes, and what the rendering options cost
is `2026-07-27-jobs-tui-research`.

A decision is needed on four points that record leaves open: the rendering stack and how it
is carried, whether the new view replaces the existing one, where a completion estimate is
computed, and whether an operator-facing "reschedule" authorises new service behaviour.

## Considerations

- Almost every capability the interface needs is already on the wire: the control endpoints,
  the capability flags that gate them, the per-job log filter, and the full project root are
  all published today (`2026-07-27-jobs-tui-research`).
- A live region cannot be hosted on the shared console as configured, and a second console
  beside it was already rejected on reproduced output
  (`2026-07-24-operator-feedback-hardening-adr`).
- Operator feedback is verified on rendered bytes, not on a produced string
  (`2026-07-24-operator-feedback-hardening-adr`). This binds the new view's tests.
- Health, status, jobs, logs and search diagnostics are service-domain behaviour that entry
  points adapt to, never own (`2026-06-11-service-jobs-operability-adr`).
- A point-sample rate averaged across steps of unequal per-unit cost mispredicts the step it
  is meant to predict (`2026-07-27-jobs-tui-research`).
- Job control is cooperative and revisioned: a requested state is not an observed state, and
  acknowledgement can lag (`2026-07-21-service-job-control-adr`).
- The managed-log response is bounded and clamped at its route
  (`2026-07-21-managed-log-contract-adr`), so a live pane cannot pull an unbounded tail.
- Nothing in the service defers, re-times, or requeues live work
  (`2026-07-27-jobs-tui-research`).

## Considered options

**Rendering stack.** A hand-rolled loop on the existing Rich dependency was rejected: it
requires owning a per-platform key reader, focus, scrolling, and reflow, which is several
hundred lines reimplementing solved problems and a Windows input path this project would
then maintain. Carrying `textual` as an optional extra was rejected: the `[mcp]` precedent
rests on the CLI never importing `mcp`, whereas the CLI is this view's only consumer, and an
extra forces a fallback view - a second implementation of one surface. `textual` as a core
dependency was chosen: it supplies the table, tabs, bindings, workers, log widget, and width
breakpoints outright, it owns the screen so the two-consoles failure cannot recur, and its
test harness drives real key presses against a real render.

**Command surface.** A separate verb alongside the existing `--watch` was rejected: two live
job views over one payload will drift, and carrying both across the seam is what the
canonical-code rule forbids. Making the interface the default for a bare invocation on a
terminal was rejected as a silent behaviour change to a command that is already run
interactively in scripts. Replacing `--watch` was chosen.

**Completion estimate.** A client-side estimate was rejected: it would be invisible to the
structured and agent-facing surfaces, and a second estimator would follow in one of them.
A service-computed windowed rate was chosen.

**Reschedule.** A new deferred-execution capability was rejected for this record: run-at
semantics need their own admission interaction and cross-restart persistence, which is a
separate decision. Mapping the affordance onto the shipped retry was chosen.

## Constraints

- The structured and one-shot paths keep their current contract. Only the live path changes.
- The interface is human-only. It is refused in combination with structured output, as the
  reprint loop already is.
- Row actions are offered only where the job's own published capability flags permit them.
  Legality is read from the job, never inferred from its phase.
- A requested action renders as requested until the service acknowledges it. The view never
  reports a desired state as an observed one.
- Every control the interface issues carries the same expected-revision guard the existing
  verbs carry.
- The estimate is published only where it is defensible, and its absence is rendered as
  absent rather than as a guess.
- The log pane reads the existing bounded route through the existing per-job filter. It adds
  no new endpoint and no unbounded tail.
- The interface adapts to reported terminal width from one composition. No second layout
  path.
- Tests assert on rendered output driven through real key presses.
- The CLI path stays free of compute imports, as it is today.

## Implementation

`textual` joins the core dependency list. The live path of the jobs command constructs and
runs an application that owns the screen; the clear-and-reprint loop and its refresh banner
are deleted rather than retained.

The service gains one derived signal per job, computed where every other derived liveness
figure is computed and published on the same projection: a windowed progress rate and the
remaining-time estimate derived from it, both null when the job is not doing countable work
or has not yet produced enough samples to be honest. The structured and agent-facing surfaces
receive it by virtue of reading the same projection.

The interface presents one multi-line row per job carrying, at minimum, state, operation,
full project path, progress, elapsed time, and estimated remaining time. Selection drives a
log pane bound to the per-job filter. A footer exposes the row actions - pause, resume, stop,
retry, delete - each enabled from the selected job's capability flags and disabled rather
than hidden when unavailable. An animated indicator distinguishes a view that is refreshing
from one that has frozen. Width breakpoints place the log pane beside the table on a wide
terminal and collapse it into tabs on a narrow one.

## Rationale

The request is for an interface, and an interface needs input and a retained screen. The
choice that follows from the evidence is not which widgets to draw but who owns the screen:
the prior operator-feedback record establishes that this project's shared console cannot host
a live region and that adding a second console makes it worse. A framework that takes the
screen outright removes that failure mode by construction rather than by care.

Replacing the existing live path rather than adding beside it is the same reasoning applied
to the view itself. Two renderings of one payload drift, and the one that stops getting fixed
is the one that ships the wrong number.

Putting the estimate in the service is not a preference about layering. An estimate is a
statement about a job, and every consumer asking about that job should get the same answer;
computing it in a terminal view would mean the agent-facing surface either lacks it or grows
its own.

Gating actions on published capability flags rather than on phase is what makes per-row
control honest. The alternative shows an operator a control that the service will reject, and
the rejection arrives after the keystroke rather than before it.

## Consequences

The base install grows by four small pure-Python packages. Every install carries them,
including installs that never open the interface.

The reprint loop is gone. Anyone relying on the previous live output's exact lines loses it;
the structured path is, as it already was, the supported channel for anything scripted.

The view acquires a test obligation the reprint loop did not have: assertions run against
rendered output driven by real key presses, and every action binding needs one. Snapshot-style
assertions are brittle against deliberate layout change and will need updating when the layout
changes on purpose.

The job payload grows two fields. They are derived and nullable, and consumers that ignore
them are unaffected.

Deferred scheduling remains unavailable, and the interface will not imply otherwise. If it is
wanted later it arrives as its own decision rather than as an affordance retrofitted onto
retry.
