---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S38'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Perform final topology-aware release review and complete every gate

## Scope

- `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact 1820-test inventory`

## Description

- Re-audit the S37 topology-aware rollback implementation at commit `d8de256`.
- Reproduce rollback behavior when the deterministic scratch pathname is already an
  operator-owned symlink.
- Stop the exact segmented aggregate and all remaining release gates after confirming
  unrelated operator-data loss.
- Record one release-blocking HIGH finding and retain the merge and publication hold.

## Outcome

Failed. S37 restores the primary builtin destination with its original node topology,
but regular-file restoration writes through a predictable unsnapshotted scratch path.
A pre-existing symlink at that scratch path is followed, its referenced file is
overwritten with rollback bytes, and the link itself is then unlinked. The reviewer
classified this as one unresolved HIGH with no CRITICAL findings. Release remains
blocked pending scratch-node-safe restoration and another independent audit.

## Notes

- The reproduction used a real temporary workspace, an unrelated operator file, and a
  genuine relative symlink at the exact rollback scratch pathname; no mock, fake,
  patch, monkeypatch, skip, or xfail was used.
- The first exact non-integration aggregate batch was terminated before a summary, so
  S38 credits no test count.
- All remaining high-risk, static, Vaultspec, diff, build, wheel, and host-recognition
  gates were stopped after the target was invalidated; none is waived.
