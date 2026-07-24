---
tags:
  - '#research'
  - '#index-cuda-shared-device'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - "[[2026-07-24-index-cuda-ceiling-adr]]"
  - "[[2026-07-24-index-cuda-ceiling-research]]"
---

# `index-cuda-shared-device` research: `the indexing CUDA ceiling ignores non-torch device consumers and mis-rejects a runtime peak as corpus size`

The live verification of the CUDA-ceiling fix
(`2026-07-24-index-cuda-ceiling-adr`, step S19) surfaced two residual gaps in the
indexing memory model, both stemming from one blind spot: the ceiling reasons
about the GPU as if the indexing process owned it exclusively. First, the
auto-derived ceiling is `device_total - headroom`, but a real box shares the GPU
with the desktop compositor and other processes, so `total` overstates what
indexing can actually allocate - during S19 the machine's desktop baseline held
~6.5 GiB, leaving ~9.8 GiB free against a 14.3 GiB derived ceiling. Second, the
codebase indexer treats the runtime CUDA allocated high-water as a corpus-sizing
dimension and rejects it against the profile's declared `cuda_bytes`, so on the
6 GiB `embedded-local` profile a legitimate forward peak of 6.73 GiB was refused
as `corpus_limit_exceeded` even though the runtime ceiling and per-job capture
already govern allocation. The question this grounds is how the ceiling and the
profile CUDA dimension should behave on a shared device: what the ceiling should
be derived from, and whether a runtime peak belongs in the static corpus-size
admission at all. The evidence favours deriving the ceiling from free device
memory (clamped by total-minus-headroom) and removing the runtime CUDA peak from
the corpus-sizing rejection, leaving runtime memory to the ceiling and per-job
capture that already own it.

## Findings

### The auto-derived ceiling is computed from total device memory, not free

`resolve_index_cuda_ceiling_mb` derives the auto ceiling as
`cuda_device_total_mb() - headroom_mb`
(`src/vaultspec_rag/memory_probe.py`), and `cuda_device_total_mb` reads
`get_device_properties(...).total_memory`
(`memory_probe.py`) - the physical device size, 16376 MiB on the RTX 4080 SUPER.
It never consults free memory. On a shared desktop GPU the difference is large
and variable: `torch.cuda.mem_get_info()` returned `free=15061 / total=16376`
MiB at rest, but the S19 run recorded `nvidia-smi` desktop usage of ~6535 MiB
(dwm, the remote-desktop compositor, and browser GPU processes), leaving roughly
9.8 GiB free against the 14328 MiB the derivation produced. A ceiling above
actual free memory is a ceiling that admits work the device cannot hold; the
genuine OOM is then caught only by the allocator backoff, not by the pre-emptive
guard that is supposed to fail fast. `mem_get_info` returns `(free, total)` and
is the standard torch call for available memory, so the data the derivation
needs is one call away.

### The codebase indexer rejects the runtime CUDA peak as a corpus-size dimension

`_set_support_measurement` publishes the running support measurement and raises
`CORPUS_LIMIT_EXCEEDED` on the first dimension `limits.exceeded_by` reports over
budget (`src/vaultspec_rag/indexer/_codebase_indexer.py:580`). The measurement's
`cuda_bytes` is not a static property of the corpus - it is set from the observed
allocated high-water, `int(snapshot.peak_cuda_allocated_mb * 1024**2)`
(`_codebase_indexer.py:499`) - so a runtime forward peak is compared against the
profile's declared `cuda_bytes` as though it described corpus size. On the
`managed-service` profile (`cuda_bytes` = 12 GiB) this rarely bites, but the
`embedded-local` profile declares 6 GiB, and S19 saw a code job for one root fail
with "code cuda_bytes is 6728776192; profile 'embedded-local' permits
6442450944" - a 6.73 GiB forward peak refused on a 6 GiB profile, on a 16 GiB
card with room to spare. The other corpus dimensions - source files, generated
chunks, weighted bytes, extracted bytes - are genuine static sizing properties;
`cuda_bytes` is the one runtime quantity mixed in among them.

