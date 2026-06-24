---
tags:
  - '#exec'
  - '#serviceclient-admin-errors'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S01'
related:
  - "[[2026-06-24-serviceclient-admin-errors-plan]]"
---




# Replace the catch-all empty-dict swallow in the admin helper with the structured http_call_failed ok=False envelope (mirroring the search and reindex helpers), leaving the connection-refused→None and timeout→admin_timeout branches unchanged

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Replaced the catch-all `except` branch's bare `return {}` in the admin helper with the
  structured `{"ok": False, "error": "http_call_failed", "message": ...}` envelope, carrying
  the exception class and text, mirroring the search and reindex helpers verbatim in shape.
- Retained the existing `logger.debug(..., exc_info=True)` so the failure is both logged and
  legible in the returned value.
- Left the connection-refused branch (`-> None`) and the timeout branch
  (`-> admin_timeout` envelope) untouched.

## Outcome

The admin path now surfaces an unexpected (non-refused, non-timeout) failure as the same
legible envelope the rest of the transport uses; on MCP it passes through the unwrap helper
unchanged, so an agent sees `ok=False` instead of a false-empty result. `ruff` and the type
checker pass on the changed module.

## Notes

No behavioural change to the refused/timeout axes. No existing test depended on the prior
`{}` swallow.
