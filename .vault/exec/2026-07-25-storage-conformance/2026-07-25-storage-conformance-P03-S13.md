---
tags:
  - '#exec'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S13'
related:
  - "[[2026-07-25-storage-conformance-plan]]"
---

# Pair the conformance degradation with its rebuild remediation command in the existing degraded-family registry

## Scope

- `src/vaultspec_rag/cli/_status_labels.py`

## Description

## Outcome

A `conformance` family paired with `vaultspec-rag index --rebuild --type all`,
and the structured `nonconforming` signal added to the health payload so the
remediation is derived from the signal rather than parsed out of the prose.

Two things were corrected here after mutation runs contradicted the first
version, and both are recorded in the tests rather than quietly fixed:

Asserting that a conformance finding merely *appears* is inert. When a reason
pairs with no signal the renderer's unclaimed sweep appends the family's finding
anyway, so the family is present even when the wrong command is attached to the
conformance cause. The tests now assert which command lands on which cause.

The family ordering is defensive, not load-bearing. Reasons resolve in the order
the health author emits them, and the models reason is emitted first, so it
claims the `model` stem before the conformance reason is reached - no reachable
input distinguishes the two orderings. The comment at the registry now says
exactly that instead of claiming a protection no test can demonstrate. Ordering
is kept because it costs nothing and holds if either reason is reworded.

## Notes
