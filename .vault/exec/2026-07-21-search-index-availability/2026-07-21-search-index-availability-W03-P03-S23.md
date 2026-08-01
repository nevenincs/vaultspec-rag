---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:a789063d21b7a77061830d1d20d7edf3cafac3588372e9a8e8d413c3008759e6'
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

Ruff formatting and lint passed. BasedPyright, invoked with the explicit main interpreter for
the immutable snapshot, reported zero errors, warnings, or notes. The final focused classifier
and HTTP contract suites passed 33 tests, and the final adjacent search, client, command-line,
Model Context Protocol, and stdio suite passed 116 tests.

## Notes

Earlier intermediate gates passed 86 adjacent, 48 focused consumer/classifier, and 16 strict
response-envelope tests. One snapshot-only BasedPyright invocation initially could not resolve
the shared virtual environment; supplying its explicit Python interpreter produced the final
zero-error, zero-warning, zero-note result.
