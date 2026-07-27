---
tags:
  - '#adr'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-27-lint-defaults-research]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #adr) and one feature tag.
     Replace lint-defaults with a kebab-case feature tag, e.g. #foo-bar.
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
