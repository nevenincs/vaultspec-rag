---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S32'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Verify reindex compatibility and the unchanged MCP incremental-refresh-only administration boundary using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_service_job_control.py`

## Description

- Introspect the live MCP tool registry and assert its exact search, retrieval,
  and incremental-refresh surface.
- Exclude job-control and administration tools from the MCP boundary.
- Assert non-destructive, idempotent refresh annotations and absence of a
  clean-rebuild input.
- Drive MCP vault refresh through real service discovery and the loopback
  `/reindex` compatibility route.
- Prevent disabled automatic watchers from warming registry slots.

## Outcome

The compatibility adapter maps MCP refresh to a canonical incremental vault
job with MCP initiator attribution and stable identity. The MCP registry
remains exactly five tools and exposes no job-control capability. Disabled
watchers no longer schedule unnecessary deferred project warming. The focused
scenario passes; Ruff, Ruff format, and BasedPyright pass. Independent review
passed with no critical, high, or medium findings.

## Notes

The first passing run exposed a deferred watcher warm despite
`watch_enabled=false`. The entry-point guard was corrected, and the focused
run passed without the model-open error. No test double or destructive Git
operation was used.
