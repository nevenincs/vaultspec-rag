---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
body_hash: 'sha256:080efbfb1282d569d3a742dddc96c88017c13ff0eadc4024ee5ae69947610112'
step_id: 'S08'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Reverse only owned MCP extra placement during unenrollment and uninstall

## Scope

- `src/vaultspec_rag/commands/_uninstall.py and src/vaultspec_rag/tests/test_install_mcp_extra.py`

## Description

- Resolve the installed RAG mode before removing enrollment sources.
- Reverse only the dependency requirement edit recorded by RAG's MCP-extra ownership marker.
- Preserve byte-for-byte project state during uninstall previews and after exact reversal.
- Surface drift and resolution failures as non-destructive uninstall warnings.

## Outcome

Uninstall now mirrors MCP-extra enrollment without claiming unowned project state. A
default-safe preview leaves the managed requirement and ownership marker untouched;
forced uninstall restores the exact original requirement and removes the marker. The
shared reconciler continues to refuse drifted or unowned dependency surfaces.

## Notes

Ruff, BasedPyright, Ty, and 17 focused real-filesystem tests pass against the in-flight
Core provider-native MCP implementation. Provider-target cleanup remains isolated in
Step S04 and will use Core's selective `names={"vaultspec-rag"}` contract.
