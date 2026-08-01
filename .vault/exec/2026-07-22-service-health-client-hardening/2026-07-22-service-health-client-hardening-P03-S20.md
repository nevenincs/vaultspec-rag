---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-23'
body_hash: 'sha256:c25537eb212faca9889ccfb4b06de3ff28a5acd922531620a0f27d5c0d37296b'
step_id: 'S20'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Assert every repointed call site preserves its sentinel semantics, so unreachability stays an ordinary branch and no exception escapes the service start or service stop verbs

## Scope

- `src/vaultspec_rag/tests/test_cli_service_status.py`

## Description

- Assert at the verb level that an unreachable service stays a branch rather than
  an escape, in `src/vaultspec_rag/tests/test_cli_service_status.py`.

## Outcome

The assertion sits at the two broker-facing verbs rather than at the function,
because the property that matters is not that the function returns a sentinel but
that the verb still emits exactly one structured outcome when it does.

The stop verb against a port with no listener emits one envelope, reports the
idempotent already-stopped status, and exits zero. The status verb against the
same port emits one envelope and no traceback. Both parse the output and assert
exactly one JSON object, which is what would catch a second envelope or a
crash-plus-envelope pair - the specific failure the one-envelope obligation
exists to prevent.

This is the Step that proves the authorizing decision's central claim, that
moving ownership cost zero contract change at the call sites. Had the owner
adopted the general entry point's exception contract, these two tests are where
it would have shown, as an escaping exception reaching a verb that must not
raise.

## Notes

Not executed by the author.

The envelope-counting helper parses only lines beginning with an object brace
rather than the whole output, so human-readable lines emitted alongside a JSON
envelope do not confuse the count. If a verb ever emitted a JSON array at top
level this helper would miss it; no verb does.

## Revision after independent review

This Step's guard asserted the property only for a dead port, which exercises the
unreachable sentinel branch. That is the half of the input space where an escape
is impossible. The case that can actually escape requires a LIVE responder
answering with something the callers cannot treat as a mapping, and no test bound
a port to produce it.

The review found the gap by reproducing the escape rather than by reading, and it
is a fair criticism of this Step specifically: the class is named for the property
it asserts, and it asserted it where it could not fail.

Coverage now includes a live responder returning valid non-object JSON, asserted
at both levels - the owner returns the sentinel, and the stop verb still emits
exactly one envelope with no attribute error in its output. The second assertion
is the one that would have caught the original defect.

This is also the first application of the guard-test convention this plan's work
produced: a negative assertion is not verified until it has been driven through
the case where it can fail.
