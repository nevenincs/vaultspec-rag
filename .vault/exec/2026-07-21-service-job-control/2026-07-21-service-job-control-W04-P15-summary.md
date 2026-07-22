---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` `W04.P15` summary

Verified legacy reindex compatibility and preserved the accepted MCP
incremental-refresh-only administration boundary.

- Modified: `src/vaultspec_rag/server/_watcher.py`
- Modified: `src/vaultspec_rag/tests/integration/test_service_job_control.py`
- Created: S32 execution and audit records.

## Description

The live MCP registry remains limited to search, read-only retrieval, and two
non-destructive incremental refresh tools. MCP vault refresh resolves the real
service, traverses the compatibility route, and creates the expected canonical
job. No pause, resume, stop, retry, delete, administration, or clean-rebuild
capability is exposed. The watcher opt-out now prevents deferred warming as
well as actual watcher publication.
