---
tags:
  - '#research'
  - '#gpu-admission-gate'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
related: []
---

# `gpu-admission-gate` research: `GPU contention admission and the parallel test ban`

Concurrent agent-launched pytest processes each loaded the embedding and
reranker stacks onto the one RTX 4080 SUPER (16 GiB), starved VRAM, and crashed
the workstation. The question this research grounds: where can the system
refuse - before a model load and before a test run - when the device is already
contended, and how can parallelised GPU tests be banned structurally rather
than by convention? The evidence picture: every signal and every coordination
primitive the gate needs already exists in hardened form; what is missing is
one admission predicate at the load seam, one collection-time refusal at the
test seam, one cross-process mutex for GPU test sessions, and the wiring that
lets the test lane stand the resident daemon down. The open choices - predicate
placement, coordination mechanism, refusal versus grouping, and whether the
preflight drives quiesce - are framed below for the ADR to settle.

## Findings

### The single model-load gate checks presence, never headroom

`load_torch()` (`src/vaultspec_rag/_gpu.py:55`) is the one centralised torch
loader for every local-mode compute path. It asserts
`torch.cuda.is_available()` (`src/vaultspec_rag/_gpu.py:68`) and sets the
allocator fraction (`src/vaultspec_rag/_gpu.py:72`), and that is all: presence,
never free memory, never foreign load. Every model construction funnels through
it - the embedding-stack dependency check (`src/vaultspec_rag/embeddings.py:213`),
the lazy reranker load (`src/vaultspec_rag/service.py:289`), the search encode
path (`src/vaultspec_rag/search/_searcher.py:422`), and the service-lifecycle
warmup (`src/vaultspec_rag/cli/_service_lifecycle.py:209`). It is therefore the
natural admission choke point, with two placement caveats. First, it is called
repeatedly on hot paths (per search encode), so a per-call device probe buys
nothing after the first load and costs a driver query per call. Second, and
decisively: once this process's own models are resident, a device-wide
free-memory reading counts that residency as pressure, so a per-call predicate
would eventually refuse the very process it admitted. The reading is only
meaningful *before* the first load. The module docstring
(`src/vaultspec_rag/_gpu.py:15`) names the deliberate exception - the
read-only probes (`/health`, `/metrics`, readiness diagnosis, memory probe)
keep guarded function-local imports and report `cuda=False` rather than raise -
and nothing about an admission predicate inside `load_torch()` touches those
paths, because they never call it.

### The device-wide free-memory signal already exists and sees foreign processes

`cuda_free_memory_mb()` (`src/vaultspec_rag/memory_probe.py:191`) reads
`torch.cuda.mem_get_info()` (`src/vaultspec_rag/memory_probe.py:204`)
torch-tolerantly, returning `None` on a torch-free or CPU-only host.
`cuda_pressure()` (`src/vaultspec_rag/memory_probe.py:209`) reads the same
counter; its own comment (`src/vaultspec_rag/memory_probe.py:216`) states the
figures are device-wide and "see pressure from every process on the card".
This is the reusable contention signal; a second reader implementation is
forbidden, so any admission predicate must consume these functions. One
behavioural difference matters for placement: `cuda_pressure()` refuses to
initialise a CUDA context it does not own
(`src/vaultspec_rag/memory_probe.py:228`), while `cuda_free_memory_mb()` will
initialise one - acceptable at a model-load admission site (the process is
about to own a context anyway), unacceptable on the read-only probe paths.

### The pressure tier is the wrong shape for admission

The observe-only tier (`src/vaultspec_rag/pressure.py:36`) is governed by an
accepted record that fixes "nothing acts on the tier" and defers every
behavioural rung pending calibration history. Beyond that authority question,
the mechanism mismatches admission on three axes: escalation needs three
consecutive samples at a 5-second cadence
(`src/vaultspec_rag/pressure.py:45`, `src/vaultspec_rag/pressure.py:52`) -
tens of seconds of history where admission needs one synchronous instant
reading; the evaluator is a daemon-resident process singleton
(`src/vaultspec_rag/pressure.py:343`) - a fresh pytest or local-mode CLI
process has no history at the moment it must decide; and its staleness rule
deliberately fails open to `nominal`, the inverse of what a safety gate wants.
The tier and the gate answer different questions on different clocks. What the
gate can share with it without forking implementations is the reading source
(the memory-probe functions above), not the verdict.

