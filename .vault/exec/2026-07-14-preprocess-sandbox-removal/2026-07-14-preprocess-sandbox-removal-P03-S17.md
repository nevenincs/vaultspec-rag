---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:3263aa55b932d18e9864350b4075cde67f3df5d9f52383051840fcf33b713a15'
step_id: 'S17'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Update worker, config, entry, CLI, server, watcher, and integration tests for the two-state mode and removed flags

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Update worker/config/entry/CLI/server/watcher tests for the two-state mode and removed flags; removed-flag rejection asserted as unknown-option exit 2 on `index` and `server start`.
- `preprocess status` tests assert no `sandbox_backend` field and the direct-execution effect line.
- Integration: containment deny-read/deny-network test deleted; the local-index hook test now asserts direct execution; caching/off/passthrough/incremental tests kept; file import-clean (9 collected).

## Outcome

83 preprocess-adjacent tests plus 378 CLI/server/watcher tests pass; the fresh-interpreter torch-absence guard is untouched and green.

## Notes

Integration suite not executed in-run (machine service was live); collect-only verified.
