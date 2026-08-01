---
tags:
  - '#adr'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:5f5b0ae42d11262b61cf75121f5d25dd797e9b3a10def8b3b93aa46bf55161ec'
related:
  - "[[2026-07-27-maintainability-remediation-research]]"
  - "[[2026-07-27-maintainability-remediation-radon-module-ownership-reference]]"
  - "[[2026-06-01-module-split-adr]]"
---

# `maintainability-remediation` adr: direct-owner decomposition | (**status:** `accepted`)

## Problem Statement

The reported Radon floor modules need structural remediation without hiding the
metric or retaining duplicate compatibility surfaces. The problem shape and
candidate seams are established in
`2026-07-27-maintainability-remediation-research` and
`2026-07-27-maintainability-remediation-radon-module-ownership-reference`.

## Considerations

- `2026-06-01-module-split-adr` requires direct ownership rather than
  forwarding facades.
- `2026-07-27-maintainability-remediation-research` rules out suppression and
  artificial integration-test substitutes.
- `2026-07-27-maintainability-remediation-radon-module-ownership-reference`
  identifies seams and protects active shared-worktree edits.

## Considered options

- **Direct-owner decomposition (chosen).** Move cohesive behavior to concrete
  modules, migrate all callers, and delete each former monolith.
- **Metric filtering or exemption.** Rejected because it conceals the same
  maintenance burden.
- **Compatibility package facades.** Rejected because they preserve a second,
  non-owning import surface.
- **Test-only emulation.** Rejected because it would weaken real service proof.

## Constraints

- Preserve runtime behavior and existing public service contracts.
- Retain one owner for each state transition, persistence boundary, and test
  harness behavior.
- Carry direct importer migration and real-behavior verification with each
  extraction.
- Reconcile shared-worktree hunks before modifying files with active work.

## Implementation

Split the production candidates by the concrete ownership map and retain one
small aggregate only where it is the state owner. Split integration modules by
independently collected scenario domain, using helpers only for common real
process, HTTP, CLI, persistence, or watcher setup. Verify every replacement
module through the health report and affected behavior, lint, format, and type
gates before advancing.

## Rationale

Direct-owner decomposition is the only option compatible with the established
canonical-code boundary while changing the actual source of the floor scores.
The seam evidence in
`2026-07-27-maintainability-remediation-radon-module-ownership-reference`
keeps the work behavior-preserving rather than a line-count exercise.

## Consequences

- **Gains.** Concrete ownership, smaller review units, and meaningful
  maintainability scores.
- **Costs.** Import migration and test collection need careful, repeated
  verification.
- **Risks.** A missed importer, duplicate helper, or facade would invalidate
  the ownership decision and must be corrected in the same change.
