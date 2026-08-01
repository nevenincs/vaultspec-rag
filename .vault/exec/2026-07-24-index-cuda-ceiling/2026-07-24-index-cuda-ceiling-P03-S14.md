---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:6fc76ee6ace171a82fb9c68366b0cef776b2477ac124ce8499bdb202e825d836'
step_id: 'S14'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# enforce every sample checkpoint against the captured baseline-net peak so no path reads max_memory_allocated directly

## Scope

- `src/vaultspec_rag/memory_probe.py`

## Description

- Re-plumb `MemoryBudget.sample` in `src/vaultspec_rag/memory_probe.py`: the enforced CUDA peak is now the job's captured forward maximum; the live allocated/reserved readings stay on the snapshot as process-global diagnostics only.
- Delete the process-global high-water measurement helper so no enforcement path can read `torch.cuda.max_memory_allocated` directly; the capture bracket is the single sanctioned reader.

## Outcome

Non-forward checkpoints - including the field-failing producer/consumer queue-wait labels - enforce against the job's own captured peak. `sample` keeps its outside-the-lock contract; the number is fed out of the critical section, the sampling never moves into it.

## Notes

None.