### The ceiling arithmetic governs in-job demand, not load admission

The per-job indexing CUDA budget - absolute ceiling
`min(baseline + free - headroom, total - headroom)`
(`src/vaultspec_rag/memory_probe.py:243`,
`src/vaultspec_rag/memory_probe.py:292`), per-job forward-peak capture inside
`gpu_lock` (`src/vaultspec_rag/memory_probe.py:509`), baseline-net enforcement
on both sides (`src/vaultspec_rag/memory_probe.py:940`) - is settled and
verified. It admits and polices *work* in a process whose models are already
resident. It does not cover the step before: whether the model stack should be
brought up at all on a contended card. Its governing records explicitly defer
the multi-tenant case - several processes competing for one device's free
memory - to the quiesce sibling; the admission gate sits squarely in that
deferred space. Its configuration precedent matters: the knobs live beside each
other in `src/vaultspec_rag/config/_settings.py:308` (`index_rss_ceiling_mb`,
`index_cuda_ceiling_mb` at `:315`, `index_cuda_headroom_mb: 2048.0` at `:320`,
`index_cuda_allocator_fraction: 0.8` at `:321`), so an admission floor belongs
in the same table. The resident-baseline machinery
(`sample_resident_cuda_baseline` at `src/vaultspec_rag/memory_probe.py:393`,
`rebase_resident_cuda_baseline` at `src/vaultspec_rag/memory_probe.py:418`)
already handles the load and release transitions the gate brackets.

### Test-side seams: the tier gate, a grouping defect, and the xdist boundary

Every collected test declares a tier, enforced at collection time
(`conftest.py:215` calling `enforce_tiers`,
`src/vaultspec_rag/tests/_tier_gate.py:137`). The established
"refuse before any test runs" precedent is `pytest_runtestloop`
(`conftest.py:228`): when selected items carry GPU markers and no Hugging Face
token is available, the session exits via `pytest.exit(..., returncode=1)`
(`conftest.py:241`). That hook is the natural home for a GPU admission
preflight - it runs after deselection, so unit-only runs are never touched.

The grouping defect claimed upstream is confirmed: `group_gpu_items`
(`src/vaultspec_rag/tests/_tier_gate.py:148`) applies
`pytest.mark.xdist_group("gpu")` to items matching `GPU_MARKERS` only
(`src/vaultspec_rag/tests/_tier_gate.py:65` -
integration/quality/performance/robustness), which excludes both `cuda` and
`subprocess_gpu` (`src/vaultspec_rag/tests/_tier_gate.py:69`,
`SLOW_TIERS` at `:75`). Under `-n auto`, `cuda`-marked and
`subprocess_gpu`-marked tests are not grouped onto one worker and can
co-schedule with the grouped set on sibling workers - each xdist worker being
its own process with its own model residency.

Grouping is also insufficient in kind, twice over. Within one pytest session,
`xdist_group` serialises *execution* on one worker but not *residency*: a
worker that ran integration tests keeps its session-scoped models resident, so
a later `subprocess_gpu` test on the same worker still overlaps that residency
with its spawned process's own load - the exact >16 GiB combination the marker
comment warns about (`src/vaultspec_rag/tests/_tier_gate.py:67`), and the
reason `just test gpu` runs two serial invocations (`justfile:401`). And
across sessions, `xdist_group` says nothing at all: several pytest processes on
one machine - the incident - are invisible to it. Any structural ban must
therefore act at two levels: within a session (refuse GPU-marked selections
under xdist distribution) and across sessions (a machine-wide mutex).

