---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-23'
body_hash: 'sha256:c2649bb8fa8fbd7a25d9ec6f1ace2ffb22ed73d6e32e4479b4143710b9b320e7'
step_id: 'S15'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Repoint the running-state summary read in status rendering to the transport's health function

## Scope

- `src/vaultspec_rag/cli/_status_render.py`

## Description

- Replace the command-line probe call with the transport's health function,
  imported from the established transport shim.

## Outcome

Branches on the reported status to choose between running, stopped, and unreachable.

The call site is otherwise untouched: same argument, same returned shape, same
sentinel on unreachability, same bounded wait. This is the zero-contract-change
claim the authorizing decision rests on, and it holds here because the owner was
implemented to preserve the probe's contract exactly rather than to adopt the
general entry point's exception contract.

## Notes

Not executed by the author. Verification of this Step is inseparable from its
siblings: the sentinel-semantics assertion covers the repointed sites as a group
rather than one at a time, which is why that assertion is its own Step.
