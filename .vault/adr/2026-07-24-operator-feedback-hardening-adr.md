---
tags:
  - '#adr'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - "[[2026-07-23-cli-startup-feedback-adr]]"
  - '[[2026-07-24-operator-feedback-hardening-audit]]'
---

# `operator-feedback-hardening` adr: `operator feedback is a rendered artefact, not a produced string` | (**status:** `accepted`)

## Problem Statement

An operator reported that `server start` produced no output whatsoever and then
failed with `Waited: 300s`. Both halves were true and neither was a hang: the
daemon came up in 56 seconds and answered every health poll, while the command
rendered nothing and then refused the result it had been given. The grounding
for everything below is `2026-07-24-operator-feedback-hardening-audit`, which
establishes the measurements and the surfaces affected; they are cited here, not
restated.

The preceding decision, `2026-07-23-cli-startup-feedback-adr`, chose to have the
daemon publish structured startup progress that the CLI polls and renders. That
decision was correct and its publishing half shipped correctly - the daemon
stamps a stage label, and a determinate done/total count, throughout cold start.
Nothing consumed it. The shared Rich console was constructed with interactivity
forced off, and a transient live region renders zero times on a non-interactive
console, so every status line the CLI produced was discarded before reaching a
terminal.

That record's plan closed every step. Three separate commits over six weeks
enriched the status string, and each shipped into the dead channel. A decision
is needed on what makes operator feedback verifiable, because the existing
records show that deciding what to *say* does not establish that anything is
*shown*.

## Considerations

- Interactivity was being answered twice and inconsistently: once from the real
  stdout stream, once from Rich's own terminal detection, which honours
  `FORCE_COLOR`. The second answer governed the index progress bars.
- Rich positions a live region from what it alone rendered, so a line printed
  through a second console on the same stream lands concatenated onto the
  spinner frame. The start path genuinely prints warnings mid-region.
- A broker-facing verb must emit exactly one structured document on stdout, so
  progress cannot share that channel under `--json`.
- `/health` reports one status word covering two unrelated things: whether the
  service can serve, and whether its job history is clean. Only the first gates
  a start.
- Job records persist across restarts, so a job-history verdict outlives the
  process that earned it.
- The startup failure path exits through `os._exit`, which makes any `raise`
  after it unreachable and any unlogged exception unrecoverable.

## Considered options

- **Treat rendering as part of the contract, and verify on rendered bytes
  (chosen).** Costs a stricter test obligation on every feedback surface.
- **Enrich the published stage vocabulary further.** Rejected: this is what the
  three prior attempts did, and the fidelity of a string nobody sees is zero.
- **Give the reporter its own console so it can force interactivity locally.**
  Rejected on evidence: reproduced output showed foreign prints welded onto the
  spinner frame, because two consoles cannot coordinate one live region.
- **Loosen the start wait's deadline.** Rejected: it treats a wrong verdict as a
  timing problem, and a serving daemon would still be reported as a failure.

## Constraints

No frontier or unstable-parent risk. Every surface this record changes - the
console, the discovery view, the health payload, the start poll loop - is
shipped and accepted. The one external dependency is Rich's rule that a
transient live region renders only while its console reports itself interactive,
which is version-observable and is pinned by a guard test rather than assumed.

## Implementation

Interactivity is resolved once, from the real stdout stream rather than from
terminal detection that environment variables can move, and the shared console
carries that answer to every consumer - the startup reporter and the indexer's
progress bars alike.

Progress placement follows from how Rich coordinates a live region. On a
terminal, the region and the lines printed around it share one console, which is
what lets the frame be erased and repainted around them. Off a terminal there is
no region, so the same activity is reported as plain rate-limited lines on
stderr, keeping stdout the parseable result channel. Under `--json` both are
silent.

The start wait completes when the daemon can serve - models resident, vector
backend live, read from structured fields - rather than when it reports the word
`ready`. A serving-but-degraded daemon is a success that carries its degradation
reasons into both the human lines and the envelope.

Health degradation from job history is bounded to the current process
generation. The failure record is retained and reported; it stops passing a
verdict on a process that did not run it.

A refusal states its cause. The startup failure handler logs the exception
before the process exit, ordered so the frames precede the one-line cause,
because the CLI surfaces only the final lines of that log.

## Rationale

The knockout criterion is that every prior attempt satisfied its own tests. The
distinguishing property of this record is not what it renders but where its
assertions bind: to bytes captured from a console object rather than to the
return value of the function that produced the string. That is the only
assertion any of the three previous attempts would have failed.

Two subsidiary choices follow the same logic. Asserting that rendered output is
merely non-empty is insufficient, because starting and stopping a live region
emits cursor control codes whether or not it ever paints - a byte-count guard
stays green through the exact regression it exists to catch. And the start
verdict reads structured fields rather than the prose reason list, because that
list is display text and is expected to be reworded.

## Consequences

Four operator surfaces that were silent now report continuously, and one line of
console construction revives the search spinner, the warmup spinner, and the
index progress bars together, since all three were failing for the same reason.

The start contract is loosened in a documented way: `server start` now exits 0
against a serving-but-degraded daemon where it previously timed out. A consumer
that treated exit 0 as "no warnings" must read the reasons the envelope now
carries.

The cost is a standing obligation. Any surface whose subject is that an operator
sees something must assert on rendered output, and a guard on that output must
be shown to fail when the rendering is removed. Without it this class of defect
is invisible to a green suite - which is how it survived an accepted decision, a
fully closed plan, and three corrective commits.

A residual gap is recorded rather than closed: verifying a terminal rendering
still needs a real or simulated terminal, so a non-interactive run can confirm
the fallback path and the absence of stdout pollution but not the animated path.
The guard tests construct a terminal-forced console to cover it; a genuine TTY
harness remains absent.
