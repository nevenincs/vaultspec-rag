---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-22'
step_id: 'S18'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Re-audit remediated MCP enrollment and run final release gates

## Scope

- `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and full repository gates`

## Description

- Re-audit all four original findings after the first remediation wave.
- Run full static, unit, real integration, lock, vault, build, and public-index wheel smoke gates.
- Probe legacy mode transitions for preview-versus-real provider parity.

## Outcome

The original provider-error and Core-floor findings closed, and fresh source add/remove
previews became accurate. Independent review found a new HIGH blocker: the preview
projection omitted the requested RAG mode, so a legacy dependency-to-tool transition
preview diverged from the real provider updates. It also found one LOW stale runtime
recovery message. Steps S19-S20 were added and release remained blocked.

## Notes

The first full unit gate passed 1412 tests and the real integration gate passed 43. The
repository-wide format check reported one untouched pre-existing `_preprocess.py` file
outside this feature diff; all feature files and commit hooks were formatted cleanly.
