---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:af32788d266d29310f882f8fb71fd05859ed79c7fe0baf81b860c9202eb29852'
step_id: 'S08'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# Verify sparse backup discovery, per-source limits, grouped output, and malformed-source rejection

## Scope

- `src/vaultspec_rag/tests/test_logging_config.py`

## Description

- Verify sparse generations, source selection, independent limits, and retained empty groups.
- Verify malformed sources are rejected.
- Verify UTF-8 records spanning reverse-read blocks with and without a final newline.

## Outcome

Reader tests prove bounded retrieval and byte-boundary correctness against real files.

## Notes

None.
