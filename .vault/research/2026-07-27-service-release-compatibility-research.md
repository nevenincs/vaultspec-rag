---
tags:
  - '#research'
  - '#service-release-compatibility'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-25-service-release-compatibility-adr]]"
  - "[[2026-07-25-service-release-compatibility-plan]]"
  - "[[2026-07-25-service-release-compatibility-reference]]"
---

# `service-release-compatibility` research: `Compatibility lifecycle evidence`

## Findings

### Retained preamble

Release compatibility is implemented as a shared verdict over service identity, while one plan step remains formally open despite its fixture change already appearing in the cited test; this records evidence and leaves completion status to the plan owner.

### Compatibility is a shared data-plane classification

`serviceclient/_compat.py:35-232` resolves match, mismatch, and unreported package versions with distinct structured errors. Health, readiness, discovery, sidecar, and parent snapshot publication carry the release across the documented identity surfaces; `server/_lifespan.py:1224-1230`, `_readiness.py:173`, `server/_lifecycle.py:188-207`, and `serviceclient/_discovery.py:425-438`.

### Reachable incompatible daemons are refused at operational boundaries

MCP entry, search, refresh and clean indexing, and service attachment use the shared verdict rather than a separate local policy; `mcp/_tools.py:170-194`, `cli/_search.py:1141-1157`, `cli/_index.py:637-647`, and `cli/_service_start.py:467-487`. The compatibility suite covers matching, mismatched, unreadable, publication, refusal, discovery-pair, and doctor behavior; `tests/test_service_version_compatibility.py:108-505`.

### The plan state needs reconciliation, not a new decision

Plan step `P03.S18` remains open, while `tests/test_search_service_first.py:207-237` already writes the local release so the test reaches and asserts `port_unreachable`. This supports the recorded fixture correction but does not establish formal plan completion; `2026-07-25-service-release-compatibility-plan` remains the authority for that status.

## Sources

- `2026-07-25-service-release-compatibility-adr`
- `2026-07-25-service-release-compatibility-plan`
- `2026-07-25-service-release-compatibility-reference`
- `src/vaultspec_rag/serviceclient/_compat.py:35-232`
- `src/vaultspec_rag/serviceclient/_discovery.py:425-438`
- `src/vaultspec_rag/server/_lifespan.py:1224-1230`
- `src/vaultspec_rag/server/_lifecycle.py:188-207`
- `src/vaultspec_rag/mcp/_tools.py:170-194`
- `src/vaultspec_rag/cli/_search.py:1141-1157`
- `src/vaultspec_rag/tests/test_service_version_compatibility.py:108-505`
- `src/vaultspec_rag/tests/test_search_service_first.py:207-237`
