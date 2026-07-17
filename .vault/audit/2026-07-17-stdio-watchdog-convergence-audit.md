---
tags:
  - '#audit'
  - '#stdio-watchdog-convergence'
date: '2026-07-17'
modified: '2026-07-17'
related: []
---

# `stdio-watchdog-convergence` audit: `review of the issue-229/232 convergence`

## Scope

Review of the pipe-creator anchor convergence and the functional assertion
floor against the ADR, both GitHub issues, and the reference
`vaultspec_core/mcp_server/watchdog.py`. Verdict: PASS - no critical or
high findings; behavioral convergence with core assessed as exact (anchor
composition, grace semantics, dedupe, handle cleanup, and the stderr event
shape all semantically identical; only sanctioned per-package naming
differs).

## Findings

### undrained-stderr-pipe | low | In-process e2e spawns capture stderr without a drain thread

A shim writing beyond the pipe buffer before the harness reads stderr
would wedge; kept low because the stdio branch deliberately configures no
stderr logging handler (sparse WARNING+ output only) and the harness
times out with a captured tail rather than hanging. ACCEPTED as optional
hardening; noted for any future chatty-shim change.

### resolver-log-level | low | Resolver's unexpected-error log was ERROR where core uses DEBUG

Cosmetic divergence from the reference on a path that only fires on
genuinely unexpected errors. RESOLVED: aligned to debug post-review.

### exceptional-path-handle-leak | low | Mid-build snapshot failure leaks already-opened handles

Shared structurally with the reference implementation; triggers only on
unexpected Toolhelp32 failure and the process exits through install's
fail-open path. ACCEPTED, matching core.

## Recommendations

Merge; the floor and the convergence goal are met. Ship in the next
release so uvx shims gain the exact-client anchor.
