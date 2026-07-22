---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S23'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Run formatting lint typing unit integration client CLI and MCP checks under supervisor observation

## Scope

- `src/vaultspec_rag`

## Description

- Check formatting, lint, and strict typing for every changed production and regression module.
- Run adjacent search diagnostics, command-line interface, safety, Model Context Protocol, and stdio lifetime tests.
- Run canonical availability-classifier and strict consumer-envelope tests after concurrent campaign integration.

## Outcome

Ruff formatting and lint passed, and BasedPyright reported zero errors, warnings, or notes for
the changed modules. The adjacent suite passed eighty-six tests. The latest focused consumer and
classifier suite passed forty-eight tests, and the final no-substitute response-envelope suite
passed all sixteen tests.

## Notes

One early adjacent collection attempt encountered incomplete, unrelated indexer edits in the
shared worktree. The same planned suite passed after those commits completed. Snapshot Ruff
checks were clean; one snapshot-only BasedPyright invocation could not resolve the main virtual
environment from the exported directory, while the canonical main-tree invocation and formal
review typing gates were clean.
