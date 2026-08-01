---
tags:
  - '#exec'
  - '#search-index-availability'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:a5ab5ce82a0524be1d443af4636da4600339789a3c2e638f33dd3fc96274a4fd'
step_id: 'S21'
related:
  - "[[2026-07-21-search-index-availability-plan]]"
---

# Map structured daemon search failures to recoverable MCP tool errors without synthesizing results using Terra xhigh

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

- Inspect structured daemon search envelopes before output-schema validation.
- Raise one actionable runtime error for every envelope with `ok: false`.
- Include the daemon error code, message, and remediation steps in tool-error text.
- Preserve successful current and legacy search envelopes and service-down handling.

## Outcome

Applied one import-light failure guard to both MCP search tools. Focused Ruff formatting and
lint checks passed, basedpyright reported no errors, and independent review approved the
consumer-boundary behavior.

## Notes

No local fallback, result synthesis, or transport behavior was added.
