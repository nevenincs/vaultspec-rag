---
tags:
  - '#plan'
  - '#body-schema-provenance'
date: '2026-07-27'
modified: '2026-07-27'
tier: L2
related:
  - '[[2026-07-27-body-schema-provenance-adr]]'
  - '[[2026-07-27-body-schema-provenance-policy-research]]'
---
# `body-schema-provenance` plan

### Phase `P01` - Immutable contracts

Make body schemas immutable and stamp new documents.

- [x] `P01.S01` - Add immutable body-schema contracts and scaffold stamping; `src/vaultspec_core/builtins and src/vaultspec_core/vaultcore`.
- [x] `P01.S02` - Validate documents against attested schema provenance; `src/vaultspec_core/vaultcore/checks/body_sections.py and parser models`.

### Phase `P02` - Attest and verify corpus

Generate the reviewed legacy baseline and prove strict validation.

- [ ] `P02.S03` - Generate reviewed historical schema baseline; `.vaultspec/body-schema-baseline.json and migrations`.
- [ ] `P02.S04` - Prove restored corpus and new documents validate correctly; `checks tests and vault check body-sections`.

## Description

Evidence gap: the retained document body has no authored Description content beyond scaffold comments or placeholders.

## Steps

Evidence gap: the retained document body has no authored Steps content beyond scaffold comments or placeholders.

## Parallelization

Evidence gap: the retained document body has no authored Parallelization content beyond scaffold comments or placeholders.

## Verification

Evidence gap: the retained document body has no authored Verification content beyond scaffold comments or placeholders.
