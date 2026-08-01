---
tags:
  - '#exec'
  - '#service-health-client-hardening'
date: '2026-07-22'
modified: '2026-07-23'
body_hash: 'sha256:afaa0800004cf6bc1cb9aa17e414fcce6f003cacdbf1f2b782ab99288958922c'
step_id: 'S10'
related:
  - "[[2026-07-22-service-health-client-hardening-plan]]"
---

# Repoint the readiness-and-token read in service start, which persists the token into the status file, to the transport's health function

## Scope

- `src/vaultspec_rag/cli/_service_start.py`

## Description

- Replace the command-line probe call with the transport's health function,
  imported from the established transport shim.

## Outcome

This site also persists the token it reads into the status file so delegated authentication works before the first heartbeat lands. That behaviour is untouched: only the function supplying the response changed.

The call site is otherwise untouched: same argument, same returned shape, same
sentinel on unreachability, same bounded wait. This is the zero-contract-change
claim the authorizing decision rests on, and it holds here because the owner was
implemented to preserve the probe's contract exactly rather than to adopt the
general entry point's exception contract.

## Notes

Not executed by the author. Verification of this Step is inseparable from its
siblings: the sentinel-semantics assertion covers the repointed sites as a group
rather than one at a time, which is why that assertion is its own Step.
