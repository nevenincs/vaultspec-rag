---
tags:
  - '#exec'
  - '#index-progress-bars'
date: '2026-04-12'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:fcd5260ff9f60965404d252770f8a7edb1cf5859df47a48557e8e16f27881bcc'
related:
  - "[[2026-04-12-index-progress-bars-phase-1-plan]]"
---

# `index-progress-bars` ledger

## Changes

- `S01` `A` `src/vaultspec_rag/progress.py`
- `S02` `M` `src/vaultspec_rag/indexer.py`
- `S03` `M` `src/vaultspec_rag/indexer.py`
- `S04` `M` `src/vaultspec_rag/cli.py`
- `S05` `M` `src/vaultspec_rag/api.py`
- `S05` `M` `src/vaultspec_rag/mcp_server.py`
- `S05` `M` `src/vaultspec_rag/watcher.py`
- `S05` `M` `src/vaultspec_rag/tests/conftest.py`
- `S06` `A` `src/vaultspec_rag/tests/test_progress_unit.py`
- `S06` `A` `src/vaultspec_rag/tests/integration/test_indexer_progress_integration.py`
- `S07` `verify:` `.venv/Scripts/python.exe -m pytest src/vaultspec_rag/tests/test_cli_progress_surfaces.py src/vaultspec_rag/tests/test_cli_search_safety.py src/vaultspec_rag/tests/test_cli_progress_lifetime.py -q -ra --strict-markers --strict-config -W error` -> `pass`

## Notes

- `S01` Historical operation attributed from Git commit f8e70dda4b35a5668bcba0392cfb5cba8bcfa28f. Protocol/reporters added. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S02` Historical operation attributed from Git commit f8e70dda4b35a5668bcba0392cfb5cba8bcfa28f. Both indexer entrypoints in old monolith changed; no current split path modification claimed. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S03` Historical operation attributed from Git commit f8e70dda4b35a5668bcba0392cfb5cba8bcfa28f. Both indexer entrypoints in old monolith changed; no current split path modification claimed. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S04` Historical operation attributed from Git commit f8e70dda4b35a5668bcba0392cfb5cba8bcfa28f. Reporter CLI wiring, not manual terminal acceptance. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S05` Historical operation attributed from Git commit f8e70dda4b35a5668bcba0392cfb5cba8bcfa28f. Explicit reporter caller migrations. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S06` Historical operation attributed from Git commit f8e70dda4b35a5668bcba0392cfb5cba8bcfa28f. Counting reporter acceptance tests authored; GPU integration gated historically. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S07` Current root-owned verification after stream-lifetime repair: progress-lifetime-focused-green.log records exit0,52passed15.36s, no warnings/atexit exception. Exact TestModelWarmupProgress nodes `test_a_terminal_gets_a_painted_frame_carrying_both_counts` and `test_a_pipe_gets_the_same_numbers_as_plain_lines` assert actual painted/plain output. Scope is these progress/safety/lifetime modules, not repository-wide GPU or full-suite acceptance. Earlier failed log is not reused as passing evidence.
