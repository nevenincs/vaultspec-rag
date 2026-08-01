---
tags:
  - '#adr'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:8e153c1d97baf8d9aaa560268f5625b308bd18e6ac6b5ac87994bd52111820a4'
related:
  - "[[2026-07-23-document-chunk-bounding-research]]"
  - "[[2026-07-23-chunk-id-uniqueness-adr]]"
---

# `document-chunk-bounding` adr: `bound hook-emitted document units and enforce the CUDA ceiling on demand` | (**status:** `accepted`)

## Problem Statement

Document indexing for a hook-backed corpus fails terminally and repeatedly, and
the failures name innocent files. Two defects grounded in
`2026-07-23-document-chunk-bounding-research` compose: preprocess-hook-emitted
units are the one chunk class the pipeline never size-bounds, and the CUDA
ceiling guard enforces the caching allocator's retained pool against the same
ceiling as live demand, so a job fails on the process's fragmentation history
rather than on its own cost. A decision is needed now because the composition makes a resident
service degrade irreversibly with uptime, and because the unbounded-unit path
also discards content silently on runs that report success - a correctness loss
no test currently reports.

## Considerations

- The pipeline already owns bounded chunking for every other content class, and
  the bound is content-epoch tracked on the vault side; hooks are the sole
  exception (`2026-07-23-document-chunk-bounding-research`).
- Point identity must stay unique and replay-stable when one unit becomes many
  chunks; the ledger rejects duplicate ids within a commit unit, and idempotent
  replay depends on deterministic ordering (`2026-07-23-chunk-id-uniqueness-adr`).
- Unit provenance (title, section, anchor, locator) is the retrieval affordance
  hooks exist to provide and must survive splitting.
- The guard is a safety mechanism; weakening it must not remove protection
  against genuine device exhaustion.
- Hook authors are downstream consumers who cannot be required to re-implement
  pipeline-owned invariants.
- The unit schema already bounds title, section, anchor, metadata, and unit
  count, and omits a bound only on the embedded text, so bounding it closes an
  inconsistency in an existing validation surface rather than adding a new one
  (`2026-07-23-document-chunk-bounding-research`).

## Considered options

- **Split unit text through the shared bounded splitter, preserving unit
  metadata on each sub-chunk.** Restores the invariant every other content class
  already holds, at the cost of a point-identity change. Chosen.
- **Reject oversized units back to the hook author as a validation error.**
  Cheap to implement and makes the contract explicit, but pushes a
  pipeline-owned invariant onto every hook, and offers no path for corpora whose
  natural unit legitimately exceeds the model window. Rejected.
- **Leave units verbatim and only raise the CUDA ceiling.** Treats the symptom,
  leaves silent truncation entirely unaddressed, and buys a bounded amount of
  headroom on a fixed device. Rejected.
- **Remove reserved from ceiling enforcement, leaving the existing allocated
  check as the sole gate and reserved as a reported diagnostic.** Keeps the
  enforcement that tracks demand and drops the one that tracks fragmentation
  history. Chosen, paired with the below.
- **Give reserved its own, higher ceiling instead of removing it.** Preserves
  some fragmentation protection without failing well-sized jobs, but requires a
  second tunable whose correct value nobody can derive, and re-creates the same
  failure mode one step further out. Rejected.
- **Bound the split by tokenizer measurement rather than a character budget.**
  Exact where a character heuristic only approximates, but puts tokenizer work
  on a chunking path that runs in CPU-only workers which must not load model
  machinery. Rejected on that constraint, not on accuracy.
- **Release the allocator cache before rebasing the peak counters.** Makes the
  per-job reset mean what its name implies. Chosen as a complement, not a
  substitute - it alone would leave enforcement keyed to a reading that
  fragmentation still perturbs.

## Constraints

- Changing how a unit maps to points changes point identity, so the document
  side needs the same care the code side took: deterministic emit order and an
  ordinal discriminator, or previously indexed corpora churn on the next run.
- The `units is None` text path and the vault path already carry bounded
  splitting; this work must reuse that splitter rather than introduce a third
  bounding rule.
- No parent feature is unstable. The chunk-id uniqueness work this builds on is
  landed and reviewed; the reserved-vs-allocated change touches a guard whose
  contract is exercised by existing job-resilience coverage.
- The truncation limit is a property of the loaded dense model, so the effective
  bound must derive from the model's sequence window rather than a hardcoded
  character count that silently drifts when the model changes. The reused
  splitter is character-based, so this derivation is an explicit conversion the
  implementation owes rather than something the splitter provides.
- Chunking runs in CPU-only worker processes that must never load torch, which
  rules out measuring the split with the model's own tokenizer and forces a
  character budget derived from the token window.

## Implementation

Document chunk construction gains a single bounding stage that both branches
share. Where the pipeline currently emits one chunk per hook unit verbatim, it
instead passes each unit's text through the same splitter the raw-text branch
uses, then materializes one chunk per resulting fragment. Every fragment
inherits its parent unit's title, section, anchor, locator, and metadata, so
retrieval provenance is unchanged for units that fit and correctly attributed
for units that split.

The same reserved-to-allocated correction applies to the support-profile CUDA
dimension projection in both indexers, not only to the budget guard. The
managed-service profile's CUDA limit equals the enforcement ceiling, so a
projection computed from reserved would reject a corpus for the same retention
reason the guard no longer fails jobs for, merely renaming the failure as a
corpus-limit rejection.

