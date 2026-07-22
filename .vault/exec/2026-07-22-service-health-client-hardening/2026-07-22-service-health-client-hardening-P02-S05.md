---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S05'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Replace the general entry point's absent default timeout with a bounded default, leaving callers that need a different bound to pass one explicitly

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`

## Description

- Resolve an omitted or absent timeout through the administrative timeout policy
  instead of leaving the call unbounded, in
  `src/vaultspec_rag/serviceclient/_transport.py:362`.
- Compute the deadline from the resolved bound so the internal remaining-time
  helper always has one.
- Report the resolved bound rather than the caller's raw argument when a
  deadline is exhausted.

## Outcome

A call that names no timeout is now bounded. The change is one line of
resolution plus the consequences of it: the deadline is always a real number,
the remaining-time helper no longer has a branch for the unbounded case and
returns a plain value, and the deadline-exhausted message quotes the bound that
was actually enforced rather than the argument the caller did not supply.

The default was chosen against the two the module already has rather than
picked. The transport carries an administrative default of thirty seconds and a
search default of three hundred, and the general entry point is
administrative-shaped work: the calls that reach it without a bound are status
reads, job listings, cleans, and job creation, none of which does heavy compute
on the daemon side. Three hundred seconds is calibrated for search, where a cold
model load and a rerank genuinely take minutes; adopting it here would leave a
wedged administrative call hanging for five minutes before anyone learned
anything, which is close enough to unbounded to defeat the purpose. Thirty
seconds is long enough that a busy daemon queueing a job answers well inside it,
and short enough that a wedged peer is reported rather than waited on.

Search is unaffected, which is worth stating because it is the one path where a
shorter bound would be a regression: it passes its own resolved value explicitly,
and the policy helper returns any valid positive bound unchanged rather than
capping it. The operator override applies only when no bound was supplied, so it
cannot shorten search either.

Resolution goes through the module's existing administrative timeout policy
rather than through a bare constant. This was a deliberate choice with three
consequences worth stating. The operator override that already governs the admin
helpers now governs this path too, which is consistent rather than surprising.
The behaviour becomes testable in reasonable time, because a test can lower the
bound through that same override instead of waiting out a thirty-second default.
And a caller passing a non-finite or non-positive value now resolves to the
default instead of constructing an immediately-expired deadline, which is a small
robustness gain that came free with the policy helper.

There is deliberately no way to request no bound at all. The authorizing decision
allows a caller needing a different bound to pass one explicitly, and every
caller that needs a longer wait already does - search passes its own resolved
timeout. An unbounded network call has no defensible use on this transport: it
can wait forever on a wedged peer, and because these requests carry the service
bearer credential, an unbounded wait is also an unbounded window in which that
credential is in flight. That reasoning is recorded in the function's own
documentation so a future caller meets it before trying to reintroduce the
option.

The one previously unbounded production caller - the reindex helper - is bounded
by inheritance without needing an exemption, for the reason established in the
sibling enumeration Step.

## Notes

Not executed by the author; verification is handed to a harness operator.

One consequence deserves a verifier's attention because it is behavioural rather
than cosmetic. Before this Step, a caller passing a non-positive or non-finite
timeout would have produced a deadline that was already expired; now it resolves
to the default. No caller was found doing that, so the change is expected to be
inert, but it is a real difference in behaviour rather than a pure refactor and
should not be described as one.

The remaining-time helper's return type narrowed from an optional value to a
plain one. That is a type-level change to a module-private helper with no callers
outside the enclosing function, but a type checker rather than a test is what
would catch a mistake there, so the gate matters more than usual for this Step.

Nothing here touches the deferred identity weakness in the service stop path, and
no summary of this work should suggest otherwise.
