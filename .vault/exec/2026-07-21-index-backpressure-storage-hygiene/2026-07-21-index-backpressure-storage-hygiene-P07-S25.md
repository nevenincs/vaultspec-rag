---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-27'
body_hash: 'sha256:6983b55a0dcbf26c8680ffa76005e3b2b7b4a66200d98036c50046f7c4359943'
step_id: 'S25'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add tests for the isolation guard, the lifecycle tripwire, and interrupted-job visibility across a simulated daemon restart

## Scope

- `src/vaultspec_rag/tests/`

## Description

Tests for all three defect-3 guards: interrupted restore lifecycle, the
terminate tripwire (refusal and isolated pass), and the suite isolation
guard asserting the machine-global dirs are never the session's resolved
targets.

## Outcome

Committed with the P07 test commit; 34 jobs-unit tests green.

## Notes

Template evidence: intro_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9; template_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
