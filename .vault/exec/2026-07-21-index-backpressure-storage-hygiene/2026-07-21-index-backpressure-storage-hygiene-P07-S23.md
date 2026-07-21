---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S23'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add a lifecycle tripwire refusing stop/terminate of the machine-global service when running under pytest without explicitly isolated status dir

## Scope

- `src/vaultspec_rag/cli/_service_lifecycle.py`

## Description

`_refuse_terminate_from_unisolated_test` guards the single terminate
choke point (`_terminate_and_confirm`): under pytest with neither
machine-dir env var isolated, it raises with remediation instead of
stopping the operator's daemon - failing a test loudly beats an outage.

## Outcome

Committed as the structural-isolation commit; refusal and isolated-pass
cases covered by `TestMachineServiceTestGuard`.

## Notes
