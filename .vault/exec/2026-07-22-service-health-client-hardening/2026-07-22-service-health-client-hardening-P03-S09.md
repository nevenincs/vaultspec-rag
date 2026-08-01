---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-23'
body_hash: 'sha256:a368dff6268dfbec9afee6e5a6f0d7446be3001b58b05aed056cc94355294d68'
step_id: 'S09'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Repoint the already-running status read in service start to the transport's health function

## Scope

- `src/vaultspec_rag/cli/_service_start.py`

## Description

- Replace the command-line probe call with the transport's health function,
  imported from the established transport shim.

## Outcome

The site reports to an operator that a service is already up. It now calls the transport's health function; the value it branches on, the field it reads, and the five-second wait are unchanged.

The call site is otherwise untouched: same argument, same returned shape, same
sentinel on unreachability, same bounded wait. This is the zero-contract-change
claim the authorizing decision rests on, and it holds here because the owner was
implemented to preserve the probe's contract exactly rather than to adopt the
general entry point's exception contract.

## Notes

Not executed by the author. Verification of this Step is inseparable from its
siblings: the sentinel-semantics assertion covers the repointed sites as a group
rather than one at a time, which is why that assertion is its own Step.
