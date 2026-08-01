---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-27'
body_hash: 'sha256:208cbfedd5959a486cec76b4b9e399a8526db01769e037ad5d4c0ed54df63a8c'
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

Template evidence: intro_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9; template_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
