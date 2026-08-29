---
tags:
  - '#research'
  - '#platform-backend-selection'
date: '2026-08-28'
modified: '2026-08-28'
body_schema: 'body-v2'
body_hash: 'sha256:df8b6a367d6961bf8eed53f934ed52df75b3faadb8064b7ad4ba677027e66ca6'
related:
  - '[[2026-03-06-gpu-only-rag-stack-adr]]'
---

# `platform-backend-selection` research: `which accelerator each platform can actually use, and what the install puts there`

`2026-03-06-gpu-rag-stack-adr` records a user mandate: GPU-only inference, no
CPU fallback. The code enforces it through one gate, and the gate tests for
CUDA. Two consequences of that follow, and they pull in opposite directions -
Apple silicon has a working GPU the gate cannot see, and a GPU-less Linux host
is handed five gigabytes of CUDA it can never use.

Neither is a case for weakening the mandate. What the evidence below frames is
narrower: whether "GPU" means "CUDA", and whether the CUDA stack belongs in the
default dependency set or in the provisioning verb that already exists for the
platforms where it is not there. The ADR must settle both.

## Findings

### The gate is CUDA-shaped, not accelerator-shaped

`_gpu.py` is the single load-bearing gate: every local-mode compute path
obtains torch through `load_torch()`, which admits or refuses the process. Its
refusal message names CUDA specifically, and its check is
`torch.cuda.is_available()`.

That single-gate design is what makes a second backend tractable: the decision
about which device to use is made in one place rather than at each call site.
The CUDA assumption, however, has leaked past it. `torch.cuda.*` appears in
`embeddings.py`, `api.py`, `search/_searcher.py`, `memory_probe.py`,
`_readiness.py`, `server/_state.py` and `cli/_gpu_errors.py`. The reporting
path at `api.py:813` is the visible symptom - on a host with no CUDA it reports
no GPU and 0 VRAM, which on Apple silicon is a false statement about the
hardware rather than a missing feature.

The admission logic is the deepest CUDA coupling. It admits a workload by
interrogating free VRAM on a discrete device; unified memory has no equivalent
reading, so admitting an MPS workload is not the same computation with a
different accessor.

### The macOS gap was accepted knowingly, not overlooked

`2026-03-06-gpu-rag-stack-adr` lists "cannot run on CPU-only machines or macOS
without CUDA" among its negative consequences. So macOS falling outside the
supported set is a recorded consequence of the original decision, not a
regression.

What has changed since is only that the platform acquired a usable backend in
torch. Treating this as a bug misreads the record; treating it as settled
misses that the mandate's stated intent - use the GPU, never the CPU - is
satisfied by MPS rather than violated by it. The question the ADR faces is
whether "GPU-only" was a decision about CUDA or about not running on CPU.

### The CUDA weight on Linux comes from PyPI, not from this project

`pyproject.toml` pins torch to the cu130 index, but under `[tool.uv.sources]`,
which is workspace-scoped and is not carried in published wheel metadata. An
installing user therefore resolves torch from PyPI, and what PyPI supplies
differs sharply by platform. From `torch@2.13.0`:

| platform                | wheel  | CUDA dependencies            |
| ----------------------- | ------ | ---------------------------- |
| `manylinux_2_28_x86_64` | 527 MB | 5 nvidia/triton requirements |
| `win_amd64`             | 122 MB | none                         |
| `macosx_14_0_arm64`     | 111 MB | none                         |

Every CUDA requirement in torch's metadata is gated on
`platform_system == "Linux"`. So the asymmetry is upstream: PyPI's Linux torch
is the CUDA build and its Windows and macOS wheels are not.

The consequence is that Linux is the only platform where a plain install
arrives GPU-capable by accident, and it does so whether or not a GPU exists.

### Windows and macOS already depend on a provisioning step

Because their PyPI wheels carry no CUDA, a bare install on Windows produces a
torch that cannot satisfy the gate at all. The project already knows this:
`cli/_gpu_errors.py` exists to detect exactly that state and direct the user to
`vaultspec-rag install`, which configures the cu130 index and installs the GPU
build.

This is the finding that reframes the Linux question. Provisioning the CUDA
stack through the install verb rather than the default dependency set is not a
new mechanism to be invented - it is what two of the three platforms already
do, and Linux is the outlier. Moving Linux onto that path changes when the GPU
build arrives, not whether it is required, so the runtime gate keeps refusing
CPU exactly as it does now.

### What was not investigated

No Apple silicon host was reachable during this work, so no MPS measurement was
taken: whether the dense and sparse models both run end to end under MPS,
what `PYTORCH_ENABLE_MPS_FALLBACK` would silently mask, and what throughput
looks like relative to CUDA are all unmeasured. Everything above about macOS
comes from torch's published metadata and from this repository's own code, and
the ADR cannot treat MPS as a supported backend on this evidence alone.

The size of a GPU-less Linux install after moving the CUDA stack behind the
install verb was not measured, only bounded below by the 527 MB torch wheel
itself. Whether an already-installed environment migrates cleanly, rather than
only a fresh one, was not examined.

## Sources

- `src/vaultspec_rag/_gpu.py`
- `src/vaultspec_rag/api.py:813`
- `src/vaultspec_rag/cli/_gpu_errors.py`
- `pyproject.toml`
- `torch@2.13.0` PyPI metadata and wheel listing
- https://docs.pytorch.org/docs/stable/notes/mps.html
- https://docs.astral.sh/uv/concepts/projects/dependencies/
