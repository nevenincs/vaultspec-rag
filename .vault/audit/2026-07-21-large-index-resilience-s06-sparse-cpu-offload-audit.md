---
tags:
  - '#audit'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:76a7b17e404b8dc20ca3a3173479b1942bca0822eaaac2a30a188ff1c94e0273'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` audit: `W01.P02.S06 sparse CPU offload and lock boundaries`

## Scope

Independent GPU-lifetime, lock-boundary, ordering, retry, compatibility, and import-safety
review of the final `W01.P02.S06` sparse document batching and its two production streaming
call boundaries.

## Findings

### cpu-transfer-under-gpu-lock | medium | Library offload extended the global lock

The first revision passed `save_to_cpu=True` to Sentence Transformers while both production
callers held `gpu_lock` around the entire wrapper. Version 5.6.0 performs `.cpu()` before it
returns, so every device-to-host transfer remained inside the process-global lock. The final
implementation executes exactly one bounded encode call under the lock, then transfers,
releases the accelerator reference, sparse-converts, and maps results after release.

Final review found no unresolved Critical, High, Medium, or Low findings. Installed library
source confirmed one forward for each input slice no larger than `batch_size`. A real cached
CUDA production probe verified ordered document results and unchanged sparse query behavior.
The finite OOM ladder discards partial results and restarts from document zero, batch size one
still re-raises, both production boundaries use separate dense and sparse lock spans, and no
new consumer or eager Torch import was introduced. Ruff, formatting, ty, BasedPyright,
compile, lazy-import, AST contract, and diff checks passed.

Status: **PASS** after revision.

## Recommendations

Keep device-to-host transfer and all sparse mapping outside `gpu_lock`. In `S11`, remove the
pre-existing prohibited reduced-signature OOM double and replace its claimed coverage with a
disposable real CUDA and cached SparseEncoder test; do not add a production signature fallback,
skip, or xfail for that synthetic API.
