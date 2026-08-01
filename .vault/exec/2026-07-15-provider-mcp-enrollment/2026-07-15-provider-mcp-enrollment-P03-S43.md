---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
body_hash: 'sha256:83be3fff42443a020e99c0a34c5fedcce3a3eaca6052b2f6a1a3f70c329b0cc6'
step_id: 'S43'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Repair fresh provider selection and transactional MCP lifecycle boundaries

## Scope

- `src/vaultspec_rag/commands/_install.py`
- `src/vaultspec_rag/commands/_uninstall.py`
- `preview topology and context handling`
- `and real lifecycle regressions`

## Description

- Default fresh MCP enrollment to Claude and Codex while preserving explicit host subsets and unrelated provider intent.
- Fail closed on unreadable provider intent before workspace bootstrap.
- Commit fresh provider persistence with native targets, Core ownership, locks, and parent topology under exact rollback.
- Preserve the complete MCP domain when uninstall explicitly skips MCP while still removing non-MCP resources.
- Isolate Core dry-run context for status, install reconciliation, and uninstall cleanup.
- Project only required lstat-aware MCP nodes for preview without traversing unrelated links or junctions.
- Preflight optional-dependency reversal and stop teardown on inspection errors, conflicts, or commit failures.
- Surface optional-dependency outcomes in uninstall JSON and human output.
- Add real-workspace lifecycle regressions for every repaired boundary.

## Outcome

- Passed 15 focused reviewer lifecycle regressions, including fresh dual-host enrollment, strict provider intent, exact rollback, prior and unset Core contexts, live and broken symlinks, and Windows junction topology.
- Passed the enlarged install, uninstall, CLI, mode, packaging, and native-host integration surface: 492 tests.
- Passed Ruff lint and changed-path formatting, ty, BasedPyright with zero findings, lock validation for 141 packages, all complexity thresholds, provider validation, and diff validation.
- Built the source distribution and wheel, then passed the isolated wheel smoke against published `vaultspec-core` 0.1.44 with both console entry points and native Claude and Codex enrollment.
- Completed an independent pre-close code review with no unresolved findings at any severity.

## Notes

- Corrected one stale fail-open uninstall expectation after the first lifecycle run; the replacement asserts the approved fail-closed contract and exact workspace preservation.
- No service implementation changed, so service-specific runtime checks were outside this step's surface.
- Left S44 and its historical full-suite inventory count untouched for the formal audit and release verification step.
