---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S02'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Assert a redirect answered on the health path is refused rather than followed

## Scope

- `src/vaultspec_rag/tests/test_http_admin_errors.py`

## Description

- Add a real loopback server that answers every request with a redirect to a
  second server, and a sink server that records what reaches it, in
  `src/vaultspec_rag/tests/test_http_admin_errors.py`.
- Assert the health-token fetch against the redirecting server obtains no token
  and leaves the sink untouched.

## Outcome

The health path is now covered by a test that serves a genuine redirect rather
than simulating one. Both servers are real and listen on loopback, in keeping
with the module's existing no-mocks stance; the redirect is a real 302 with a
real location header naming the second server.

The assertion has two halves, and the second is what gives it force. The first
is that no token is obtained, which shows the redirect was not followed to a
successful read. The second is that the sink recorded no request at all, which
distinguishes "followed the redirect and failed to parse the result" from "never
made the second request". Only the latter is refusal, and only the sink's
emptiness can tell them apart.

The sink deliberately answers with a body containing a plausible-looking service
token. If a regression ever causes the redirect to be followed, the test fails on
the value returned as well as on the recorded request, so the failure names the
real problem rather than surfacing as an unexplained empty result.

## Notes

Not executed by the author; verification is handed to a harness operator. The
test is written against the transport's real wire path and the module's existing
server-fixture helper, but it has not been run, so its passing is expected rather
than observed.

No mock, stub, patch, fake, skip, or expected-failure marker was used. The two
handlers are real request handlers on real sockets, and the shared
server-starting helper already present in the module is reused rather than
duplicated.