The lane configuration already encodes the intended discipline: `"python"`
runs `-n auto --dist loadfile` with every slow tier excluded
(`justfile:399`), `"gpu"` runs two serial invocations with no `-n`
(`justfile:401`), and the long comment block (`justfile:356`) explains why the
other lanes must never parallelise. Nothing enforces that discipline against a
hand-typed `pytest -n auto -m integration`; the ban has to live in collection
code, not in the recipe.

### Cross-process primitives: the machine lock pattern and the containment boundary

The crash-safe coordination pattern is established:
`src/vaultspec_rag/_machine_lock.py` holds an OS advisory lock
(`_try_lock_exclusive` at `src/vaultspec_rag/_machine_lock.py:215`, via the
shared `_fd_lock` helpers) on a file for the holder's lifetime; the OS releases
it on process death, so no stale-reclaim heuristic exists anywhere in the
mechanism. `machine_lock_live_holder()`
(`src/vaultspec_rag/_machine_lock.py:321`) shows the side-effect-free try-probe
idiom, and the quiesce record already chose a second, distinct OS lock as its
crash-safe cross-process lease rather than overloading the service singleton
lock. A GPU-session lock would be a third instance of the same hardened
pattern.

The anchoring question has a trap. The service lock anchors beside the managed
Qdrant storage (`src/vaultspec_rag/_machine_lock.py:97`), which pytest
containment deliberately redirects into a per-session temp root
(`conftest.py:112` pinning `VAULTSPEC_RAG_QDRANT_STORAGE_DIR`;
`register_pytest_singleton_root` imported at `conftest.py:142`;
`enforce_pytest_managed_singleton_containment` at
`src/vaultspec_rag/_test_isolation.py:346` refusing any singleton effect
outside that root). A GPU test mutex anchored through the same config would be
per-session - private to each pytest run and useless for the cross-process
exclusion it exists to provide. The GPU is machine hardware, not
machine-singleton *state*: a session mutex must anchor machine-globally,
outside the containment boundary (the system temp directory is the
config-independent candidate), and that exemption must be deliberate and
documented, because the containment guard exists precisely to catch tests
reaching outside their root. `register_pytest_singleton_root` itself was
assessed as a detection point for sibling pytest processes and is too coarse:
session roots exist for unit-only runs too, and "a recently-touched root"
cannot distinguish a GPU session from any other
(`src/vaultspec_rag/_test_isolation.py:162`).

### Quiesce is implemented, unwired from tests and CI, and frees no VRAM

The cooperative pause shipped: `server pause` / `server resume` CLI verbs
(`src/vaultspec_rag/cli/_service_quiesce.py:103`,
`src/vaultspec_rag/cli/_service_quiesce.py:112`) drive service-owned routes
with idempotent single-envelope semantics, and workers park at unprotected
checkpoints. Nothing in the test lanes or CI invokes any of it - confirmed:
`justfile:397` and `.github/workflows/ci.yml:227` contain no pause/resume
step.

A materially load-bearing refinement to the upstream framing: the implemented
pause parks workers but releases no memory. `_quiesce_transition`
(`src/vaultspec_rag/server/_routes.py:1047`) only flips the gate; no
`empty_cache`, no registry release, no baseline rebase appears anywhere on the
pause path. The quiesce record itself scoped the VRAM release to its deferred
phase 2 and named `server pause` as the natural site to drive it. So "wire
quiesce into the test preflight" as it stands buys quiet - no new daemon
forwards during the borrow - but not headroom: the resident stack (several
GiB - embedding models eagerly, reranker lazily at
`src/vaultspec_rag/service.py:265`) stays on the card, and a free-VRAM
preflight would still refuse. The release machinery exists and is exercised on
the shutdown path: `close_all()` (`src/vaultspec_rag/server/_main.py:138`,
`src/vaultspec_rag/server/_main.py:164`,
`src/vaultspec_rag/server/_lifespan.py:804`) plus
`rebase_resident_cuda_baseline` (`src/vaultspec_rag/memory_probe.py:418`),
whose docstring already warns that callers must drop references and collect
before rebasing because model stacks are cycle-held. Making pause release
resident models (and lazily reload on demand after resume) is an increment the
quiesce record anticipated but did not authorise; the ADR must decide whether
this feature authorises it, because without it the CI preflight on the shared
workstation refuses whenever the developer's resident daemon holds models -
converting the wedge into a permanent refusal rather than removing it.

