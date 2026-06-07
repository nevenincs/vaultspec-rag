---
tags:
  - '#plan'
  - '#cli-tree-overhaul'
date: '2026-06-06'
tier: L3
related:
  - '[[2026-06-06-cli-tree-overhaul-adr]]'
  - '[[2026-06-06-cli-tree-overhaul-research]]'
---

<!-- RETIRED: S01, S02, S03, S04, S05, S06, S07, S08, S09, S10, S11, S12, S13, S14, S15, S16, S17, S18, S19, S20, S21, S22, S23, S24, S25, S26, S27, S28, S29, S30, S31, S32, S33, S34, S35 -->

# `cli-tree-overhaul` `Complete CLI Tree Overhaul` plan

## Wave `W01` - Core Overhaul

Update existing targets to pwsh

### Phase `W01.P01` - Initial CLI Tree Overhaul

Convert justfile to pwsh and implement strict pipelines

- [x] `W01.P01.S36` - Set pwsh shell and VIRTUAL_ENV variables; `justfile`.
- [x] `W01.P01.S37` - Overhaul default target; `justfile`.
- [x] `W01.P01.S38` - Overhaul prod target; `justfile`.
- [x] `W01.P01.S39` - Overhaul dev deps target; `justfile`.
- [x] `W01.P01.S40` - Overhaul dev lint target; `justfile`.
- [x] `W01.P01.S41` - Overhaul dev fix target; `justfile`.
- [x] `W01.P01.S42` - Overhaul dev audit target; `justfile`.
- [x] `W01.P01.S43` - Overhaul dev test target; `justfile`.
- [x] `W01.P01.S44` - Overhaul dev build target; `justfile`.
- [x] `W01.P01.S45` - Overhaul dev precommit target; `justfile`.
- [x] `W01.P01.S46` - Overhaul ci target; `justfile`.

## Wave `W02` - Code Quality Rules

Enforce cognitive complexity limits and relative imports using Ruff

### Phase `W02.P02` - Ruff Config Overhaul

Configure pyproject.toml and justfile for strict linting

- [x] `W02.P02.S47` - Add extra dev dependencies; `Add xenon and cognitive-complexity dev tools`.
- [x] `W02.P02.S48` - Configure Ruff; `Enforce TID rules for imports and C901 for complexity`.
- [x] `W02.P02.S49` - Update justfile; `Add dev complexity check target and integrate into ci`.

## Wave `W03` - Remediation of Unshielded Codebase

Resolve all newly surfaced linting and integration test failures resulting from the removal of codebase test skips and noqa annotations.

### Phase `W03.P03` - Linting Remediation

Fix all strict linting failures, particularly ARG unused arguments exposed in tests after unshielding.

- [x] `W03.P03.S50` - Fix unused test arguments (ARG001, ARG002, etc.); `src/vaultspec_rag/tests/`.

### Phase `W03.P04` - Integration Test Remediation

Resolve the 23 failing integration tests exposed by the removal of test skips.

- [x] `W03.P04.S51` - Fix failing CLI Status and Index tests; `test_cli_integration.py`.
- [x] `W03.P04.S52` - Fix Codebase Search and GPU tests; `test_codebase_integration.py, test_gpu_pipeline_integration.py`.
- [x] `W03.P04.S53` - Fix failing ADR Regression tests; `test_adr_regression.py`.
- [x] `W03.P04.S54` - Fix failing Fast Path and Torch Config tests; `test_cli.py, test_install_torch_config.py`.

### Phase `W03.P05` - Type Safety and Metadata Remediation

Resolve the 14 Pyright type errors introduced during cognitive complexity refactoring and append missing step_id metadata to execution records.

- [x] `W03.P05.S55` - Fix Pyright type errors; `src/`.
- [x] `W03.P05.S56` - Append missing step_id frontmatter to execution records; `.vault/exec/`.

### Phase `W03.P06` - Regression Remediation

Fix 10 test failures introduced during Pyright type safety remediations in P05.

- [x] `W03.P06.S57` - Fix 10 test regressions; `src/`.

## Description

## Steps

## Parallelization

## Verification