Point identity gains a fragment discriminator inside the `location` component,
which is the part of the identity payload that distinguishes one unit from
another. This placement is load-bearing rather than incidental: identity takes
the unit ordinal only for units without a locator, and takes the locator triple
otherwise, so a discriminator attached to the unit ordinal alone would not enter
the identity of a locator-bearing unit at all and every fragment of one page
would collide (`2026-07-23-document-chunk-bounding-research`). Extending the
location component covers both branches, which makes ids unique by construction
and stable across replay of an unchanged file, mirroring the guarantee the code
path adopted. The discriminator is carried unconditionally rather than omitted
at zero: a conditional discriminator would make identity depend on the split
bound in force when a unit was written, so the same unit's id would move
silently whenever the bound changed. The identity payload's version field is
bumped accordingly, because the derivation changes for every document.

The splitter is reused rather than reinvented, but its bound is expressed in
characters while the constraint that matters is the encoder's token window. The
character bound is therefore derived from the model's sequence window by a
declared, conservative chars-per-token ratio rather than a hardcoded literal, so
the effective limit tracks a model change instead of silently drifting. Both
document branches - hook units and extracted plain text - draw that
configuration from one shared source carried on the resolved policy, so the two
cannot drift apart the way they did when only one of them was bounded.

The document splitter carries a non-zero overlap, unlike the code path, which
forbids it. The code path's objection is that overlap prepends content from the
preceding chunk into a chunk whose span is a line range, misattributing text to
lines that do not contain it. Document spans are locators naming a unit rather
than exact line ranges, so a fragment that begins with trailing context from its
predecessor remains truthfully attributed to the unit it came from, and the
continuity is worth more than the small duplication.
Tokenizer-measured splitting is the more exact alternative and is not
adopted here: it would put tokenizer work on the chunking path, which runs in
CPU-only worker processes that must not load model machinery.

The unit-text bound and the splitting parameters join the document content
epoch, on the same basis the vault chunk bound already does, so that changing
either triggers a rebuild rather than leaving previously unsplit points in place
with no signal that they are stale.

Splitting makes the pipeline correct for any input, but it leaves the schema
still advertising an unbounded text field, so the unit contract gains an
explicit upper bound on `text` alongside the bounds it already declares for
title, section, anchor, and metadata. The bound is generous - it exists to make
the contract honest and to reject the pathological case at the boundary that
validates it, not to substitute for splitting, which continues to handle every
unit above the model window. This keeps the two mechanisms in their proper
roles: validation states what a unit may be, and splitting guarantees what
reaches the encoder regardless.

The memory budget already enforces the allocated high-water reading against the
ceiling; the change is to stop enforcing the reserved reading against that same
ceiling. Reserved continues to be sampled and reported on job resilience records
and metrics, where it remains the honest signal for fragmentation and device
pressure, but it no longer decides job outcome. The per-job budget
reset additionally releases the allocator cache before rebasing peak counters,
so a job's recorded peaks describe that job rather than inheriting the
process's retention history.

## Rationale

The knockout criterion is that no other option addresses the silent-truncation
finding in `2026-07-23-document-chunk-bounding-research`. Raising the ceiling or
rejecting oversized units both leave a corpus that indexes "successfully" while
discarding the tail of every oversized unit, which is the most damaging of the
observed behaviours precisely because it emits no signal. Splitting is also the
only option that restores consistency: the pipeline already decided, for vault
markdown, raw text, and code, that bounding is the producer-side pipeline's job,
and the hook path is an unintended gap in that decision rather than a
deliberate exemption.

On the guard, enforcing against allocated wins because the research's paired
measurements show allocated tracks demand while reserved tracks fragmentation
history - and only the former is a property of the work being admitted. Keeping
reserved as a reported diagnostic preserves the operator's view of device
pressure without letting an unrelated allocation history make a well-sized job
fail.

## Consequences

Hook-backed corpora become fully indexed rather than truncated, and the failure
class that made a long-lived daemon degrade with uptime disappears, so restarts
stop being an implicit part of the operating procedure. Failure attribution also
becomes trustworthy: a memory failure will name work that genuinely demanded the
memory.

The costs are real. Bumping the identity version re-keys every document point,
so the first run after this lands re-indexes document corpora in full rather
than replaying incrementally - a one-time cost that must be expected rather than
diagnosed as a regression. A narrower alternative was available: omit the
discriminator when it is zero, leaving unsplit units on their existing ids and
confining churn to oversized documents. It is rejected because it makes identity
depend on the bound in force at write time, so the same unit's id would move
silently across a bound change, and because a uniform derivation is far easier
to reason about during replay than one with a conditional branch. Full churn
where partial churn was possible is accepted deliberately rather than by
omission.

The bound additionally participates in the resolved-policy fingerprint for the
document kind, so changing the character budget, the overlap, or the unit
maximum forces a document rebuild instead of stranding points derived under the
previous bound. Scoping it to the document kind keeps a document-side bound
change from churning the code index. Chunk counts for hook-backed corpora will
rise, with
proportionate storage and preallocation growth. Splitting a unit also risks
cutting a semantic boundary a hook deliberately chose, which is a genuine
quality trade against the truncation it replaces; the sub-chunks remain
attributed to the parent unit, which limits but does not eliminate that loss.

Demoting reserved from enforcement narrows protection against fragmentation-
driven exhaustion. The residual risk is a genuine device OOM that the allocated
ceiling admits, which surfaces as an allocator error on the existing OOM path
rather than as a pre-emptive refusal. Two follow-on questions are opened and not
settled here: whether the resident-model baseline should be excluded from the
indexing ceiling so the ceiling describes indexing headroom, and whether the
allocator fraction and the ceiling should be derived from one another rather
than configured independently.
