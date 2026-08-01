---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-23'
body_hash: 'sha256:c18de6d314c8aacb967c7c31a944d847d471c59880925b507c9af9b5de5afe84'
step_id: 'S18'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Repoint the integration readiness-wait helper to the transport's health function

## Scope

- `src/vaultspec_rag/tests/integration/_helpers.py`

## Description

- Replace the command-line probe call with the transport's health function,
  imported from the established transport shim.

## Outcome

The helper waits for a daemon to become ready. It imports the transport function directly rather than through the command-line package, which is no longer where the function lives.

The call site is otherwise untouched: same argument, same returned shape, same
sentinel on unreachability, same bounded wait. This is the zero-contract-change
claim the authorizing decision rests on, and it holds here because the owner was
implemented to preserve the probe's contract exactly rather than to adopt the
general entry point's exception contract.

## Notes

Not executed by the author. Verification of this Step is inseparable from its
siblings: the sentinel-semantics assertion covers the repointed sites as a group
rather than one at a time, which is why that assertion is its own Step.
