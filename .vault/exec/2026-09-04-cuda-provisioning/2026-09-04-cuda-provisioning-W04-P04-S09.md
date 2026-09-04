---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:e5621340c3da9f2c96d3c444b2020d5bb1763bf6bd2bbe6d69670649abe81021'
step_id: 'S09'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Treat torch absent by design as a state rather than an installation defect

## Scope

- `src/vaultspec_rag/cli/_process.py`

## Changes

- `M src/vaultspec_rag/cli/_process.py`
- `M src/vaultspec_rag/commands/_tool_torch.py`
- `M src/vaultspec_rag/tests/test_tool_torch_repair.py`

## Notes

The distinction is drawn inside the probe, because the environment is the only
thing that can answer the question about itself. When the torch import fails
the probe now asks whether the GPU stack is installed at all, and exits 6 when
it is not. Exit 3 keeps its meaning and its defect classification: the stack is
present and torch is missing anyway, which is what a half-completed
replacement leaves behind.

Two axes rather than one. An environment without torch still cannot serve a
request, so exit 6 remains blocking for a service start; it is simply not a
defect, so an install must not fail over it and the repair has nothing to
offer. The repair transaction returns NOT_APPLICABLE for it, which does not
block, and the operator is told to choose the GPU extra rather than to run a
reinstall that would change nothing.

Verified live against real environments rather than only through the exit-code
map: a bare virtual environment reports absence by design and is not a defect;
the same environment with the GPU stack installed reports no supported
accelerator and is a defect.

Guard proof: disabling the by-design branch failed
`test_an_install_without_the_gpu_extra_is_not_a_defect` on its action
assertion, returning CUDA_UNVERIFIED - the blocking outcome that produced the
original exit 2. Restored; zero MUTATION markers remain. Gates: ruff, ty, and
203 tests across the repair and install suites.
