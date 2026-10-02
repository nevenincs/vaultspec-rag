---
tags:
  - '#exec'
  - '#service-graph'
date: '2026-04-02'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:ddbb5fd8f36c6bf47243d718cfe717341dedbb32f38900a06bf65ad1eaaa6abf'
related:
  - "[[2026-04-02-service-graph-phase1-plan]]"
---

# `service-graph` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/api.py`
- `S01` `M` `src/vaultspec_rag/search.py`
- `S02` `M` `src/vaultspec_rag/api.py`
- `S02` `M` `src/vaultspec_rag/search.py`
- `S03` `A` `src/vaultspec_rag/tests/test_graph_cache.py`
- `S04` `A` `src/vaultspec_rag/service.py`
- `S06` `A` `src/vaultspec_rag/tests/test_service_registry.py`
- `S07` `M` `src/vaultspec_rag/mcp_server.py`
- `S08` `M` `src/vaultspec_rag/mcp_server.py`
- `S09` `M` `src/vaultspec_rag/mcp_server.py`
- `S10` `M` `src/vaultspec_rag/cli.py`
- `S11` `M` `src/vaultspec_rag/cli.py`
- `S12` `M` `src/vaultspec_rag/cli.py`
- `S05` `M` `src/vaultspec_rag/api.py`
- `S05` `A` `src/vaultspec_rag/registry.py`

## Notes

- `S01` Historical operation attributed from Git commit 22db751f9ade8b71468d6959c53b4b0fdfb33501. Graph ownership/injection actually modified historical monolith; no current split path operation inferred. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S02` Historical operation attributed from Git commit 22db751f9ade8b71468d6959c53b4b0fdfb33501. Graph ownership/injection actually modified historical monolith; no current split path operation inferred. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S03` Historical operation attributed from Git commit 22db751f9ade8b71468d6959c53b4b0fdfb33501. Authored concurrency regression; execution metrics only retained exec, not Git. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S04` Historical operation attributed from Git commit ad151b40d9cb7d1c4faccbe52816553906381f7f. Created registry and slots. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S06` Historical operation attributed from Git commit ad151b40d9cb7d1c4faccbe52816553906381f7f. Authored multi-project identity coverage; no new run inferred. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S07` Historical operation attributed from Git commit d3d09054d6baeeddd391bab4d7c2faa5d42a8a50. Eager lifespan/health/project-root live together in historical server monolith. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S08` Historical operation attributed from Git commit d3d09054d6baeeddd391bab4d7c2faa5d42a8a50. Eager lifespan/health/project-root live together in historical server monolith. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S09` Historical operation attributed from Git commit d3d09054d6baeeddd391bab4d7c2faa5d42a8a50. Eager lifespan/health/project-root live together in historical server monolith. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S10` Historical operation attributed from Git commit a052433565b5fc130bf5863d45c9b5a7ccb80d8c. Daemon helpers/start-stop-status/warmup in one historical CLI; S12 real lifecycle verification remains separate. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S11` Historical operation attributed from Git commit a052433565b5fc130bf5863d45c9b5a7ccb80d8c. Daemon helpers/start-stop-status/warmup in one historical CLI; S12 real lifecycle verification remains separate. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S12` Historical operation attributed from Git commit a052433565b5fc130bf5863d45c9b5a7ccb80d8c. Daemon helpers/start-stop-status/warmup in one historical CLI; S12 real lifecycle verification remains separate. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S05` Historical operation attributed from Git commit 0eaf67ff17f563ca4c0cc28739821405af51061a. Later Apr12 completion collapses Engine facade to registry; not Apr2 phase2 execution. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
