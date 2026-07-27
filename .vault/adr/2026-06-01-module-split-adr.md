---
tags:
  - '#adr'
  - '#module-split'
date: '2026-06-01'
modified: '2026-07-27'
related:
  - "[[2026-06-01-module-split-research]]"
  - "[[2026-06-01-module-split-audit]]"
  - '[[2026-07-27-module-split-production-length-gate-research]]'
---

# `module-split` adr: direct-owner decomposition of overlength modules | (**status:** `accepted`)

## Problem Statement

Overlength production and test modules obstruct review and local reasoning. The
original facade approach preserved legacy import paths at the cost of leaving
each former module boundary as a second, non-owning surface. This ADR settles
the decomposition strategy for the current overlength set, including
`store.py`, without keeping compatibility facades alive.

## Considerations

- **One behavior has one importable home.** Every importer moves to the
  concrete module that owns the behavior. A package root never re-exports a
  moved name merely to preserve an old import path.
- **Tests follow production ownership.** A test that needs an implementation
  detail imports that concrete owner; test-only compatibility surfaces are not
  retained.
- **State retains an explicit owner.** A package root may own initialization
  state only when the state itself is the behavior, never as a forwarding
  facade.
- **Responsibility is the seam.** Extraction boundaries follow independently
  testable responsibilities, with direct importer migration in the same step.

## Constraints

- **Behavior must not change.** Each extraction carries its real behavior tests
  and the affected importers, then passes the relevant suite, format, lint,
  and type checks.
- **The production contracts remain stable.** Direct importer migration may
  change source import paths but must not add a parallel API or alter runtime
  behavior.
- **Existing lifecycle and storage ownership decisions remain binding.** A
  split cannot copy lifecycle, locking, or service-domain logic across owners.
- **This is an in-repo structural refactor.** It adds no dependency and does
  not widen external protocols.

## Implementation

For every overlength module, identify cohesive concrete owners, move each
owner to its own module, and migrate every production and test import directly
to that owner. Delete the former monolith only after no importer resolves
through it. Test files split into independently collected modules by behavior
domain; shared test helpers live in one concrete helper module rather than a
compatibility collection shim. Each extraction is separately verified before
the next dependent extraction begins.

## Rationale

`2026-07-27-module-split-production-length-gate-research` establishes that a
facade conflicts with the canonical-code rule, and the focused ownership audit
identifies workable responsibility seams for the current candidates. Direct
migration removes the former boundary instead of making it permanent, which is
the only option consistent with one behavior and one implementation. Including
`store.py` applies the same maintainability requirement to the longest cohesive
class rather than preserving an exemption.

## Consequences

- **Gains.** Smaller, navigable files with a single owner per behavior and
  imports that reveal that ownership.
- **Honest difficulties.** This is a broad mechanical refactor; missed direct
  imports, cyclic dependencies, and moved test helpers are the main risks.
- **Pitfalls.** Extraction must not turn a concrete state owner into a facade,
  duplicate service/storage behavior, or retain a symbol solely for tests.

## Codification candidates

- **Rule slug:** `module-splits-migrate-to-direct-owners`.
  **Rule:** A module split migrates every caller to the concrete owner in the
  same change. No forwarding module, package-root re-export, compatibility
  alias, or test-only surface survives the split.

## Considered options

Evidence gap: the retained document body has no separately labelled Considered options section.
