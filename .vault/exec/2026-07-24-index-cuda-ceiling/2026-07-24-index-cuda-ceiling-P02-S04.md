---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S04'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace index-cuda-ceiling with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S04 and 2026-07-24-index-cuda-ceiling-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The add a GPU-gated device-capacity query that returns total CUDA memory and is unreachable from torch-free service-client and worker paths and ## Scope

- `src/vaultspec_rag/_gpu.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# add a GPU-gated device-capacity query that returns total CUDA memory and is unreachable from torch-free service-client and worker paths

## Scope

- `src/vaultspec_rag/_gpu.py`

## Description

- Added `cuda_device_total_mb()` to `memory_probe.py`: a guarded probe that
  returns the active device's total VRAM in MiB, or `None` on a torch-absent
  or CPU-only host, sharing the cached module guard with `_measure_cuda_mb`.

## Outcome

The live probe returns `16375.5` MiB on this box, so the auto-derived ceiling
resolves to ~14327 MiB (total minus the 2048 MiB headroom).

## Notes

**Deviation from the plan.** The Step scope names `_gpu.py`, but the probe was
placed in `memory_probe.py` instead. `_gpu.py` is the hard GPU gate whose
`load_torch` deliberately RAISES on a CPU-only host; a soft probe that must
return `None` there contradicts that contract, while `memory_probe.py` already
houses the guarded `None`-returning CUDA probes this one mirrors. The behaviour
and the torch-gating the ADR required are unchanged; only the file differs.
