---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace index-cuda-ceiling with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- PHASE SUMMARY:
     This file rolls up every <Step Record> belonging to one Phase
     of the originating plan. Each Step (S##) in the Phase produces
     one <Step Record> in `.vault/exec/`; this summary aggregates
     them, lists modified / created files across the Phase, and
     reports verification status. -->

# `index-cuda-ceiling` `P02` summary

<!-- Brief summary of overall progress across every Step in this Phase,
     followed by a list of files touched across the Phase, e.g.:
     - Modified: `{file1}`
     - Created: `{file2}` -->

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

<!-- High-level description of work accomplished. -->

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
