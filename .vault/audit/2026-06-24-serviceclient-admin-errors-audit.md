---
tags:
  - '#audit'
  - '#serviceclient-admin-errors'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - "[[2026-06-24-serviceclient-admin-errors-plan]]"
---



# `serviceclient-admin-errors` audit: `admin-error envelope contract review (PASS)`

## Scope

Reviewed commit `d87d190` (GitHub #199) against its ADR and plan: the single-branch swap of the `_try_http_admin` catch-all from a bare `{}` to the structured `http_call_failed` envelope, the preserved refused/timeout axes, MCP `_unwrap` compatibility, and the no-mock regression test. Read-only review by a `vaultspec-code-reviewer` persona; the orchestrator independently re-ran ruff/ty/pytest (3 passed).

## Findings

**Verdict: PASS - no Critical, High, or Medium findings. The change realises every ADR decision (D1 envelope, D2 shared `http_call_failed` code with a per-surface message prefix, D3 null-body `{}` retained and now unambiguous, D4 real-route regression) and both plan steps. The connection-refused->None and timeout->admin_timeout axes are byte-for-byte unchanged and correctly ordered before the catch-all; the envelope passes through MCP `_unwrap` verbatim (no `_unwrap` change needed) and stays distinguishable from a real empty `{}` and from `None`; the debug log is retained so the failure is both logged and legible (no-swallow intent met). All six reviewer findings are confirmations; only one is an actionable test-hygiene nit.**

## free-port-reuse-race | low | negligible TOCTOU window in the test's _free_port helper

`_free_port()` binds port 0, reads the assigned port, closes the socket, and returns the number - a bind/close/reuse window where another process could grab the port before the test connects, turning the expected connection-refused into something else. On loopback the window is sub-millisecond and flakiness risk is negligible. If fully deterministic refusal is wanted later, keep a bound-but-not-accepting socket or connect to a deliberately-closed second port. Not blocking.

## Recommendations

Merge. The implementation is minimal, correct, and fully grounded; the lone LOW is optional test-hygiene. No revision required.

## Codification candidates

None this review. The ADR's `serviceclient-helpers-envelope-not-swallow` is a candidate only, promoted after the constraint holds across a full execution cycle, per the codify discipline.