The stranded-pause hazard the quiesce record names remains: a CI job that
pauses and then dies without its resume post-step leaves the daemon held, with
recovery manual until the deferred phase-2 lease/observer lands.

### The CI job verifies visibility, not availability

The `gpu-tests` job (`.github/workflows/ci.yml:227`) is
`workflow_dispatch`-only (`.github/workflows/ci.yml:255`), runs on
`[self-hosted, windows, gpu, cuda]` (`.github/workflows/ci.yml:256`), in a
`cancel-in-progress: false` concurrency group (`.github/workflows/ci.yml:235`).
Its preflight asserts only that CUDA is *visible*
(`.github/workflows/ci.yml:296`) before running `just test gpu`
(`.github/workflows/ci.yml:302`). The job's own comment
(`.github/workflows/ci.yml:242`) records that auto-running on push "wedged the
runner" and that "shared-GPU contention made results non-deterministic" - the
contention problem is documented there as unsolved. The security posture is
fixed by its governing record: public repo, self-hosted runner is RCE on the
host, `workflow_dispatch` requires write access; any preflight change must add
no new trigger, no new secret exposure, and no fork-reachable path.

### The option space the ADR must settle

Enforcement placement: (a) a predicate inside `load_torch()` evaluated once
per process, before the first successful load, latched thereafter - single
choke point, no hot-path cost, self-residency cannot poison the reading;
(b) per-call evaluation - rejected by the evidence above (self-refusal after
residency, hot-path driver query); (c) at each model constructor - two-plus
sites, a drift surface the canonical-code rule exists to prevent. The evidence
favours (a).

Predicate: a free-VRAM floor read from the existing probe is the only option
that needs no new reader, subsumes foreign-process detection (refusal is about
insufficient room, not about who holds it), and works identically in daemon,
CLI-local, and pytest processes. Per-process NVML enumeration adds a
dependency surface for a question the floor already answers. The pressure tier
is the wrong shape (above). The floor's default must relate honestly to the
known demand: resident stack plus the existing 2048 MiB headroom figure.

Cross-process coordination: detection-only cannot close the simultaneous-load
race (two processes both read 10 GiB free, both admit, both load); an
open-ended lease held for residency can wedge and duplicates the quiesce
lease's deferred design space. The narrow middle is a load-window try-lock:
hold an OS advisory lock only across the check-plus-load window, non-blocking
acquire, refuse on contention, released once the load completes and the
baseline is sampled. Crash-safe by construction (death releases it), and it
cannot wedge because it is never held across residency. Failure handling when
the lock file itself is unreachable (I/O error, unwritable temp dir) is a
policy choice between refusing all compute on a filesystem hiccup and
degrading to detection-only with a logged warning.

Test-session admission: a `pytest_runtestloop` preflight mirroring the
HF-token precedent - try-acquire a machine-global GPU-session lock when
selected items carry any slow tier, `pytest.exit` naming the holder on
refusal, hold for the session. Within-session ban: refuse the session at
collection time when slow-tier items are selected under xdist distribution,
versus keeping/extending grouping. Refusal supersedes grouping entirely (a
session that cannot distribute GPU tests has nothing left to group), which
under the canonical-code rule implies deleting `group_gpu_items` rather than
carrying both; silently downgrading distribution was the alternative and hides
the misconfiguration it should surface.

