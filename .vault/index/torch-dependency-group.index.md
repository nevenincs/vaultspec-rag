---
generated: true
tags:
  - '#index'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - '[[2026-06-24-torch-dependency-group-P01-S01]]'
  - '[[2026-06-24-torch-dependency-group-P01-S02]]'
  - '[[2026-06-24-torch-dependency-group-P01-S03]]'
  - '[[2026-06-24-torch-dependency-group-P02-S04]]'
  - '[[2026-06-24-torch-dependency-group-P02-S05]]'
  - '[[2026-06-24-torch-dependency-group-P02-S06]]'
  - '[[2026-06-24-torch-dependency-group-P03-S07]]'
  - '[[2026-06-24-torch-dependency-group-P04-S08]]'
  - '[[2026-06-24-torch-dependency-group-P04-S09]]'
  - '[[2026-06-24-torch-dependency-group-P04-S10]]'
  - '[[2026-06-24-torch-dependency-group-adr]]'
  - '[[2026-06-24-torch-dependency-group-plan]]'
  - '[[2026-06-24-torch-dependency-group-research]]'
---

# `torch-dependency-group` feature index

Auto-generated index of all documents tagged with `#torch-dependency-group`.

## Documents

### adr

- `2026-06-24-torch-dependency-group-adr` - `torch-dependency-group` adr: `optional dependency-group placement for the managed torch direct-dependency` | (**status:** `accepted`)

### exec

- `2026-06-24-torch-dependency-group-P01-S01` - Add a --torch-group NAME install flag selecting a PEP 735 dependency-group surface for the managed torch direct-dependency, defaulting to dev when given without a value
- `2026-06-24-torch-dependency-group-P01-S02` - Thread the group selector through install-run and the torch flow down to the ensure-direct-dep call without breaking the idempotent re-run path
- `2026-06-24-torch-dependency-group-P01-S03` - Add a parameterised group-target write helper that creates the dependency-groups table and named array when absent and returns the dependency-groups location string
- `2026-06-24-torch-dependency-group-P02-S04` - Promote the managed-torch-direct-dependency marker to record the written location, reading a legacy boolean true as the project-dependencies location
- `2026-06-24-torch-dependency-group-P02-S05` - Make uninstall remove the managed torch dep from the marker-recorded surface only, preserving symmetric install and uninstall and never touching an unmarked user-declared torch
- `2026-06-24-torch-dependency-group-P02-S06` - Warn and no-op on a re-run whose target differs from the recorded placement so torch is never silently migrated between surfaces
- `2026-06-24-torch-dependency-group-P03-S07` - Warn when a group target is selected that the group must be enabled for the resolve for the cu130 source pin to apply, so a group-placed dep is never a silently inert pin
- `2026-06-24-torch-dependency-group-P04-S08` - Add a no-mock test that a group target writes torch under the dependency-group and not project dependencies, with the cu130 index and sources block still written
- `2026-06-24-torch-dependency-group-P04-S09` - Add a no-mock test that the marker records the group location and uninstall removes the group entry, and that a legacy true marker still removes from project dependencies
- `2026-06-24-torch-dependency-group-P04-S10` - Add a no-mock test that the default no-flag path still writes project dependencies unchanged and a user-declared torch in a group is left untouched

### plan

- `2026-06-24-torch-dependency-group-plan` - `torch-dependency-group` plan

### research

- `2026-06-24-torch-dependency-group-research` - `torch-dependency-group` research: `placing the managed torch direct-dependency in a dependency group`
