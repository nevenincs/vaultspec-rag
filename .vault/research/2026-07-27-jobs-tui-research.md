---
tags:
  - '#research'
  - '#jobs-tui'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-06-11-service-jobs-operability-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-24-operator-feedback-hardening-adr]]"
  - "[[2026-07-21-managed-log-contract-adr]]"
  - "[[2026-04-12-index-progress-bars-adr]]"
---

# `jobs-tui` research: `an interactive operator TUI for the jobs surface`

## Findings

### Retained preamble

The live jobs view is a clear-screen reprint loop, not an interface. `--watch` fetches
the same bounded collection the one-shot path fetches, clears the console, and reprints
one line per job on a fixed interval (`src/vaultspec_rag/cli/_service_jobs.py:1076`).
An operator watching it cannot select a row, cannot act on one, cannot see which project
a job belongs to, and cannot tell how long the job has left. Every control the service
already exposes - pause, resume, stop, retry, delete - is reachable only by leaving the
view, reading a truncated job id off the screen, and typing a second command.

The evidence below is that almost none of the missing capability is missing from the
*service*. The control endpoints, the capability flags that gate them, the per-job log
filter, and the project root are all already on the wire. Two things are genuinely
absent: a completion estimate, and any rendering surface capable of input.

### The row is a single line built from a fixed format string, and it drops the path

Each job renders as one soft-wrapped line assembled inline in the feed loop
(`src/vaultspec_rag/cli/_service_jobs.py:606`): a state prefix glyph, a wall-clock
stamp, a phase word, an operation label, a parenthesised short job id, and a detail
clause. There is no column model, so nothing aligns and nothing can be widened.

The project appears only as a *basename*. `_project_label` splits the initiator's
`project_root` and returns its last path segment
(`src/vaultspec_rag/cli/_service_jobs.py:216`), which is why the feed says `main` for
every worktree of every project that happens to end in that segment. The full root is
already carried on the payload and is already rendered - but only in the single-job
detail view (`src/vaultspec_rag/cli/_service_jobs.py:963`). For a machine running several
roots of one repository concurrently, the collection view is ambiguous precisely where it
matters. Adding a path element is a rendering change, not a contract change.

### Elapsed time is truthful; remaining time does not exist anywhere

The service computes `runtime_seconds` per job from the record's own timestamps, and
correctly declines to compute it for queued work, freezes it at `finished_at` for
terminal work, and freezes it at `state_changed_at` for paused work
(`src/vaultspec_rag/server/_routes_jobs.py:249`). Elapsed time therefore needs no new
signal - only a place to display it per row.

Remaining time has no basis in the current payload. `JobProgress` carries `step`,
`completed`, `total`, and `last_updated` and nothing else
(`src/vaultspec_rag/job_models.py:225`), and the projection enriches liveness only with
ages and a stall flag (`src/vaultspec_rag/server/_routes_jobs.py:377`). A point sample of
`completed`/`total` plus `runtime_seconds` yields an average-rate estimate, but that
estimate is wrong in the way that matters: an index job's steps have very different
per-unit costs, so a figure averaged over discovery and chunking understates the embed
phase it is supposed to predict. A defensible estimate needs a windowed rate held across
samples, which is state the service keeps and the client does not.

Where that rate is computed is not a free choice. The service-surface rule requires
health, status, jobs, logs and search diagnostics to be service-domain behaviour with the
entry points adapting to it. A rate estimated inside a terminal view would be invisible
to `--json` and to the MCP surface, and a second estimator would eventually appear in one
of them. `_job_with_liveness` is the established home for every other derived liveness
figure and is the natural home for this one.

### Every row action already exists as an endpoint, and the payload already says which are legal

Pause, resume, stop, retry, and delete are shipped CLI verbs over typed transports
(`src/vaultspec_rag/cli/_service_jobs.py:1396` onward), each resolving an exact job id and
sending an expected-revision guard. The desired-state model behind them is the accepted
cooperative-unwind contract; a view binding these does not need new service behaviour.

Crucially, legality is already published. `JobCapabilities` carries `pausable`,
`resumable`, `cancellable`, `retryable`, `deletable`, and `force_killable`
(`src/vaultspec_rag/job_models.py:168`) and the record's capability map reaches the
projection (`src/vaultspec_rag/server/_routes_jobs.py:500`). A row's available actions can
be derived from the job rather than guessed from its phase, which is what makes per-row
control honest: an action that would be rejected can be shown as unavailable before it is
pressed rather than after.

There is no scheduling capability of any kind. `retry` creates a linked retry for a
*terminal* job; nothing defers, re-times, or requeues live work. An operator affordance
named "reschedule" therefore either maps onto `retry` or requires a new service-domain
feature with its own admission and persistence behaviour.

### Logs are already joinable to a job

The managed-log route accepts a `job_id` filter alongside `contains`, `source`, and a
clamped line limit, and the CLI already passes it through
(`src/vaultspec_rag/cli/_service_logs.py:72`). A log pane scoped to the selected row needs
no new endpoint - it needs the selection to drive the filter argument. The managed-log
contract also bounds and clamps the response, so a live pane cannot pull an unbounded
tail.

