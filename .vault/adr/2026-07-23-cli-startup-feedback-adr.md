---
tags:
  - '#adr'
  - '#cli-startup-feedback'
date: '2026-07-23'
modified: '2026-07-23'
related:
  - "[[2026-07-23-cli-startup-feedback-research]]"
---

# `cli-startup-feedback` adr: `publish structured startup progress; the CLI polls and renders it` | (**status:** `accepted`)

## Problem Statement

`server start` blocks to readiness while the daemon provisions Qdrant and loads
GPU models, and the operator sees only a static wait - indistinguishable from a
hang. A decision is needed on how the CLI reports genuine, live per-stage
progress when the work runs in a separate daemon process, so that the feedback
is a real reflection of daemon state rather than a hand-rolled guess. The
grounding (`2026-07-23-cli-startup-feedback-research`) establishes the option
space; this record picks the contract.

## Considerations

- The CLI and the startup work sit on opposite sides a process boundary the
  daemon spawns; the only readable channels are `/health` (post-bind) and the
  published status/discovery view (`2026-07-23-cli-startup-feedback-research`).
- The cold-start stages differ in measurable fidelity: downloads expose bytes,
  model load exposes an N-of-M count, a reconcile is spinner-only.
- A Rich-decoupled progress-reporter vocabulary already exists from the
  `index-progress-bars` decision, but it terminates inside the daemon.
- The authoritative status snapshot is rewritten under a machine-singleton
  write lock, so a chatty percentage feed would contend on that lock.
- Publication must be best-effort: a progress-write failure must never fail
  startup, and `--json` mode must still emit exactly one envelope.

## Considered options

- **Daemon publishes structured progress into the existing status view; CLI
  polls and renders (chosen).** Extends the shipped `phase_detail` increment
  with an optional structured stage descriptor. Reuses the atomic status write
  and the existing poll loop; bounded update frequency avoids lock contention.
- **Dedicated high-cadence progress side-file the CLI tails.** Rejected for the
  default scope: needed only for byte-granular download bars, which are a
  follow-on; a second file adds consistency and cleanup surface for a fidelity
  the first release does not require.
- **CLI parses structured progress out of the daemon log.** Rejected: brittle
  prose parsing, and the log is a fallback diagnostic surface, not a contract.
- **Block silently / keep the coarse single-string label.** Rejected: it is the
  status quo the feature exists to remove.

## Constraints

- No frontier-technology or unstable-parent risk: the discovery/status view, the
  start poll loop, and the progress-reporter vocabulary are all shipped,
  accepted surfaces this feature extends rather than introduces.
- Byte-granular download percentages depend on the Hugging Face and
  pinned-binary downloaders exposing incremental callbacks; the research flags
  this as unverified, so determinate download bars are explicitly out of the
  first increment and gated behind that check in the plan.
- The published progress field is advisory: consumers that read only the coarse
  `phase` (`warming`/`running`) must be unaffected, so no discovery-schema
  version bump is permitted for the additive field.

## Implementation

The daemon carries a small structured startup-progress descriptor - a stable
stage identifier, a human label, and an optional `done`/`total` pair - on its
discovery/status view, published at each cold-start stage boundary
(provisioning, model load, reranker) through the same best-effort publisher that
already carries `phase_detail`. Where a stage exposes a discrete count (models
loaded of the configured set) the daemon fills `done`/`total`; where it does not
(reconcile), it publishes the label alone. The CLI start wait reads that
descriptor each poll and renders a spinner that names the current stage,
appending a determinate `(done/total)` count to the stage label whenever
`total` is present (the pragmatic determinate signal for a small-N startup
count, in place of a graphical bar), and falls back to the plain label when the
field is absent so an older daemon still works.
The coarse `phase` remains the authoritative machine-readable state and the
`--json` path is unchanged. Service startup is the surface this feature owns;
index-build progress remains the jobs-operability surface and is not duplicated
here. The already-shipped `phase_detail` string (`034a0dd4`) is the first
increment of this contract, which this record formalizes and extends to the
structured count.

## Rationale

The publish-and-poll contract wins on a knockout criterion the alternatives
cannot meet: it is the only shape that reports true daemon state across the
process boundary the research shows is unavoidable, while reusing the atomic
status write so a partially-written progress record can never be read. Extending
the existing view rather than adding a side channel keeps the first increment
small and contention-safe (bounded stage-boundary publishes, not a per-byte
feed), and defers the one fidelity that would need a second transport - true
download percentages - behind the unverified-callback check the research names.
Reusing the accepted progress-reporter vocabulary keeps the daemon's internal
signal and the published contract aligned rather than forking a second grammar.

## Consequences

The operator sees which stage a cold start is in and, for model load, how many
models remain - a live signal, not a spinner guess - and a stalled stage is now
visible. The additive, advisory field keeps every existing status consumer and
the `--json` contract intact with no schema bump. The honest cost is that the
first increment stops at stage-plus-count granularity: true download-percentage
bars wait on confirming the downloaders expose incremental callbacks, and until
then the provisioning and first-run weight-download stages render as named
spinners rather than filling bars. Publishing progress at stage boundaries also
introduces a small, bounded number of extra best-effort status writes during
startup, which the machine-singleton lock already serializes safely.