Preflight-drives-quiesce: the test/CI preflight can (a) refuse outright on low
free VRAM, (b) pause the daemon then check, or (c) pause-with-release then
check. On the shared workstation (a) and (b) refuse indefinitely while the
resident daemon holds models; only (c) actually clears the card, at the cost
of authorising the VRAM-release increment and accepting lazy reload latency on
resume. The stranded-pause cost applies to (b) and (c) equally and is bounded
by an always-run resume post-step plus manual `server resume`.

Not investigated: NVML per-process accounting as a diagnostic enrichment
(which PIDs hold the card) - orthogonal to the refusal decision and addable to
the probe surface later; GPU scheduling under WDDM versus TCC driver modes;
and any Windows job-object approach to fencing foreign GPU processes, which
would be control of processes this project does not own.

## Sources

- `src/vaultspec_rag/_gpu.py:15`, `src/vaultspec_rag/_gpu.py:55`,
  `src/vaultspec_rag/_gpu.py:68`, `src/vaultspec_rag/_gpu.py:72`
- `src/vaultspec_rag/memory_probe.py:191`,
  `src/vaultspec_rag/memory_probe.py:204`,
  `src/vaultspec_rag/memory_probe.py:209`,
  `src/vaultspec_rag/memory_probe.py:216`,
  `src/vaultspec_rag/memory_probe.py:228`,
  `src/vaultspec_rag/memory_probe.py:243`,
  `src/vaultspec_rag/memory_probe.py:292`,
  `src/vaultspec_rag/memory_probe.py:393`,
  `src/vaultspec_rag/memory_probe.py:418`,
  `src/vaultspec_rag/memory_probe.py:509`,
  `src/vaultspec_rag/memory_probe.py:940`
- `src/vaultspec_rag/pressure.py:36`, `src/vaultspec_rag/pressure.py:45`,
  `src/vaultspec_rag/pressure.py:52`, `src/vaultspec_rag/pressure.py:343`
- `src/vaultspec_rag/config/_settings.py:308`,
  `src/vaultspec_rag/config/_settings.py:315`,
  `src/vaultspec_rag/config/_settings.py:320`,
  `src/vaultspec_rag/config/_settings.py:321`
- `conftest.py:112`, `conftest.py:142`, `conftest.py:215`, `conftest.py:228`,
  `conftest.py:241`
- `src/vaultspec_rag/tests/_tier_gate.py:65`,
  `src/vaultspec_rag/tests/_tier_gate.py:67`,
  `src/vaultspec_rag/tests/_tier_gate.py:69`,
  `src/vaultspec_rag/tests/_tier_gate.py:75`,
  `src/vaultspec_rag/tests/_tier_gate.py:137`,
  `src/vaultspec_rag/tests/_tier_gate.py:148`
- `src/vaultspec_rag/_machine_lock.py:97`,
  `src/vaultspec_rag/_machine_lock.py:215`,
  `src/vaultspec_rag/_machine_lock.py:321`
- `src/vaultspec_rag/_test_isolation.py:162`,
  `src/vaultspec_rag/_test_isolation.py:346`
- `src/vaultspec_rag/cli/_service_quiesce.py:103`,
  `src/vaultspec_rag/cli/_service_quiesce.py:112`
- `src/vaultspec_rag/server/_routes.py:1047`,
  `src/vaultspec_rag/server/_main.py:138`,
  `src/vaultspec_rag/server/_main.py:164`,
  `src/vaultspec_rag/server/_lifespan.py:804`
- `src/vaultspec_rag/service.py:265`, `src/vaultspec_rag/service.py:289`
- `src/vaultspec_rag/embeddings.py:213`,
  `src/vaultspec_rag/search/_searcher.py:422`,
  `src/vaultspec_rag/cli/_service_lifecycle.py:209`
- `justfile:356`, `justfile:397`, `justfile:399`, `justfile:401`
- `.github/workflows/ci.yml:227`, `.github/workflows/ci.yml:235`,
  `.github/workflows/ci.yml:242`, `.github/workflows/ci.yml:255`,
  `.github/workflows/ci.yml:256`, `.github/workflows/ci.yml:296`,
  `.github/workflows/ci.yml:302`
