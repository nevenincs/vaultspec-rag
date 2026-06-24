---
tags:
  - '#plan'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
tier: L2
related:
  - '[[2026-06-24-torch-dependency-group-adr]]'
---

# `torch-dependency-group` plan

### Phase `P01` - Group-target write path and selector

Add the --torch-group selector and a parameterised group write helper, default unchanged.

- [x] `P01.S01` - Add a --torch-group NAME install flag selecting a PEP 735 dependency-group surface for the managed torch direct-dependency, defaulting to dev when given without a value; `src/vaultspec_rag/cli/_install.py`.
- [x] `P01.S02` - Thread the group selector through install-run and the torch flow down to the ensure-direct-dep call without breaking the idempotent re-run path; `src/vaultspec_rag/commands/_torch_flow.py`.
- [x] `P01.S03` - Add a parameterised group-target write helper that creates the dependency-groups table and named array when absent and returns the dependency-groups location string; `src/vaultspec_rag/torch_config/_direct_dep.py`.

### Phase `P02` - Marker location-tracking and uninstall symmetry

Make the marker record the written surface and uninstall remove only from it, with legacy-true back-compat.

- [x] `P02.S04` - Promote the managed-torch-direct-dependency marker to record the written location, reading a legacy boolean true as the project-dependencies location; `src/vaultspec_rag/torch_config/_direct_dep.py`.
- [x] `P02.S05` - Make uninstall remove the managed torch dep from the marker-recorded surface only, preserving symmetric install and uninstall and never touching an unmarked user-declared torch; `src/vaultspec_rag/torch_config/_direct_dep.py`.
- [x] `P02.S06` - Warn and no-op on a re-run whose target differs from the recorded placement so torch is never silently migrated between surfaces; `src/vaultspec_rag/commands/_torch_flow.py`.

### Phase `P03` - Operator guidance

Warn when a group-placed pin would be inert unless the group is enabled for the resolve.

- [x] `P03.S07` - Warn when a group target is selected that the group must be enabled for the resolve for the cu130 source pin to apply, so a group-placed dep is never a silently inert pin; `src/vaultspec_rag/commands/_torch_flow.py`.

### Phase `P04` - Regression coverage

Prove group placement, marker/uninstall symmetry, legacy back-compat, and the unchanged default, with no mocks.

- [x] `P04.S08` - Add a no-mock test that a group target writes torch under the dependency-group and not project dependencies, with the cu130 index and sources block still written; `src/vaultspec_rag/tests/test_install_torch_config.py`.
- [x] `P04.S09` - Add a no-mock test that the marker records the group location and uninstall removes the group entry, and that a legacy true marker still removes from project dependencies; `src/vaultspec_rag/tests/test_install_torch_config.py`.
- [x] `P04.S10` - Add a no-mock test that the default no-flag path still writes project dependencies unchanged and a user-declared torch in a group is left untouched; `src/vaultspec_rag/tests/test_install_torch_config.py`.

## Description

Give `vaultspec-rag install` an optional PEP 735 dependency-group placement for the managed
CUDA torch direct-dependency, so a project that uses rag as dev-only tooling does not leak
torch into its published `Requires-Dist`, per the ADR. Phase P01 adds the `--torch-group`
selector, threads it through the install layers, and adds a parameterised group write helper
alongside the existing project-deps helper - the default (no flag) is unchanged. Phase P02 is
the load-bearing correctness work: promote the ownership marker from a bare boolean to a
location-bearing value (reading legacy `true` as the project-deps surface), make uninstall
remove only from the marker-recorded surface, and warn-and-no-op rather than silently migrate
on a changed target. Phase P03 warns when a group-placed pin would be inert unless the group
is enabled for the resolve. Phase P04 proves all of it against real tomlkit documents with no
mocks. Grounded in the ADR and its research; planning artifact only, ADR pending sign-off.

## Steps

## Parallelization

P01 lays the write path and selector that P02 and P03 build on, so it lands first. Within P01,
the CLI flag (S01), the threading (S02), and the write helper (S03) are a connected chain best
done together. P02's marker and uninstall changes (S04-S05) are tightly coupled and must be
reviewed as a pair to keep install/uninstall symmetric; the warn-and-no-op (S06) and the
inert-pin warning (P03.S07) are independent and can follow. P04's tests depend on the surfaces
they exercise, so they trail their respective phases. There is no other in-flight work on the
torch-config surface.

## Verification

The plan is complete when every Step is closed and all of the following hold:

- `vaultspec-rag install --torch-group <NAME>` writes `torch` under
  `[dependency-groups].<NAME>` and not `[project].dependencies`, with the cu130
  `[[tool.uv.index]]` and `[tool.uv.sources]` block still written.
- The ownership marker records the written location; uninstall removes the managed dep from
  that surface only, and a legacy boolean-`true` marker still removes from
  `[project].dependencies`.
- A re-run with a different target warns and no-ops rather than silently migrating; an unmarked
  user-declared torch is never touched.
- A group target prints a warning that the group must be enabled for the resolve for the cu130
  pin to apply.
- The default no-flag path still writes `[project].dependencies` unchanged; all assertions are
  proven against real tomlkit documents with no mocks, stubs, or skips; `ruff` and the type
  checker report zero violations.
