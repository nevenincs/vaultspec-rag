---
tags:
  - '#exec'
  - '#mcp-launch-hygiene'
date: '2026-07-17'
modified: '2026-07-17'
body_hash: 'sha256:bb1609616bca5865409ee571f133971429d5849a97b1c0dff65aea872804800c'
step_id: 'S03'
related:
  - "[[2026-07-17-mcp-launch-hygiene-plan]]"
---

# Pin the contract with tests: placement matrix for the extra step and the stale-exe-seed refresh on install --upgrade

## Scope

- `src/vaultspec_rag/tests/test_install_mcp_extra.py`

## Description

- Pin the placement matrix, the tool-mode skip, `_detect_rag_placement`
  variants (runtime, dev group, custom group, longer-name non-match, absent,
  malformed toml), and the stale-exe-seed [UPDATE]-on-force refresh plus the
  no-force skip.

## Outcome

26 tests pass in test_install_mcp_extra.py; basedpyright clean.

## Notes

None.
