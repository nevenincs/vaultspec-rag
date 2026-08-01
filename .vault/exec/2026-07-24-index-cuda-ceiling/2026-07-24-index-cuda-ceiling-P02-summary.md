---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:7d12cff758ef8fb6086545603b20b2e845554f01bde5db85b7e7004e613ec807'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# `index-cuda-ceiling` `P02` summary

All six Steps (`S04`-`S09`) complete. The effective CUDA ceiling derives
from real device capacity and the operator override works in both
directions at every enforcing site.

- Modified: `src/vaultspec_rag/memory_probe.py`
- Modified: `src/vaultspec_rag/config.py`
- Modified: `src/vaultspec_rag/job_dispatch.py`
- Modified: `src/vaultspec_rag/indexer/_codebase_indexer.py`
- Modified: `src/vaultspec_rag/indexer/_document_indexer.py`
- Modified: `src/vaultspec_rag/tests/test_config.py`

## Description

`resolve_index_cuda_ceiling_mb` replaces the one-way `min(profile, config)`
clamp at all three enforcing sites (dispatch admission, the codebase budget
builder, the document budget builder). A positive `index_cuda_ceiling_mb`
is authoritative in either direction; the `0` sentinel (new default) derives
the ceiling as device total minus `index_cuda_headroom_mb` (default 2048),
via the guarded `cuda_device_total_mb` probe that degrades to the profile
figure on a torch-absent or CPU-only host, keeping torch off service-client
and worker paths. The profile CUDA figure is thereby demoted from hard cap
to fallback default, so a 16 GiB card is no longer pinned at the 12 GiB
profile constant. Tests bind the raise-and-lower override behaviour and
both auto-derive branches.

One deviation from the plan's locators: the device-capacity probe lives in
`src/vaultspec_rag/memory_probe.py` beside the other guarded probes rather
than the GPU gate module named by `S04`; the reachability constraint (no
torch on service-client or spawn-worker paths) holds either way.
