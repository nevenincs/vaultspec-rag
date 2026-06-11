---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
step_id: 'S15'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Make the full-scan extension, size, and binary gate preprocess-rule-aware (D2, D10)

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

Reordered `_process_scan_files` to apply the ignore gate first, then a
`_matches_preprocess_rule(rel)` short-circuit that admits a matched file regardless of
extension, `_MAX_FILE_SIZE`, or binary content (the preprocessor extracts indexable text);
unmatched files run the original extension/size/binary gauntlet unchanged (D2, D10). Ignore
still wins absolutely.

## Outcome

A matched `.pdf` outside `SUPPORTED_EXTENSIONS` and over the size cap is now scanned in;
ordinary scan behaviour is byte-identical (103 indexer unit tests pass).

## Notes

`_matches_preprocess_rule` uses `getattr` so `__new__`-built test instances stay safe.
