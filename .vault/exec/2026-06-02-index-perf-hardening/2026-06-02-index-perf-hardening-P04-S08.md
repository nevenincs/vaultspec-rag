---
tags:
  - '#exec'
  - '#index-perf-hardening'
date: '2026-06-02'
modified: '2026-06-30'
step_id: 'S08'
related:
  - "[[2026-06-02-index-perf-hardening-plan]]"
---

# Add real-GPU tests for parallel chunking correctness and pipeline chunk-identity parity

## Scope

- `src/vaultspec_rag/tests/integration/`

## Description

- Add CPU-only parity tests: parallel == serial chunk ids, worker hash == `hashlib.file_digest`, CRLF parity, byte-gate behaviour, and a guard that importing the worker never loads torch.

## Outcome

All parity tests pass with a real spawn pool and no mocks.

## Notes

Measured large-codebase chunk-stage A/B: real 17,872 files 1.9x; heavy synthetic 8,000 files 3.6x; parity OK.
