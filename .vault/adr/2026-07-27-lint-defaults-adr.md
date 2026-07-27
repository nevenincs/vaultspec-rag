---
tags:
  - '#adr'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-27-lint-defaults-research]]"
---

# `lint-defaults` adr: `ruff complexity defaults` | (**status:** `accepted`)

## Problem Statement

The project must replace temporary, raised complexity maxima with enforceable
upstream defaults while preserving behavior and the clarity of public transport
contracts. `2026-07-27-lint-defaults-research`.

## Considerations

- Internal operations already have behavior-preserving extraction patterns.
- Public CLI and MCP signatures may be contracts, not accidental parameter bundles.
- The completed migration must leave each default meaningful for future code.

## Considered options

- Keep the raised global maxima: rejected because new complexity remains invisible.
- Replace every signature with a parameter object: rejected because it can obscure
  public CLI and MCP contracts.
- Restore defaults, structurally refactor internals, and permit reviewed local
  argument-count exceptions only at true public transport boundaries: accepted.

## Constraints

- Preserve observable ordering, error behavior, serialization, and user-facing text.
- Classify each candidate from real callers before treating it as a transport boundary.
- Do not create forwarding signatures or test-only paths during migration.

## Implementation

Set all four configured maxima to Ruff's upstream defaults. Decompose internal
control flow into cohesive phases, predicates, and owned request or configuration
values. Apply a local `PLR0913` exception only after documenting why the function
directly represents a CLI or MCP contract; migrate every internal caller to the new
shape in the same change.

## Rationale

This option restores the value of the global guard while avoiding artificial request
objects where a transport's explicit filters are itself the product contract.
`2026-07-27-lint-defaults-research` and
`2026-07-27-lint-defaults-ruff-complexity-reference`.

## Consequences

New code is measured against the upstream defaults without a hidden baseline. The
migration is cross-cutting and requires behavior tests for every changed cluster.
Local exceptions require focused rationale and must not become a substitute for
internal design work.
