---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
body_hash: 'sha256:e67df804da0687a3e53c2faa2bc28a221ec4f63f5528725f95277fc5893821de'
step_id: 'S47'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Make required MCP nodes topology-safe across preview and apply

## Scope

- `preview projection`
- `provider and workspace intent writes`
- `native targets`
- `ownership`
- `and real relative-link regressions`

## Description

- Enumerate every required native, ownership, provider-intent, workspace-intent,
  package-placement, canonical MCP source, and advisory lock node before mutation.
- Preserve safe one-hop in-project relative links through preview, apply, delta,
  rollback, uninstall, and publication to their captured regular-file targets.
- Reject external, absolute, broken, chained, overlapping, aliased, hard-linked,
  directory-linked, and junction-backed required topology before lifecycle mutation.
- Derive exact rollback ownership from an isolated lifecycle replay, rebase Core's
  absolute ownership paths to the real workspace, and retain final, materialized,
  and intermediate absent CAS tokens for linked nodes.
- Sequence every fallible MCP reconciliation before unrelated provider-resource,
  torch, or provisioning mutation.
- Exercise Windows junctions, preview/apply parity, no-delta preservation, exact
  failure rollback, concurrent operator updates, immediate abort, and partial
  materialization failure with real filesystem behavior.

## Outcome

- Completed. Required MCP topology now remains exact across preview and apply, safe
  relative links publish through their captured targets, and unsafe topology fails
  closed before lifecycle mutation.
- Exact rollback restores transaction-owned regular, linked, target, placement,
  ownership, provider, workspace, source, and lock state while preserving concurrent
  operator changes.
- Final acceptance passed 177 integration cases and 62 focused placement, mode, and
  packaging cases. Ruff, Ty, BasedPyright, complexity, module-length reporting, lock,
  Vaultspec, source-distribution, wheel, and isolated published-Core enrollment gates
  passed.

## Notes

- Independent review finished PASS with no CRITICAL, HIGH, MEDIUM, or LOW findings.
- Review findings covering dynamic-source preview parity, link-target races,
  hard-link aliasing, identity ambiguity, absolute ownership paths, sequencing, and
  partial materialization were reproduced and resolved before closure.
- No mocks, fakes, stubs, patches, monkeypatches, skips, or xfails were introduced.