The document indexer does not share this defect: its
`_DocumentResourceBudget._retain_snapshot`
(`src/vaultspec_rag/indexer/_document_indexer.py:168`) retains the projected
`cuda_bytes` as a diagnostic counter only, and `reserve` gates on chunks,
weighted, and extracted bytes but never feeds the runtime counter through a
rejection. Admission-time measurements build with `cuda_bytes = 0` on both paths.
So the corpus-CUDA rejection is a code-path-only defect, and the fix brings the
code indexer to match the document indexer rather than changing both.

The ceiling derivation itself has three call sites: the two indexer budget
builders that enforce, and the admission snapshot in `job_dispatch.py` that is
reported and persisted. Only the two budget builders gate a job; the admission
snapshot is a point-in-time diagnostic.

### The corpus CUDA dimension is now redundant with the runtime ceiling

Runtime CUDA allocation is already governed twice over by the ceiling work
(`2026-07-24-index-cuda-ceiling-adr`): the per-job forward-peak capture enforces
each job's own demand against the derived ceiling, and the allocator OOM backoff
halves the batch under genuine pressure. The corpus-sizing `cuda_bytes`
rejection predates that enforcement and duplicated its intent with a coarser,
static-looking check. With per-job capture in place, projecting the runtime peak
into the corpus admission adds no protection the ceiling does not already
provide, and on the small profile it actively over-rejects. Removing it does not
weaken the runtime guard; it removes a second, miscategorised copy of it.

### Free memory is a moving target, which shapes the fix rather than blocking it

`mem_get_info().free` is a point-in-time reading: the desktop baseline rose and
fell across the S19 window (15061 MiB free at rest versus ~9.8 GiB under load),
and the resident models load into that free pool after the ceiling is derived.
This means a free-based ceiling cannot be a single admission-time constant read
once and trusted forever - but it does not need to be. The ceiling is a coarse
pre-emptive guard backed by the per-job capture and the OOM backoff, so deriving
it from free-at-model-load, clamped below `total - headroom`, is strictly better
than deriving from total alone: it lowers the ceiling toward reality when the
device is contended and never raises it above the physical cap. The exact
sampling point - before or after model residency - is a decision for the ADR.

### Option space

For the ceiling derivation, the evidence favours
`min(free - headroom, total - headroom)` (equivalently, derive from free and keep
the total-minus-headroom clamp), so a contended device lowers the ceiling and an
idle one recovers the current behaviour. The bidirectional operator override
stays authoritative above both. An alternative - subtracting a fixed larger
headroom from total to "cover" the desktop - was rejected: the desktop baseline
is not fixed (a remote-desktop session, a browser, a second GPU app all vary it),
so any constant is wrong somewhere, whereas free memory measures the real
remainder directly.

For the corpus CUDA dimension, the options are removing `cuda_bytes` from
`exceeded_by` entirely (runtime memory is not corpus size), or keeping it
measured and reported but non-fatal. The evidence favours removal from the
rejection while the measurement may remain for diagnostics, because the runtime
ceiling and per-job capture already own the enforcement and the static corpus
dimensions remain the honest admission gate.

### Not investigated

Whether `mem_get_info` is cheap enough to call at every job admission was
assumed, not measured (it is a lightweight driver query, but the exact cost was
not profiled). Whether other roots' concurrent GPU jobs should factor into a
single process's free-memory reading - the multi-tenant question - is left to the
sibling `service-quiesce` work and is out of scope here. The `embedded-local`
profile's other dimensions were not re-examined; only its CUDA dimension is in
question.

## Sources

- `src/vaultspec_rag/memory_probe.py` (`resolve_index_cuda_ceiling_mb`,
  `cuda_device_total_mb`)
- `src/vaultspec_rag/indexer/_codebase_indexer.py:499`, `:580`
- `src/vaultspec_rag/index_profiles.py:158`, `:184` (managed-service 12 GiB,
  embedded-local 6 GiB CUDA dimensions)
- `torch.cuda.mem_get_info` (returns `(free, total)` device bytes)
- Live `mem_get_info` and S19 `nvidia-smi` / job-failure readings, 2026-07-24
  (observational; not reproducible from this repository)
