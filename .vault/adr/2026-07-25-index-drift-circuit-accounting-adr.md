---
tags:
  - '#adr'
  - '#index-drift-circuit-accounting'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-25-index-resume-drift-race-adr]]"
  - "[[2026-07-25-index-resume-drift-race-research]]"
  - "[[2026-07-21-large-index-resilience-adr]]"
  - '[[2026-07-25-document-index-drift-parity-adr]]'
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #adr) and one feature tag.
     Replace index-drift-circuit-accounting with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     Status convention: the H1 status value is one of proposed, accepted,
     rejected, superseded, or deprecated. A new ADR starts as proposed; it
     moves to accepted or rejected when the decision is made; it becomes
     superseded when a later ADR replaces it (set by vault adr supersede,
     which also records superseded_by); and deprecated when it is retired
     without a direct successor.

     Amend vs supersede: refinements and concretization rewrite the accepted
     record's body in place (modified: carries the revision); a new ADR with
     supersession is only for a major pivot. One accepted record per
     decision.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `index-drift-circuit-accounting` adr: `the circuit breaker counts faults, not superseded paths` | (**status:** `accepted`)

<!-- DOCUMENT BOUNDARY:
     This record owns the decision and only the decision. Grounding evidence
     lives in the related research/reference documents and is cited by stem
     (e.g. `2026-02-04-editor-demo-research`), never restated - a restated
     fact forks and goes stale. A fact this record needs but the grounding
     lacks is added to the grounding first, then cited. -->

## Problem Statement

The indexing circuit breaker counts a failed run toward opening the circuit. Once
the code index gains a drift signal that supersedes a racing path and re-records
it (`2026-07-25-index-resume-drift-race-adr`), drift outcomes become routine
events on any tree being edited. If they are counted as failures the breaker
opens precisely when a tree is busy, which is when indexing is most needed and
when the retry is most likely to succeed.

The breaker's counting rule must therefore be decided before the drift signal
ships, not after it produces its first false trip.

## Considerations

- The breaker exists to stop retrying genuine faults, per
  `2026-07-21-large-index-resilience-adr`.
- A superseded path is the drift mechanism working as designed, not a fault
  (`2026-07-25-index-resume-drift-race-research`).
- Drift frequency scales with edit rate, so a counting rule that treats drift as
  failure degrades worst on the busiest trees.
- Silence is not acceptable either: an operator must be able to see that drift
  is occurring and how often.

## Considered options

- **Count every failed run, drift or fault.** Simplest, and what happens today
  by default. Rejected: it opens the breaker on healthy behaviour and does so
  hardest on active trees.
- **Count drift at a reduced weight.** Preserves some backpressure against
  pathological churn. Rejected: the weight is unjustifiable — no evidence
  supports any particular fraction, and it reintroduces the false trip at a
  slower rate rather than removing it.
- **Count faults only; record drift separately.** Chosen.

## Constraints

- The breaker's existing fault accounting is unchanged; this record narrows what
  qualifies as a fault, and adds no new state machine.
- Drift outcomes must remain observable through the existing job and status
  surfaces rather than a new reporting channel.
- Distinguishing drift from fault requires the typed drift signal introduced by
  `2026-07-25-index-resume-drift-race-adr`; this record depends on it and does
  not ship before it.

## Implementation

A run outcome carries whether it ended in a fault or in drift remediation. The
breaker increments on faults only. Drift outcomes increment a separate counter
that is reported alongside job state, so an operator sees drift volume without
the breaker reacting to it.

A run that both drifted and faulted counts as a fault. Drift never subtracts
from the fault count or resets it.

## Rationale

The knockout is directional: counting drift makes the system least available
exactly when it is most exercised. A breaker that opens because a tree is being
edited has inverted its own purpose, since the condition it reacts to is
indistinguishable from normal use.

Reduced weighting fails for a different reason — it requires a number no
evidence supports, and any nonzero weight preserves the inversion at a slower
rate.

## Consequences

The breaker stops reacting to edit rate and reacts only to faults, which is what
it was built for. Drift volume becomes a visible operational signal in its own
right, which is more useful than it was as an undifferentiated failure count.

Honestly framed: removing drift from the count also removes the accidental
backpressure it provided. A tree churning fast enough to exhaust per-path retry
budgets every generation will now keep being retried rather than being cut off.
That is the correct behaviour — the paths are genuinely stale and genuinely
worth retrying — but it means drift volume is the signal an operator must watch,
and it is the reason drift gets its own counter rather than being merely
uncounted.
