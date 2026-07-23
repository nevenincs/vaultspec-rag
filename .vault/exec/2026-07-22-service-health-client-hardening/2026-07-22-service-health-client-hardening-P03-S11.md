---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-23'
step_id: 'S11'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Repoint the serving-pid and token resolution in service stop to the transport's health function

## Scope

- `src/vaultspec_rag/cli/_service_stop.py`

## Description

- Replace the command-line probe call with the transport's health function,
  imported from the established transport shim.

## Outcome

The stop verb resolves which process is serving a port from the health response, and now reads that response from the transport. The identity check downstream is unchanged and remains the deferred weakness recorded elsewhere; nothing here repairs it.

The call site is otherwise untouched: same argument, same returned shape, same
sentinel on unreachability, same bounded wait. This is the zero-contract-change
claim the authorizing decision rests on, and it holds here because the owner was
implemented to preserve the probe's contract exactly rather than to adopt the
general entry point's exception contract.

## Notes

Not executed by the author. Verification of this Step is inseparable from its
siblings: the sentinel-semantics assertion covers the repointed sites as a group
rather than one at a time, which is why that assertion is its own Step.
