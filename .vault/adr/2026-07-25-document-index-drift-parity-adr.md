---
tags:
  - '#adr'
  - '#document-index-drift-parity'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-25-index-resume-drift-race-adr]]"
  - "[[2026-07-25-index-resume-drift-race-research]]"
  - '[[2026-07-25-index-drift-circuit-accounting-adr]]'
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #adr) and one feature tag.
     Replace document-index-drift-parity with a kebab-case feature tag, e.g. #foo-bar.
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

# `document-index-drift-parity` adr: `the document index keeps its resume semantics and does not adopt the drift signal` | (**status:** `accepted`)

<!-- DOCUMENT BOUNDARY:
     This record owns the decision and only the decision. Grounding evidence
     lives in the related research/reference documents and is cited by stem
     (e.g. `2026-02-04-editor-demo-research`), never restated - a restated
     fact forks and goes stale. A fact this record needs but the grounding
     lacks is added to the grounding first, then cited. -->

## Problem Statement

The code index gains a drift signal that supersedes a racing path and re-records
it rather than failing the run (`2026-07-25-index-resume-drift-race-adr`). The
document index runs its own checkpoint and resume machinery over the same
ledger. Whether it adopts the same mechanism has to be decided, because leaving
it implicit invites a later contributor to copy the code path across on the
assumption that parity is always desirable.

## Considerations

- The guard that produces the failure fires only where a path carries
  same-generation indexed evidence before its own units are recorded
  (`2026-07-25-index-resume-drift-race-research`).
- The code resume path produces that state; the document path does not reach it.
- Mechanism added without a defect to answer is mechanism that must still be
  maintained, tested, and reasoned about at every future change.
- Symmetry between the two indexes has value for readers, but only where the
  underlying behaviour is genuinely symmetric.

## Considered options

- **Adopt the drift signal in the document index for parity.** Rejected: it adds
  a retry path, a per-path budget, and a deferral outcome to answer a failure
  that path cannot currently produce.
- **Extract a shared drift component both indexes consume.** Rejected for now:
  a shared abstraction drawn from one real caller and one hypothetical one is
  shaped by the hypothetical, and the code path's requirements are still
  settling as it is seamed.
- **Keep the document index resume semantics unchanged.** Chosen.

## Constraints

- This record decides scope, not behaviour: the document index is not modified,
  and its existing resume semantics are the specification.
- The decision is conditional on the guard's reachability. If the document path
  is later changed such that a path can carry same-generation indexed evidence
  before its units are recorded, that change carries a new decision with it.

## Implementation

Nothing is implemented in the document index. The seam and drift owner
introduced for the code index are not generalised across both paths, and the
document checkpoint continues to use its current resume behaviour unchanged.

The drift owner is built as a code-index component. Should the document path
later need it, promoting it to a shared component is a refactor with two real
callers to shape it, which is the point at which the shared abstraction can be
drawn honestly.

## Rationale

The decisive fact is reachability: the failure mode does not exist on this path,
so adopting its remedy buys nothing and costs permanent surface area. Parity is
a reason to align behaviour where behaviour differs without justification; it is
not a reason to install a mechanism against a defect that cannot occur.

Deferring the shared abstraction follows from the same evidence. An interface
extracted to serve one real caller encodes that caller's shape and then
constrains the second one when it finally arrives.

## Consequences

The document index stays smaller and its resume path stays as simple as it is
today. The code index's drift work proceeds without carrying a second caller's
requirements while its own seams are still being cut.

Honestly framed: the two indexes now differ in how they handle a resumed run,
and a reader comparing them will find the asymmetry. That asymmetry is real and
justified, and this record is the answer to the question it provokes.

The conditional in the constraints is a live obligation, not a formality:
whoever changes the document path's ordering so that indexed evidence can
precede its own unit records is the one who must revisit this decision.
