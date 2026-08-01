---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
body_hash: 'sha256:716db37df04480450a0e4c0c474901646c116128a328561e84e9884ed0cba6ee'
step_id: 'S58'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Assign stable unique pytest parameter IDs

## Scope

- `src/vaultspec_rag/tests/test_config.py`
- `src/vaultspec_rag/tests/test_torch_config.py`
- `Windows and POSIX collection ledgers`
- `and S58 formal review`

## Description

- Assign semantic, stable IDs to four existing parameterized test groups.
- Recollect full and `not integration` inventories on Windows and POSIX.
- Reconcile the promoted, junction-only, and FIFO-only sets by exact node ID.
- Run the affected runtime and static checks.
- Submit the correction and evidence for formal technical re-review.

## Outcome

- Preserved every existing parameter value, assertion, marker, and test case while
  eliminating all six duplicate displayed pytest node IDs.
- Passed all 135 affected tests.
- Recollected 2,271 Windows items with 2,271 unique displayed node IDs and 1,828
  marker-selected items with 1,828 unique displayed node IDs.
- Recollected 2,259 POSIX items with 2,259 unique displayed node IDs and 1,829
  marker-selected items with 1,829 unique displayed node IDs.
- Proved zero duplicate groups in every full and selected inventory.
- Reconciled the six promoted items, 13 Windows-only junction items, and one POSIX-only
  FIFO item without overlap.
- Passed affected Ruff lint and formatting checks and Ty.
- Passed formal technical re-review with no remaining finding.

## Notes

The initial formal review correctly rejected occurrence-index disambiguation as an
unacceptable substitute for unique displayed identities. This step fixes the identity
defect only. It does not claim release readiness and does not authorize a pull request,
merge, approval, publication, or release.
