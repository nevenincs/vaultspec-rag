---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-23'
step_id: 'S12'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Repoint the identity token comparison in the process helper to the transport's health function

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Description

- Replace the command-line probe call with the transport's health function,
  imported from the established transport shim.

## Outcome

This was the one site resolving the probe as a package attribute at call time rather than through a bound import, which is why five test interception points depended on it. It now imports the transport function directly, and a sibling Step repoints those interceptions to match.

The call site is otherwise untouched: same argument, same returned shape, same
sentinel on unreachability, same bounded wait. This is the zero-contract-change
claim the authorizing decision rests on, and it holds here because the owner was
implemented to preserve the probe's contract exactly rather than to adopt the
general entry point's exception contract.

## Notes

Not executed by the author. Verification of this Step is inseparable from its
siblings: the sentinel-semantics assertion covers the repointed sites as a group
rather than one at a time, which is why that assertion is its own Step.
