---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
body_hash: 'sha256:04d5b1ce5a8bf874c579c9d2f8906437c25a85ca7a8f15cc1e35bca4e976f96a'
step_id: 'S49'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Reject full-lifecycle target overlap and adopt the corrective Core floor

## Scope

- `src/vaultspec_rag/commands/_mcp_topology.py`
- `install and uninstall lifecycle tests`
- `pyproject.toml`
- `and uv.lock`

## Description

- Reject required link targets that alias any complete lifecycle-owned file, lock,
  container, or content root while preserving exact-path topology validation.
- Derive the protected provider surface from Core and cover builtin content,
  provider trees and hooks, root control files, `.vaultspec/rules`, `uv.lock`,
  `.venv`, and data directories.
- Exercise preview, apply, and uninstall behavior through real install lifecycle
  regressions.
- Raise the exact Core dependency floor and public-PyPI lock to 0.1.45, then
  update the package acceptance assertions to match.
- Verify the focused topology, install-mode, package-metadata, and installed CLI
  surfaces against the published Core 0.1.45 distribution.

## Outcome

- Landed the overlap protection and real lifecycle regressions in commit
  `e7b4edc`.
- Resolved the project environment and lock from public PyPI with
  `vaultspec-core` 0.1.45.
- Passed the complete install/uninstall integration surface (183 tests), the
  adjacent mode, placement, and CLI surface (323 tests), the focused topology
  surface (13 tests), package metadata (5 tests), focused mode selection (5
  tests), and the installed-package smoke checks.
- Completed formal review with no findings after correcting the initial
  root-output omission.

## Notes

- Deferred the dependency-floor change until Core 0.1.45 was available from
  public PyPI.
- Recollected 2,267 total tests for S50. The exact campaign ledger is 1,830
  selected and 437 excluded, including 183 native install cases (six more than
  S48). The generic `not integration` marker view is not that ledger because it
  deselects the complete integration-marked install module.
- Left S50 as the release gate; this step did not open a pull request or perform
  a release.
