---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S21'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Correct the module docstring's false claim that every call funnels through the general entry point, and document the two failure idioms the module now exposes

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Correct the transport module docstring's false universal claim and document the
  two failure contracts the module now exposes.

## Outcome

The docstring said every call funnels through the general entry point. That was
false before this plan - nine command-line call sites bypassed it entirely - and
would have remained imprecise afterwards, because the health owner deliberately
does not route through it.

It now names both entry points and states their contracts explicitly: the general
path raises on connection-level failure, the health path never raises and returns
a sentinel instead. It also records why the health path is the exception, which is
that its callers sit in verbs bound to emit exactly one structured outcome.

The redirect policy is stated once, at module level, with its reason: loopback
only, no service route emits a 3xx, and the standard library would otherwise copy
the bearer credential onto whatever host a redirect named.

## Notes

Not executed by the author; a docstring correction has no behavioural test.

The two-contract split is a real cost of the ownership decision, and the
authorizing record acknowledges it. Stating it at module level is the mitigation:
a reader who assumes one idiom covers the module now meets the correction before
reaching either function.
