---
tags:
  - '#exec'
  - '#serviceclient-admin-errors'
date: '2026-06-24'
modified: '2026-06-24'
body_hash: 'sha256:436cc3c6ff6261e91797ab72c9fa1698630ad88eee2b41a5e152bf450e584289'
step_id: 'S02'
related:
  - "[[2026-06-24-serviceclient-admin-errors-plan]]"
---

# Add a no-mock regression test: drive an admin call against a real in-process route that raises a non-refused, non-timeout error (e.g. a malformed non-JSON response) and assert it returns the http_call_failed envelope, distinguishable from a real empty result and from the unreachable None sentinel

## Scope

- `src/vaultspec_rag/tests/test_http_admin_errors.py`

## Description

- Added a no-mock regression test that stands up a real in-process `ThreadingHTTPServer` and
  drives the admin helper over the genuine `urllib` wire path (no transport internals patched).
- Asserted three axes: a malformed (non-JSON) 200 response returns the `http_call_failed`
  envelope and is distinguishable from both `{}` and `None`; a valid empty `{}` body stays
  `{}` (a legitimate empty result); a closed port returns `None` (the service-down sentinel).
- Isolated the status dir to a temp dir so no ambient discovery-file token couples into the
  test.

## Outcome

Three tests pass. The regression that an unexpected admin failure is swallowed into an empty
dict is now guarded, and the envelope-vs-empty-vs-None distinction is proven. `ruff` and the
type checker pass; the `log_message` override uses an LSP-compatible signature.

## Notes

The in-process HTTP server is a real socket server, not a mock; the no-mock mandate is
satisfied by exercising the actual wire path rather than stubbing the transport.