### The existing render channel structurally cannot host an interface

The shared Rich console is constructed with interactivity forced off, which is the fault
the operator-feedback record diagnosed: a transient live region renders zero times on a
non-interactive console, so three separate commits' worth of startup progress shipped into
a dead channel. That record also establishes, on reproduced output, that two Rich consoles
cannot coordinate one live region - foreign prints weld themselves onto the spinner frame.

Both findings bear directly here. A live interface cannot be built on the shared console
as configured, and building a second console beside it is the approach that record
rejected on evidence. Whatever renders this view must own the screen outright.

That record also sets the verification bar: operator feedback is a rendered artefact, and
is verified on rendered bytes rather than on the string a function returned. A view whose
tests assert on a model would repeat the exact failure that record was written about.

### Option space for the rendering stack

`rich>=14.3.2` is already a core dependency; `textual` appears nowhere in the tree or the
lockfile. Three options were considered.

A hand-rolled loop on `rich.Live` adds no dependency but requires writing a key reader per
platform (`msvcrt` on Windows, `termios` elsewhere), a focus and selection model, scrolling,
and a layout engine that reflows on resize - several hundred lines reimplementing solved
problems, and a Windows key-input path this project would then own.

`textual@6.6.0` supplies all of it: `DataTable` with stable row keys that survive sort and
deletion, `TabbedContent`, `Footer` bindings driven by `BINDINGS`, `set_interval` for the
refresh and for animation, `@work(thread=True)` with `call_from_thread` for the blocking
HTTP fetches, `RichLog` for the log pane, reactive attributes with `bindings=True` so the
footer re-evaluates as state changes, and `check_action` returning `None` to *disable* a
key rather than hide it - which is the precise affordance the capability flags call for.
It owns the screen, which resolves the two-consoles problem structurally, and `App.run_test`
with a `Pilot` drives real key presses against a real render, which is what verifying on
rendered bytes requires. Its runtime dependencies are `rich` (already present),
`markdown-it-py`, `platformdirs`, and `typing-extensions` - negligible beside `torch`.

Carrying `textual` as an optional extra mirrors the `[mcp]` precedent, but the reasoning
there does not transfer: `[mcp]` is optional because the CLI never imports `mcp`, whereas
the CLI is this view's only consumer. An extra also forces a fallback view for absent
textual, which is a second implementation of the same surface - the duplication the
canonical-code rule exists to prevent.

### Responsiveness is a width-breakpoint problem

"Mobile responsive" in a terminal means adapting to the width the emulator reports. Textual
exposes `App.HORIZONTAL_BREAKPOINTS`, which stamps a CSS class onto the screen as width
crosses a threshold, plus `on_resize` and `self.size` for anything the stylesheet cannot
express. A wide terminal can therefore place the log pane beside the table and a narrow one
can collapse the same content into tabs, from one composition, without a second layout path.
Column visibility can be driven the same way.

### Not investigated

Web delivery via `textual-serve` was not evaluated; it is a separate transport decision and
nothing in the request requires a browser. Mouse interaction beyond textual's defaults was
not evaluated. Whether the admission-limiter wait should surface as a distinct progress
state was not evaluated - the current view already labels it
(`src/vaultspec_rag/cli/_service_jobs.py:380`) and no evidence suggests that label is wrong.

### What the decision must settle

- Whether `textual` enters as a core dependency, an optional extra, or not at all.
- Whether the TUI replaces `server jobs --watch` - deleting the reprint loop - or arrives as
  a separate verb alongside it.
- Where the completion estimate is computed, and what makes it honest enough to display.
- Whether "reschedule" maps onto the shipped `retry` or authorises a new scheduling
  capability.

## Sources

- `src/vaultspec_rag/cli/_service_jobs.py:216` - project label reduced to a basename
- `src/vaultspec_rag/cli/_service_jobs.py:380` - admission-wait label
- `src/vaultspec_rag/cli/_service_jobs.py:606` - the single-line row format
- `src/vaultspec_rag/cli/_service_jobs.py:963` - full project root, detail view only
- `src/vaultspec_rag/cli/_service_jobs.py:1076` - the clear-and-reprint watch loop
- `src/vaultspec_rag/cli/_service_jobs.py:1396` - job control verbs
- `src/vaultspec_rag/cli/_service_logs.py:72` - per-job log filter
- `src/vaultspec_rag/job_models.py:168` - `JobCapabilities`
- `src/vaultspec_rag/job_models.py:225` - `JobProgress`
- `src/vaultspec_rag/server/_routes_jobs.py:249` - `runtime_seconds`
- `src/vaultspec_rag/server/_routes_jobs.py:377` - the liveness projection
- `src/vaultspec_rag/server/_routes_jobs.py:500` - capability map on the projection
- `pyproject.toml:19` - core dependency list; `rich` present, `textual` absent
- https://textual.textualize.io - `textual@6.6.0` widget, worker, binding, and
  breakpoint behaviour
