---
tags:
  - '#plan'
  - '#jobs-tui'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:a1d2cb00f5982133d8f9e430c2c8cc68a34ce2e27a5c3769c8ab1999b460efb3'
tier: L2
related:
  - '[[2026-07-27-jobs-tui-adr]]'
  - '[[2026-07-27-jobs-tui-research]]'
---

# `jobs-tui` plan

### Phase `P01` - service-side completion estimate

Publish a windowed progress rate and a derived remaining-time estimate on the job liveness projection, so every consumer reads one answer and the estimate is null wherever it would be a guess.

- [x] `P01.S01` - Retain a bounded window of progress samples per job so a rate can be derived from change over time rather than from a single point; `src/vaultspec_rag/jobs.py`.
- [x] `P01.S02` - Derive a windowed completion rate and remaining-time estimate on the liveness projection, returning null for queued, paused, terminal, uncountable and under-sampled work; `src/vaultspec_rag/server/_routes_jobs.py`.
- [x] `P01.S03` - Prove the estimator declines to guess: assert null for each non-countable state and that a steady rate yields the expected remaining seconds; `src/vaultspec_rag/tests/`.

### Phase `P02` - textual dependency and application shell

Carry textual as a core dependency and stand up the application that owns the screen behind the live jobs path, refreshing off-thread against the existing bounded query.

- [x] `P02.S04` - Add textual to the core dependency list and refresh the lockfile; `pyproject.toml`, `uv.lock`.
- [x] `P02.S05` - Create the application module that owns the screen, composing the table, the log region and the footer from one layout; `src/vaultspec_rag/cli/_jobs_tui.py`.
- [x] `P02.S06` - Refresh off the event loop on an interval through a thread worker over the existing bounded jobs query, keeping the fetch identical to the one-shot path; `src/vaultspec_rag/cli/_jobs_tui.py`.

### Phase `P03` - the row view

Render one multi-line row per job carrying state, operation, full project path, progress, elapsed and remaining time, with a liveness indicator and width breakpoints driving one composition.

- [x] `P03.S07` - Build the multi-line row from the job payload: state, operation, full project path, progress, elapsed and remaining time, keyed so a row survives reordering and removal; `src/vaultspec_rag/cli/_jobs_tui.py`.
- [x] `P03.S08` - Reuse the existing job label helpers rather than restating their vocabulary, and promote the full project root out of the detail-only render path; `src/vaultspec_rag/cli/_service_jobs.py`, `src/vaultspec_rag/cli/_jobs_tui.py`.
- [x] `P03.S09` - Animate a liveness indicator that distinguishes a refreshing view from a frozen one, and stamp the last successful refresh; `src/vaultspec_rag/cli/_jobs_tui.py`.
- [x] `P03.S10` - Drive layout and column visibility from reported terminal width, collapsing to tabs when narrow and placing the log region beside the table when wide; `src/vaultspec_rag/cli/_jobs_tui.py`, `src/vaultspec_rag/cli/_jobs_tui.tcss`.

### Phase `P04` - control and logs

Bind the shipped job controls to the selected row, gated on its published capability flags, and scope a bounded log pane to the selection through the existing per-job filter.

- [x] `P04.S11` - Bind pause, resume, stop, retry and delete to the selected row through the existing typed transports, carrying the expected-revision guard; `src/vaultspec_rag/cli/_jobs_tui.py`.
- [x] `P04.S12` - Enable each action from the selected job's published capability flags, disabling rather than hiding what the service would reject; `src/vaultspec_rag/cli/_jobs_tui.py`.
- [x] `P04.S13` - Render a requested control as requested until the service acknowledges it, so a desired state is never shown as an observed one; `src/vaultspec_rag/cli/_jobs_tui.py`.
- [x] `P04.S14` - Scope the log region to the selected job through the existing bounded per-job filter, refreshing it with the selection; `src/vaultspec_rag/cli/_jobs_tui.py`.

### Phase `P05` - removal and verification

Delete the reprint loop it replaces, prove the interface on rendered bytes driven by real key presses, and run the gates.

- [x] `P05.S15` - Route the live jobs path to the application and delete the clear-and-reprint loop, its refresh banner and its watch-status text; `src/vaultspec_rag/cli/_service_jobs.py`.
- [x] `P05.S16` - Prove the interface on rendered output driven by real key presses: one assertion per action binding, plus the capability gate, the narrow and wide layouts, and the estimate column; `src/vaultspec_rag/tests/`.
- [x] `P05.S17` - Update the operator documentation for the replaced live view and the new controls; `docs/`, `README.md`.
- [x] `P05.S18` - Run lint, format, type-check and the touched test modules, then commit by explicit pathspec; `repository gates`.

## Description

Executes `2026-07-27-jobs-tui-adr`, grounded in `2026-07-27-jobs-tui-research`. The live
jobs path stops being a reprint loop and becomes an application that owns the screen, with
per-row control, a bounded log region scoped to the selection, and a completion estimate the
service computes rather than the view.

`P01` is service-domain and stands alone: it publishes the one signal the payload lacks.
`P02` through `P04` build the interface on top of it. `P05` removes the surface it replaces
and proves the result on rendered output.

## Steps

Retained-plan evidence: the milestone and wave sections in this document are the step inventory; this canonical section preserves that inventory without duplicating it.

## Parallelization

`P01` shares no file with `P02`-`P04` and may run alongside them; only `P03.S07` consumes its
output, and it degrades to an absent estimate until `P01.S02` lands.

`P02` is a hard prerequisite for `P03` and `P04` - both edit the module `P02.S05` creates.
Within `P03`, steps `S07`-`S10` touch one module and are sequential. Within `P04`, `S11`-`S13`
are sequential for the same reason; `S14` touches a separate region and may run beside them.

`P05` is strictly last. `P05.S15` must not land before `P02.S05`, or the live path routes to a
module that does not exist.

## Verification

- The estimator returns null for queued, paused, terminal, uncountable and under-sampled work,
  and returns the arithmetically expected remaining seconds for a steady synthetic rate.
- The structured and one-shot jobs paths produce their current output unchanged, save for the
  two added nullable fields.
- Each of pause, resume, stop, retry and delete has an assertion that drives its real key press
  through the application and observes the effect on rendered output.
- An action absent from a job's published capability flags renders disabled, and pressing its
  key issues no request.
- A narrow and a wide terminal each render their intended layout from the same composition.
- The live path refuses combination with structured output, and the reprint loop, its refresh
  banner and its watch-status text are absent from the tree.
- Lint, format and type-check are clean over the touched files, and the touched test modules
  pass.
