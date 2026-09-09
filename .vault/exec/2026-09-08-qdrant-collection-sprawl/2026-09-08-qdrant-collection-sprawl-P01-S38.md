---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:004d10ee458b7a2f78e7127c3e43f2a9bdb867b6ae90de4fd79bdf22ca33e8ef'
step_id: 'S38'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Derive the service-start readiness deadline from the resolved qdrant patience window and its ceiling so the command stops abandoning a start that will succeed

## Scope

- `src/vaultspec_rag/cli/_service_start.py`

## Changes

- `M` `src/vaultspec_rag/cli/_service_start.py`
- `M` `src/vaultspec_rag/qdrant_runtime/_supervise.py`
- `M` `src/vaultspec_rag/tests/test_qdrant_ready_timeout.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest test_qdrant_ready_timeout.py test_cli_server.py test_cli_server_start.py test_cli_start_outcomes.py test_cli_no_mcp_import.py test_qdrant_supervise.py` -> `pass`
