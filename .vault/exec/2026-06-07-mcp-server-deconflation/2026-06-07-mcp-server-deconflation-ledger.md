---
tags:
  - '#exec'
  - '#mcp-server-deconflation'
date: '2026-06-07'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:4dda32483cbe8be69ae710a26d9b095b7f71736a4dc2d9dc878898314d9b9485'
related:
  - "[[2026-06-07-mcp-server-deconflation-plan]]"
---

# `mcp-server-deconflation` ledger

## Changes

- `S01` `M` `pyproject.toml`
- `S02` `A` `src/vaultspec_rag/mcp/_mcp.py`
- `S03` `M` `src/vaultspec_rag/server/_routes.py`
- `S04` `M` `src/vaultspec_rag/mcp/_tools.py`
- `S05` `A` `src/vaultspec_rag/cli/_http_search.py`
- `S05` `D` `src/vaultspec_rag/cli/_mcp_search.py`
- `S06` `R` `src/vaultspec_rag/tests/test_mcp_server.py` -> `src/vaultspec_rag/tests/test_server.py`
- `S07` `M` `src/vaultspec_rag/tests/integration/test_service_jobs.py`
- `S09` `M` `src/vaultspec_rag/cli/_app.py`
- `S10` `M` `src/vaultspec_rag/cli/_service_info.py`
- `S11` `M` `.vaultspec/rules/rules/vaultspec-rag.builtin.md`

## Notes

- `S01` Historical operation attributed from Git commit e6720a35. Actual historical implementation scope; compound runtime or all-provider synchronization acceptance is not inferred.
- `S02` Historical operation attributed from Git commit f025186c. Actual historical implementation scope; compound runtime or all-provider synchronization acceptance is not inferred.
- `S03` Historical operation attributed from Git commit 6b866c6c. Actual historical implementation scope; compound runtime or all-provider synchronization acceptance is not inferred.
- `S04` Historical operation attributed from Git commit 4605407d. Actual historical implementation scope; compound runtime or all-provider synchronization acceptance is not inferred.
- `S05` Historical operation attributed from Git commit 36da5bb6. Actual historical implementation scope; compound runtime or all-provider synchronization acceptance is not inferred.
- `S06` Historical operation attributed from Git commit 12efe0d6. Actual historical implementation scope; compound runtime or all-provider synchronization acceptance is not inferred.
- `S07` Historical operation attributed from Git commit 12efe0d6. Actual historical implementation scope; compound runtime or all-provider synchronization acceptance is not inferred.
- `S09` Historical operation attributed from Git commit 377b7804. Actual historical implementation scope; compound runtime or all-provider synchronization acceptance is not inferred.
- `S10` Historical operation attributed from Git commit 7a4fa9f3. Actual historical implementation scope; compound runtime or all-provider synchronization acceptance is not inferred.
- `S11` Historical operation attributed from Git commit 7a4fa9f3. Actual historical implementation scope; compound runtime or all-provider synchronization acceptance is not inferred.
