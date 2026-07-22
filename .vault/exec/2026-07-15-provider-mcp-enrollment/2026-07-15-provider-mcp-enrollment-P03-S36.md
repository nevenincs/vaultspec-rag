---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
step_id: 'S36'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Perform final fresh data-loss review and complete all release gates

## Scope

- `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact selected test inventory`

## Description

- Re-audit every prior MCP skip, placement, reporting, lock, source, and builtin rollback finding at commit `92ce320`.
- Run the complete high-risk install, placement, mode, torch-config, Qdrant, native-host, and packaging selection.
- Reproduce forced builtin rollback against operator-owned filesystem topology using a genuine later write blocker.
- Record the release-blocking symlink restoration defect and retain the merge and publication hold.

## Outcome

Failed. S35 restores ordinary pre-existing builtin files byte-for-byte, but its
bytes-or-absence snapshot does not preserve symlink identity. A failed forced repair
replaced an operator-owned rule symlink with a regular file. The reviewer classified
this as one unresolved HIGH with no CRITICAL findings. Release remains blocked pending
topology-aware remediation and another independent audit.

## Notes

- The complete high-risk selection passed 244 tests, including both installed host CLIs and isolated Qdrant behavior.
- Exact non-integration segmentation passed 1,632 of 1,820 selected tests before the accepted HIGH invalidated the target and terminated the service batch.
- The remaining 188 selected tests and the static, Vaultspec, diff, build, and wheel gates were stopped; none is waived.
- The real reproduction used a pre-existing rule symlink to an operator-owned in-workspace file and a non-empty directory at the later skill atomic-temporary path.
- Merge and publication remain held pending remediation and a fresh complete review.
