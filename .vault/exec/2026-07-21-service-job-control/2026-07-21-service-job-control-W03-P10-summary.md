---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:d4d7e0d8b745bf4da279534be8569f57b722b0d3914631c5ed961ca465f7ebb4'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` `W03.P10` summary

The daemon now restores durable manager intent on startup and drains every
known watcher and manager execution owner before closing storage, with truthful
clean versus unclean lifecycle reporting.

- Modified: `src/vaultspec_rag/job_control.py`
- Modified: `src/vaultspec_rag/job_manager.py`
- Modified: `src/vaultspec_rag/jobs.py`
- Modified: `src/vaultspec_rag/service.py`
- Modified: `src/vaultspec_rag/server/_lifespan.py`
- Modified: `src/vaultspec_rag/tests/test_jobs_unit.py`
- Created: `src/vaultspec_rag/job_dispatch.py`
- Created: `.vault/audit/2026-07-22-service-job-control-s20-lifecycle-audit.md`
- Created: `.vault/exec/2026-07-21-service-job-control/2026-07-21-service-job-control-W03-P10-S20.md`

## Description

S20 integrates the process-wide `JobManager` with the service lifespan. Fresh
startup restores persisted state after model readiness, binds every queued and
paused indexing job to the exact package registry, and dispatches only durable
queued intent whose desired state is running. Production attempt runners now
live in the focused `job_dispatch.py` module instead of duplicated closures in
the `jobs.py` facade.

Shutdown uses a distinct cooperative signal, gates dispatch and watcher intake
before other cleanup, and joins manager and watcher ownership concurrently
within the configured deadline. Only proven release permits registry, Qdrant,
and machine-lock teardown. Persistence durability is tracked separately so a
write failure remains an unclean diagnostic without retaining already released
resources. Retained restore errors preserve their original cause and flow
through bounded cleanup instead of poisoning in-process reuse.

The same cleared `ServiceRegistry` and stopped manager reopen after a clean
embedded lifecycle. Real behavior probes and focused suites verify preserved
queued and paused intent, interrupted running attempts after release, gated
late dispatch, timeout survivor truth, application-failure precedence,
registry reuse, watcher-stop fail-closed behavior, and retained-state rebinding.
Independent review resolved three High findings and approved the phase at
Critical 0, High 0, Medium 0, Low 0.
