---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:d7af1878d9b12333db34065007c4394bfeeda06323f376a947e91bec9b06e44d'
step_id: 'S03'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Assert a redirect answered on a token-carrying request path is refused and the bearer credential never reaches the redirect target

## Scope

- `src/vaultspec_rag/tests/test_http_admin_errors.py`

## Description

- Write a status file carrying a known bearer token so the call under test
  genuinely authenticates, in
  `src/vaultspec_rag/tests/test_http_admin_errors.py`.
- Assert the redirecting server observed the bearer credential on the original
  request.
- Assert the sink server recorded no request, so the credential never reached
  the redirect target.
- Assert the sink's response body was not adopted as a service result.

## Outcome

The credential-bearing path is covered, and the test demonstrates the specific
consequence that made the policy transport-wide rather than health-only: the
standard library copies request headers onto a redirect target without comparing
hosts, so a followed redirect on this path would carry the bearer token off-host.

Three assertions, each carrying a distinct load. The sink recording nothing is
the substantive claim - the credential did not leak. The sink's body not
appearing in the result closes the weaker failure where a redirect is followed
and its response is mistaken for the service's own. The third assertion exists to
stop the test passing vacuously and is the one most easily omitted: it confirms
the redirecting server actually saw the bearer credential on the original
request. Without it, a regression that stopped sending the token at all would
turn this test green while proving nothing, because a credential that is never
sent also never leaks.

The token is supplied the way the transport really obtains one, by writing a
status file into the isolated status directory the module's fixture already
provides, rather than by reaching into the transport to inject a value. The call
under test is an ordinary admin call that resolves to a plain request, so the
credential travels the same path a production call would.

## Notes

Not executed by the author; verification is handed to a harness operator. As
with the sibling coverage Step, passing is expected rather than observed.

One property was confirmed by reading rather than by running, and a verifier
should treat it as the most likely point of failure: the admin tool name chosen
for the test must resolve to a route that actually issues a request, or the
guard assertion fails and the test reports a vacuous pass rather than hiding
one. The mapping was read directly and resolves to a plain root route with no
required arguments, which is why that name was chosen over one needing a
project root.

No mock, stub, patch, fake, skip, or expected-failure marker was used. Nothing
here touches the deferred identity weakness in the service stop path, and the
credential-leak property proven here is not a property of that check; the two
should not be conflated in any summary of this work.
