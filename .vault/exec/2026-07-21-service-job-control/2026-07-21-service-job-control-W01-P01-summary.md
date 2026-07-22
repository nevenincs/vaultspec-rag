---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` `W01.P01` summary

The cooperative run-control contract and its bounded service configuration are complete and
verified against imported production behavior.

- Created: `src/vaultspec_rag/job_control.py`
- Modified: `src/vaultspec_rag/config.py`
- Created: `src/vaultspec_rag/tests/test_job_control_unit.py`

## Description

`RunControlToken` now provides thread-safe pause, resume, cancellation, checkpoints, and
protected spans with explicit delivered-signal semantics. `NullRunControl` keeps existing
callers compatible. The service exposes validated bounds for nonterminal admission and
cooperative shutdown timing, including both environment and public override resolution.

Focused real-thread tests cover protected work, reversible pending pauses, absorbing
cancellation, signal delivery, exception preservation, and invalid configuration values.
Ruff, ty, BasedPyright, and the phase unit suite pass.
