---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-23'
body_hash: 'sha256:08a7ac0123a49a080f89bc0eb4b782e3526866a50761235b26e91441ece45fcb'
step_id: 'S08'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Assert the health function returns a sentinel on unreachability, a structured error on an unhealthy answer, and the parsed body on success, and that it raises in none of those cases

## Scope

- `src/vaultspec_rag/tests/test_http_admin_errors.py`

## Description

- Add contract coverage for the three outcomes and the never-raises property in
  `src/vaultspec_rag/tests/test_http_admin_errors.py`.

## Outcome

Four tests. A live service returns its parsed body; an unhealthy service returns
a structured error carrying its HTTP code; an unreachable port returns the
sentinel; and a fourth drives all three conditions asserting that none raises.

The unhealthy case asserts two things rather than one: that the result is not the
unreachable sentinel, and that it carries the code. The distinction is the reason
that branch exists - a caller must be able to tell a sick daemon from an absent
one - and asserting only the code would pass even if unreachability had been
folded into the same shape.

The never-raises case is separate rather than implied by the other three because
it is a contract rather than an observation. Its callers sit in lifecycle verbs
bound to emit exactly one structured outcome per exit path, so an escaping
exception would become a second one. A property that load-bearing deserves an
assertion that fails for the right reason.

## Notes

Not executed by the author. No mock, stub, patch, fake, skip, or expected-failure
marker was used: the healthy and unhealthy cases are real loopback servers, and
the unreachable case uses the module's existing bound-but-never-listening port
fixture rather than a closed port, which would leave a reuse window.
