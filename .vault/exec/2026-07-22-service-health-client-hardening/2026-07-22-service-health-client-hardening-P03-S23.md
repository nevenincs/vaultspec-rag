---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-23'
step_id: 'S23'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Repoint the discovery-reconciliation probe injection to the transport's health function, a consumer the plan's call-site enumeration missed because the probe is passed as a value rather than invoked

## Scope

- `src/vaultspec_rag/cli/_service_reconcile.py`

## Description

- Repoint the discovery-reconciliation probe injection to the transport's health
  function in `src/vaultspec_rag/cli/_service_reconcile.py`.

## Outcome

This consumer passes the probe as a value into a reconciliation routine rather
than calling it, which is why the plan's original enumeration missed it: the
enumeration searched for call sites, and this is a reference. The routine types
the parameter as a callable taking a port and returning an optional mapping,
exactly the owner's signature, so the repointing is an import change like the
others.

The general lesson outlasts the fix: an audit of who uses a symbol must search
references, not invocations. A function passed as an argument, stored in a
registry, or bound as a default is a consumer no call-site search will find, and
the more decoupled the design the more of these exist.

A follow-on was deliberately not taken. The routine receiving this injection lives
in the service-client layer and already types the probe contract there, so once
the transport owns the function the injection is arguably redundant - the routine
could call the owner directly rather than being handed it. That is a design
change, it touches a file another effort currently holds, and folding it into a
repointing Step is how scope creep enters a security plan. It is recorded as an
observation for later, not as work performed.

## Notes

Not executed by the author.
