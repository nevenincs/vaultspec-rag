---
tags:
  - '#adr'
  - '#jobs-tui'
date: '2026-07-27'
modified: '2026-07-28'
body_hash: 'sha256:f7248647af2ef68b4db6d7ad380a61358eb3f7eed84cdba43e720a1bfb45872a'
related:
  - "[[2026-07-27-jobs-tui-research]]"
  - "[[2026-06-11-service-jobs-operability-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-24-operator-feedback-hardening-adr]]"
  - "[[2026-07-21-managed-log-contract-adr]]"
  - '[[2026-07-27-jobs-tui-interrupt-and-terminal-handoff-reference]]'
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

Implementation surfaced a fifth point neither record anticipated: replacing the reprint loop
replaces its exit contract too. The loop reported the conventional interrupted status on
Ctrl+C, while an owned-screen application absorbs the interrupt into its own event loop and
returns normally - and it holds terminal state, the alternate screen and the cursor, that
only an unwind gives back. What the command reports on the way out, and what it owes the
terminal, is measured in `2026-07-27-jobs-tui-interrupt-and-terminal-handoff-reference`.

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
- The live path is refused in combination with structured output, so no caller can request it
  and parse an envelope from it
  (`2026-07-27-jobs-tui-interrupt-and-terminal-handoff-reference`).
- Both an interrupted status and a normal one are reachable on this command depending only on
  who handles the signal: absent the interface, the entry point's own guard reports the
  conventional interrupted status
  (`2026-07-27-jobs-tui-interrupt-and-terminal-handoff-reference`).
- Status and stream cleanliness cannot distinguish an application that unwound from one that
  exited without unwinding; only the terminal teardown sequence can
  (`2026-07-27-jobs-tui-interrupt-and-terminal-handoff-reference`).

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

**Interrupt status.** Restoring the reprint loop's interrupted status was rejected. It would
have to be manufactured, by catching an interrupt the interface has already absorbed and
re-reporting it, in order to describe a failure that did not occur: the operator asked to see
the jobs and saw them. It would also make Ctrl+C and the quit binding report differently for
the same gesture - leaving the view - on a surface where they are the same gesture. The
argument for it is consistency with every other interrupt in this CLI, which is real but
weaker here, because no caller can read this command's status programmatically at all.
Reporting success on the operator leaving the view was chosen, matching the quit binding.

**Terminal handoff.** Treating the screen as the terminal's problem was rejected. The
application takes the alternate screen and the cursor, and an exit path that skips the unwind
returns neither, leaving a working shell rendering as a dead one. Requiring every exit path
to complete the unwind was chosen, and made a verified obligation rather than an assumed one.

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
- Leaving the view is a success. An interrupt and the quit binding report the same status,
  and the command's documented exit line carries no interrupted status.
- Every exit path completes the unwind: the alternate screen is left and the cursor restored
  before the process ends. This holds for the interrupt as much as for the quit binding.
- The handoff is verified on the bytes the child actually emits, ordered - entering the screen
  before leaving it, restoring the cursor after - and never on a status alone, which cannot
  distinguish an unwind from a hard exit.

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

The interrupt needs no handler. The application absorbs it and returns, and the value of
adding one would be to report a failure that did not happen. The obligation that does need
code is the guard: a spawned CLI on its own console, a genuine console control event, and
assertions over the child's raw bytes for the ordered teardown, since a substituted sleep
raising a constructed exception exercises none of the delivery path and no status can
evidence an unwind.

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

The exit status follows from what the command is for. A status describes whether the caller
got what they asked for, and an operator who watched the jobs and then left got exactly that;
an interrupted status here would be describing the keystroke rather than the outcome. The
consistency argument against this is the strongest one available and is worth stating
plainly: this command now reports its interrupt differently from every other command in the
CLI. It is accepted because the surface it applies to cannot be read programmatically, so the
distinction has no consumer to serve, and because on an owned screen Ctrl+C is the same
gesture as the quit binding rather than an abort of work in progress.

What replaces it as the real obligation is the terminal handoff, which is the thing an
operator actually suffers when it is wrong. A status is invisible to someone watching a
screen; a shell left on the alternate buffer with a hidden cursor looks broken. That failure
is reachable from an exit path that skips the unwind while still reporting success and
printing no traceback, so nothing about the status or the streams can catch it. Only the
teardown bytes can, which is why the guard reads them and why the record names them.

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

The previous interrupted status on this command is gone, and a caller that distinguished it
from success no longer can. Nothing supported could have been that caller, since the live path
refuses structured output, but a script testing the status of an interactive command it should
not have been running will now read success.

This command's interrupt reports differently from the rest of the CLI, where the entry point's
guard still reports the conventional interrupted status. That divergence is deliberate and
scoped to the owned-screen surface; it is not licence to change any other command's interrupt,
and a second interface would inherit this record's reasoning rather than the entry point's.

Verifying the handoff costs a real spawned process on its own console per run, which is slower
and more elaborate than any in-process substitute, and the technique is platform-specific.
The assertions read escape sequences, so a rendering stack that changed how it takes and
releases the screen would require updating them - deliberately, and visibly in the diff.
