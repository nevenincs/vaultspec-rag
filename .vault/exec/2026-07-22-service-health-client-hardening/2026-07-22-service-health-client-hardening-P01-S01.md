---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S01'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Build the transport's requests through a redirect-refusing opener so no request path follows a 3xx

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Add a redirect-refusing handler and a module-level opener built from it at
  `src/vaultspec_rag/serviceclient/_transport.py:76` and `:101`.
- Route the health-token fetch through that opener
  (`_transport.py:234`).
- Route the general request sender through that opener
  (`_transport.py:287`).

## Outcome

The transport no longer follows a redirect on any path. Both sites that
previously called the bare standard-library opener now open through one that
declines the redirect, so the policy is transport-wide rather than confined to
the path whose consequence was traced first.

Refusal is expressed by declining rather than by raising a bespoke error. The
handler returns nothing, which leaves the response to fall through to the
default error handling and surface as an ordinary HTTP error. Each caller's
existing behaviour then applies unchanged: the health-token fetch already
returns an empty string on any failure, and the general sender already parses an
error response into its structured envelope. No caller needed a new branch, and
no new exception type crosses a module boundary.

Scope note on the duplication this could have created. The command-line probe
already carries a handler of the same shape, and adding a second one in the
transport is the parallel-implementation pattern this feature exists to remove.
Two things make the duplication transient rather than entrenched. The canonical
handler now lives in the service-client layer, which is the lower layer and the
surviving owner - the dependency direction runs from the command line into the
service client and never the reverse, so this is the only placement from which
one handler can eventually serve both. And the command-line probe's separate
implementation is already scheduled for removal by a later Step in this plan,
which deletes its copy rather than leaving two. Moving the command-line copy now
would have edited a file outside this Step's declared scope to save one
intermediate state.

## Notes

Verification was not performed by the author and is handed to a harness
operator. Nothing in this Step was executed: the refusal behaviour is reasoned
from the standard library's handler contract and from the command-line probe,
which has used the identical construction in this repository for some time.

One consequence was traced statically rather than observed, and a verifier
should confirm it rather than assume it. A declined redirect surfaces as a 3xx
HTTP error, and the general call path treats a non-401 status by parsing the
body it received. A redirect response carries no body, so the parse fails and
the path returns its structured error envelope. That is the intended outcome,
but it is an inference about two interacting behaviours rather than something
this Step demonstrated.

No test was modified by this Step, no suppression was added, and no behaviour
was weakened. The deferred identity weakness in the service stop path is
untouched: narrowing the conditions under which a foreign responder can be
reached is not a repair of the check that fails to identify one, and nothing in
this Step should be described as repairing it.
