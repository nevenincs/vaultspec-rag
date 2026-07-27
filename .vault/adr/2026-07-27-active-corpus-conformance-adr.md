---
tags:
  - "#adr"
  - "#active-corpus-conformance"
date: '2026-07-27'
related:
  - "[[2026-07-27-active-corpus-conformance-research]]"
superseded_by: '2026-07-27-body-schema-provenance-adr'
modified: '2026-07-27'
---
# `active-corpus-conformance` adr: `Archive non-conforming active vault documents` | (**status:** `superseded`)

## Problem Statement

The user requires a zero-warning active vault, while `2026-07-27-active-corpus-conformance-research` establishes that the live corpus contains historical and current documents missing required authored sections. The missing evidence cannot be truthfully reconstructed from the affected files.

## Considerations

- The active corpus must be checker-clean.
- Historical evidence must remain recoverable.
- Feature-wide archive cannot select the exact failing paths.

## Considered options

- **Preflighted manifest archive (chosen).** Archive exactly the paths reported by body-sections through an owning CLI command. This preserves bytes and makes the live corpus conforming.
- **Bulk-fill missing sections.** Rejected because it fabricates provenance.
- **Delete the documents.** Rejected because it loses historical evidence.
- **Relax the body-sections validator.** Rejected because it hides non-conformance.

## Constraints

The command accepts only explicit repository-relative live document paths, rejects escapes, symlinks, duplicates, and destination collisions, supports dry-run and JSON, and preserves all bytes. The archive operation must be reversible through the existing archive layout.

## Implementation

Add a `vault archive documents --manifest` command with preflight and atomic rollback. Generate the manifest from the live body-sections diagnostics, archive exactly those documents, regenerate indexes, and re-run every vault check.

## Rationale

An explicit archive cutover is the only option that satisfies the zero-warning requirement without manufacturing or destroying historical content.

## Consequences

The active vault will exclude incomplete current and historical lifecycle records. Their evidence remains in `.vault/_archive` and must be unarchived and completed before returning to active governance.
