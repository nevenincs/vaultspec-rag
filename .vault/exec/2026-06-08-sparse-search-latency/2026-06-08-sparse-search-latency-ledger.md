---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-08'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:8bcea75a305c2cddba74c945e4f96a999f246fde8b3ebbc1550b56972f9c45d9'
related:
  - "[[2026-06-08-sparse-search-latency-plan]]"
---

# `sparse-search-latency` ledger

## Changes

- `S01` `T`
- `S02` `T`
- `S03` `T`
- `S04` `T`
- `S05` `T`
- `S06` `T`
- `S07` `T`
- `S16` `T`
- `S18` `T`
- `S19` `T`
- `S20` `T`
- `S21` `T`
- `S22` `T`
- `S23` `T`
- `S24` `T`
- `S34` `T`
- `S08` `A` `.vault/audit/2026-06-08-comprehensive-code-review-audit.md`
- `S10` `M` `src/vaultspec_rag/mcp/_admin_tools.py`
- `S11` `M` `src/vaultspec_rag/store.py`
- `S12` `M` `src/vaultspec_rag/indexer/_streaming.py`
- `S13` `M` `src/vaultspec_rag/tests/test_cli.py`
- `S13` `A` `src/vaultspec_rag/tests/integration/test_mcp_admin_tools.py`
- `S14` `M` `src/vaultspec_rag/server/_main.py`
- `S15` `M` `src/vaultspec_rag/mcp/_resources.py`
- `S17` `M` `src/vaultspec_rag/server/_routes.py`
- `S25` `verify:` `Historical initial daemon-down status and local GPU/index-count baseline recorded in 2026-06-08-sparse-search-latency-P08-summary` -> `pass`
- `S26` `verify:` `Historical clean daemon start/stop, sidecar creation/removal, and freed port recorded in 2026-06-08-sparse-search-latency-P08-summary` -> `pass`
- `S27` `verify:` `Historical incremental vault REST reindex completing +12 /9 -0 recorded in 2026-06-08-sparse-search-latency-P08-summary` -> `pass`
- `S28` `verify:` `Historical vault/code REST search filters and CLI port delegation recorded in 2026-06-08-sparse-search-latency-P08-summary` -> `pass`
- `S29` `verify:` `Historical actual incremental vault +12 /9 result and observed running watcher recorded in 2026-06-08-sparse-search-latency-P08-summary` -> `pass`
- `S30` `verify:` `Historical six concurrent REST searches without lock errors recorded in 2026-06-08-sparse-search-latency-P08-summary` -> `pass`
- `S31` `verify:` `Historical CLI-managed stop releasing daemon port and lock recorded in 2026-06-08-sparse-search-latency-P08-summary` -> `pass`
- `S32` `verify:` `Historical daemon-down local search, dead-port refusal, and allow-fallback success recorded in 2026-06-08-sparse-search-latency-P08-summary` -> `pass`
- `S33` `verify:` `Historical fresh-start stale-daemon Qdrant-lock recovery recorded in 2026-06-08-sparse-search-latency-P08-summary` -> `pass`

## Notes

- `S08` Historical operation attributed from Git commit 9460f1d8. Actual retained code/review action only; no runtime acceptance or unretained gate result is asserted.
- `S10` Historical operation attributed from Git commit f57b67be. Actual retained code/review action only; no runtime acceptance or unretained gate result is asserted.
- `S11` Historical operation attributed from Git commit f57b67be. Actual retained code/review action only; no runtime acceptance or unretained gate result is asserted.
- `S12` Historical operation attributed from Git commit f57b67be. Actual retained code/review action only; no runtime acceptance or unretained gate result is asserted.
- `S13` Historical operation attributed from Git commit 2c79d74b. Actual retained code/review action only; no runtime acceptance or unretained gate result is asserted.
- `S14` Historical operation attributed from Git commit 2c79d74b. Actual retained code/review action only; no runtime acceptance or unretained gate result is asserted.
- `S15` Historical operation attributed from Git commit 5b38c131. Actual retained code/review action only; no runtime acceptance or unretained gate result is asserted.
- `S17` Historical operation attributed from Git commit cf249af4. Actual retained code/review action only; no runtime acceptance or unretained gate result is asserted.
- `S25` Narrow retained observed check only. Daemon-down exit3 and local GPU/index figures are retained; a complete watcher/project-slot inventory is not asserted. No full compound-Step acceptance or fresh run is asserted.
- `S26` Narrow retained observed check only. The summary retains actual start/stop and readiness outcomes; separate warmup verification is not retained. No full compound-Step acceptance or fresh run is asserted.
- `S27` Narrow retained observed check only. This is a real queued incremental vault REST job; full codebase indexing and every CLI path are not asserted. No full compound-Step acceptance or fresh run is asserted.
- `S28` Narrow retained observed check only. Retained observations cover `doc_type,` `include_paths,` `exclude_paths,` and CLI vault delegation; no broader unrecorded filter/channel matrix is asserted. No full compound-Step acceptance or fresh run is asserted.
- `S29` Narrow retained observed check only. The incremental result is retained, but watcher-driven indexing of a newly changed source is not demonstrated by merely observing `watch_enabled.` No full compound-Step acceptance or fresh run is asserted.
- `S30` Narrow retained observed check only. Six actual concurrent REST searches succeeded; no broader load experiment is inferred. No full compound-Step acceptance or fresh run is asserted.
- `S31` Narrow retained observed check only. Clean daemon stop is retained; project-slot eviction is not separately demonstrated. No full compound-Step acceptance or fresh run is asserted.
- `S32` Narrow retained observed check only. The daemon-down behavior is retained; degraded-service fallback is not separately demonstrated. No full compound-Step acceptance or fresh run is asserted.
- `S33` Narrow retained observed check only. Fresh-start recovery is retained; the planned degraded-server exit4 detection is not demonstrated by that recovery alone. No full compound-Step acceptance or fresh run is asserted.
