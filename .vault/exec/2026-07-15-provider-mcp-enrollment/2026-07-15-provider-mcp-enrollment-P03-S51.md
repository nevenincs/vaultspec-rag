---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
body_hash: 'sha256:07db0d674951889d90c2c18e0b1e963ab8dbade90276d8252aa921ae5e39da95'
step_id: 'S51'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Accumulate requested project diagnostics and align filesystem failure tests with Core 0.1.45

## Scope

- `src/vaultspec_rag/commands/_install.py and real install regressions`

## Description

- Preserve the outer required-topology refusal while accumulating MCP-extra and
  requested torch-config inspection failures for an unreadable project surface.
- Centralise the established project-inspection error mapping so the inner and
  outer install paths emit the same structured report fields.
- Replace retired predictable-temp blockers with real Core 0.1.45 filesystem
  conditions: required-node directories for preflight safety and a non-required
  builtin destination directory for late atomic-replacement rollback.
- Exercise exact inventory, lock, symlink, absent/existing builtin, force,
  upgrade, JSON exit, and requested diagnostic behavior without test doubles.

## Outcome

- Corrected the S50 directory-shaped `pyproject.toml` report truncation while
  preserving fail-before-mutation behavior and the generic topology diagnostic.
- Passed invalid-UTF8, directory, and broken-relative-link project cases, the
  independent unsafe-topology CLI case, all 59 Windows-collected torch-config install
  tests, all 14 Core-floor compatibility
  regressions, and all 183 real install integration tests under Core 0.1.45.
- Passed Ruff, touched-file formatting, Ty, BasedPyright with zero findings,
  all complexity thresholds, and diff hygiene.
- Completed independent re-review with PASS and no actionable findings after
  resolving both HIGH diagnostic-boundary findings.
- Left a new S52 step open for the independent 1,830-test release audit; this
  corrective step does not claim release readiness.

## Notes

- The first expanded integration run exposed 14 stale tests that still expected
  Core's retired PID-derived temporary name. A watcher-based replacement was
  rejected after only five of 14 cases passed because it was timing-sensitive;
  no such helper remains in the committed surface.
- Independent review found and blocked an unrestricted diagnostic read that
  could hang on a FIFO and skip a broken symlink. The final implementation uses
  non-following node classification, and real broken-link plus capability-gated
  FIFO regressions cover the corrected boundary.
- Re-review caught a false component error for supported live relative project
  links. Descriptor-based decoding and an in-project live-link matrix resolved
  the finding without weakening generic topology refusal.
- A repository-wide Ruff format check also reports unrelated pre-existing drift
  in `src/vaultspec_rag/cli/_preprocess.py`; the three files changed by this
  step are formatted.
