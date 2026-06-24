---
tags:
  - '#plan'
  - '#serviceclient-admin-errors'
date: '2026-06-24'
modified: '2026-06-24'
tier: L1
related:
  - '[[2026-06-24-serviceclient-admin-errors-adr]]'
---


# `serviceclient-admin-errors` plan

- [x] `S01` - Replace the catch-all empty-dict swallow in the admin helper with the structured http_call_failed ok=False envelope (mirroring the search and reindex helpers), leaving the connection-refused→None and timeout→admin_timeout branches unchanged; `src/vaultspec_rag/serviceclient/_transport.py`.
- [x] `S02` - Add a no-mock regression test: drive an admin call against a real in-process route that raises a non-refused, non-timeout error (e.g. a malformed non-JSON response) and assert it returns the http_call_failed envelope, distinguishable from a real empty result and from the unreachable None sentinel; `src/vaultspec_rag/tests/test_http_admin_errors.py`.
## Description

Correct a single swallowing branch in the shared HTTP service-client transport so that an
unexpected admin failure becomes legible to both the CLI and the MCP agent. Today the admin
helper returns a bare empty dict on a non-refused, non-timeout exception, which the MCP
unwrap passes through unchanged - indistinguishable from a genuinely-empty result. The ADR
decided the fix: return the same structured `http_call_failed` `ok=False` envelope that the
search and reindex helpers already return for that exception class, reusing the existing
error code and leaving the two load-bearing axes (connection-refused returns the `None`
service-down sentinel; timeout returns the `admin_timeout` envelope) untouched. A
successful-but-null body keeps returning the empty dict, which becomes unambiguous once the
failure path no longer produces it. The work is two Steps - the one-branch change and a
no-mock regression test - grounded in the ADR and its research. This is the planning
artifact only; no code is written here, and the ADR awaits user sign-off before execution.

## Steps







## Parallelization

The two Steps carry a soft ordering: S01 changes the branch and S02 proves it. S02's test
is authored against the envelope contract S01 establishes, so writing S01 first is natural,
but the two could be developed together since the test encodes the intended behavior. There
is no other interdependency and no other in-flight work touches this branch.

## Verification

The plan is complete when both Steps are closed and all of the following hold:

- An admin call that hits a non-refused, non-timeout failure returns the
  `{"ok": False, "error": "http_call_failed", "message": ...}` envelope - never a bare empty
  dict - and the message names the underlying exception class and text.
- The connection-refused branch still returns the `None` service-down sentinel and the
  timeout branch still returns the `admin_timeout` envelope (no regression to the other two
  axes).
- The new regression test passes against a real in-process route with no mocks, stubs, or
  skips, and asserts the envelope is distinguishable from both an empty result and `None`.
- The existing transport and MCP test suites stay green; `ruff` and the type checker report
  zero violations.
