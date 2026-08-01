---
tags:
  - '#exec'
  - '#tool-env-gpu-continuity'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:00b167ed6b49c9ebdbb352c8b5233cb7ddf96e4ec38f8071a4617eaa5a8e5d3d'
step_id: 'S13'
related:
  - "[[2026-07-14-tool-env-gpu-continuity-plan]]"
---

# Run the full unit and integration suites with the machine service stopped and isolated status and storage dirs, fixing any regressions the new surfaces introduce

## Scope

- `src/vaultspec_rag/tests`

## Description

- Ran the full unit suite in an isolated worktree with a GPU-verified
  interpreter (torch 2.13.0+cu130, RTX 4080 SUPER); status and storage dirs
  isolated per the managed-singleton rule.
- Repaired a large pre-existing red on the integration baseline that was
  unrelated to this feature: a sibling change had made the preprocess rule
  schema require `target` and `extractor_version` and bumped the config
  schema version without migrating the test suite, leaving 88 unit failures.
  Migrated every rule construction and config fixture to the current schema
  and reconciled the version-mismatch tests to the deliberated hard-error
  contract.
- Closed the one real surface gap this feature introduced: the uvx-ephemeral
  warning was dropped on the `server start` already-running attach path, the
  outcome a long-lived daemon returns almost every time. Added a caller-side
  warning emitted in human text and inside the JSON success envelope's
  `warnings` field, verified through a real uvx invocation in both modes.
- Confirmed each new surface has direct unit coverage: the runtime-env
  classifier truth table and single-source remediation strings, the warming
  status rendering and its distinct exit code, the jobs `--json` signpost,
  and the two ephemeral-env warnings.

## Outcome

The full unit suite is green: 2077 passed, 0 failed. Every surface this
feature added is exercised by real-behaviour unit tests with no mocks,
skips, or patches. Ruff and BasedPyright are clean across the changed files.
The GPU-only contract is verified in production: the installed tool's uv
receipt carries the canonical `vaultspec-rag[mcp]` form with the pinned
cu130 torch wheel, and its interpreter reports a CUDA build.

## Notes

- The on-box manual persona pass originally scoped as S14 was removed from
  the plan as an inappropriate automated-development step; verification rests
  on the automated suite and the real-uvx warning reproduction above.
- The full integration suite was not re-run in this session because it
  requires stopping the resident machine-singleton daemon, which is currently
  serving a different active project on this box. The surfaces this feature
  adds are CLI rendering, status-sidecar fields, and warning strings with no
  integration-only code path, and all are unit-covered.
- The repair and this feature's fix are committed on branch
  `integrate/closeout` (uvx warning, preprocess schema migration), unmerged
  pending the owner of `main`.
