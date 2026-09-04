---
tags:
  - '#exec'
  - '#cuda-provisioning'
date: '2026-09-04'
modified: '2026-09-04'
body_schema: 'body-v2'
body_hash: 'sha256:dda0a5aea37677decd3bd8b8db25868b06030a69139aebcfa365447922f96371'
step_id: 'S10'
related:
  - "[[2026-09-04-cuda-provisioning-plan]]"
---

# Collapse the torch pin version to the single lockfile-backed derivation

## Scope

- `src/vaultspec_rag/torch_config/_constants.py and tools/binaries/torch_channel.py`

## Changes

- `A src/vaultspec_rag/torch_config/_lockfile.py`
- `A src/vaultspec_rag/tests/test_torch_pin_single_source.py`
- `M src/vaultspec_rag/torch_config/_constants.py`
- `M tools/binaries/torch_channel.py`
- `M tools/binaries/tests/test_torch_channel.py`
- `M .vault/adr/2026-09-04-cuda-provisioning-adr.md`

## Notes

The Step called for deleting the runtime constant in favour of the lockfile
derivation. That is not possible, and the check that established it is
recorded here: a built wheel contains neither `uv.lock` nor `pyproject.toml`,
verified by inspecting the names in `dist/vaultspec_rag-0.3.13-py3-none-any.whl`.
An installed runtime therefore has nothing to derive from, and the constant is
the only thing an environment holding no torch can name a wheel by.

What was actually collapsed is the derivation, which is the duplication the
canonical-code rule is about. `locked_torch_version` now lives in the package,
the build tooling imports it, and `tools.binaries.torch_channel.locked_version`
is deleted rather than left as a wrapper - its two callers point at the package
function directly. The constant remains as a mirror held to the lockfile by a
test wherever a checkout is reachable, and skipped where it is not.

The ADR's D5 was amended in place to record why the chosen option could not be
taken literally and what replaced it.

Guard proof: drifting the constant to 2.12.0 failed
`test_the_runtime_pin_mirrors_the_locked_version` on
`assert '2.13.0' == '2.12.0'`. Restored; zero MUTATION markers remain. Gates:
ruff, ty, and 96 tests across the pin, pre-flight, repair and tools suites.
