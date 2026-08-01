---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:752a395de9ecf6e5d91082ea42488cd4cfe32b202417ffda5eb9f46829db9807'
step_id: 'S06'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Assert a call that omits the timeout argument is bounded rather than able to wait indefinitely

## Scope

- `src/vaultspec_rag/tests/test_http_admin_errors.py`

## Description

- Add a real loopback server that answers only after a delay far longer than any
  bound under test, in `src/vaultspec_rag/tests/test_http_admin_errors.py`.
- Assert a call that names no timeout gives up rather than waiting for that
  server, and that it gives up well inside the server's delay.

## Outcome

The bound is proven against a server that genuinely does not answer in time,
rather than by inspecting the resolved value. The distinction matters: asserting
that the resolution helper returns a number would restate the implementation and
pass even if the resolved bound were never applied to the socket. Watching a real
call abandon a real slow server is what demonstrates the bound reaches the wire.

Two assertions carry the claim. The call must raise a timeout, which shows it
gave up rather than succeeded or failed some other way. And the elapsed time must
be well below the server's delay, which shows the caller's bound ended the call
rather than the server eventually answering. Without the second, a test could
pass on a server that happened to fail for an unrelated reason.

The bound is lowered for the test through the operator override that the resolved
policy already honours, which is why this test completes in under a second
instead of waiting out the default. That is a direct benefit of resolving through
the policy helper rather than a bare constant, as the sibling Step records.

## Notes

Not executed by the author; verification is handed to a harness operator.

This test is timing-sensitive in a way the module's other tests are not, and a
verifier should know where its tolerances sit. The server delays several seconds,
the bound under test is a fraction of a second, and the assertion allows a
generous margin below the server's delay. The margin is wide enough that ordinary
scheduling noise on a loaded host should not reach it, but a host suspended
mid-test could. If this test ever fails intermittently while the bounded-ness it
asserts is otherwise intact, the tolerance is the thing to examine - though it
should be widened only with evidence, since a genuinely unbounded call would
also present as a long elapsed time.

The slow handler suppresses the connection errors it will provoke when the client
abandons the request mid-response. That is not a swallowed failure in the code
under test; it is the server side of a deliberate client-side abort, and the same
suppression pattern is already used by the module's existing deadline handler.

No mock, stub, patch, fake, skip, or expected-failure marker was used.
