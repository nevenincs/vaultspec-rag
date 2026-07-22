---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S07'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Add a dedicated health function to the transport that returns the parsed body, returns a structured error carrying the HTTP code when the service answers unhealthily, returns a sentinel when unreachable, never raises, and defaults to a bounded timeout matching the command-line probe

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Add the health function to `src/vaultspec_rag/serviceclient/_transport.py:225`
  with a bounded default matching the probe it replaces.
- Export it from the module and through the command-line transport shim.

## Outcome

The health call has one owner. It returns the parsed body on success, a
structured error carrying the HTTP code when the service answers unhealthily,
and a sentinel when it cannot be reached; it never raises.

One design point is worth recording because a reader could reasonably have
expected the opposite. The function is implemented directly over the
redirect-refusing opener rather than over the module's general entry point. That
was deliberate: the general path discards the HTTP status code and returns only
the body, whereas several call sites embed the health response into operator
output and one branch distinguishes a sick daemon from an absent one. Routing
through the general path would have silently dropped the code at those sites. The
authorizing decision anticipated this by specifying a structured error carrying
the HTTP code, so this is conformance rather than divergence - but it means the
owner is a move of the existing logic rather than a rewrite on a different
contract.

The health route is ungated, so no credential is sent and no token-recovery retry
is needed. The bound defaults to five seconds, matching the probe exactly, so
every repointed site waits precisely as long as it did before; the constant
carries a comment saying so, because a future reader would otherwise have no way
to know the number was inherited rather than chosen.

## Notes

Not executed by the author.

The function reuses the module's response-size ceiling and its redirect-refusing
opener rather than reimplementing either. That is the point of the ownership
move: there is now one place where a health request is constructed, and anything
hardened there is hardened for every caller.
