---
generated: true
tags:
  - '#index'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:81c4f3b72f5bfbe23b2f1de6142186752aaece1ec6c860dd0c1b50c96c0b4333'
related:
  - '[[2026-09-11-binary-release-bundles-P01-S01]]'
  - '[[2026-09-11-binary-release-bundles-P01-S02]]'
  - '[[2026-09-11-binary-release-bundles-P01-S03]]'
  - '[[2026-09-11-binary-release-bundles-P01-S04]]'
  - '[[2026-09-11-binary-release-bundles-P01-S05]]'
  - '[[2026-09-11-binary-release-bundles-P01-S06]]'
  - '[[2026-09-11-binary-release-bundles-P01-summary]]'
  - '[[2026-09-11-binary-release-bundles-P02-S07]]'
  - '[[2026-09-11-binary-release-bundles-P02-S08]]'
  - '[[2026-09-11-binary-release-bundles-P02-S09]]'
  - '[[2026-09-11-binary-release-bundles-P02-S10]]'
  - '[[2026-09-11-binary-release-bundles-adr]]'
  - '[[2026-09-11-binary-release-bundles-audit]]'
  - '[[2026-09-11-binary-release-bundles-current-pipeline-reference]]'
  - '[[2026-09-11-binary-release-bundles-plan]]'
  - '[[2026-09-11-binary-release-bundles-rag-port-research]]'
---

# `binary-release-bundles` feature index

Auto-generated index of all documents tagged with `#binary-release-bundles`.

## Documents

### adr

- `2026-09-11-binary-release-bundles-adr` - `binary-release-bundles` adr: `RAG binary release bundles` | (**status:** `accepted`)

### audit

- `2026-09-11-binary-release-bundles-audit` - `binary-release-bundles` audit: `P01 through P02.S10 implementation review`

### exec

- `2026-09-11-binary-release-bundles-P01-S01` - Centralize RAG's supported targets, stable executable names, private staging names, archive suffixes, and release metadata
- `2026-09-11-binary-release-bundles-P01-S02` - Implement deterministic per-target ZIP and TAR.GZ bundle creation with stable executables, manifest, license, usage material, and checksum sidecars
- `2026-09-11-binary-release-bundles-P01-S03` - Add Windows PE version-resource stamping and read-back verification while retaining icon resource verification
- `2026-09-11-binary-release-bundles-P01-S04` - Order binary finalization and bundle inputs so icon, version metadata, permissions, platform-floor checks, and all digests complete before release archives are emitted
- `2026-09-11-binary-release-bundles-P01-S05` - Prove deterministic archive bytes, exact member layout, manifest hashes and metadata, target naming, and refusal of missing or malformed inputs
- `2026-09-11-binary-release-bundles-P01-S06` - Prove Windows icon and version resources, finalization ordering, platform-floor behavior, and checksum timing with fixture and real PE coverage
- `2026-09-11-binary-release-bundles-P01-summary` - `binary-release-bundles` `P01` summary
- `2026-09-11-binary-release-bundles-P02-S07` - Accept a version-checked release wheel as the PyApp input while preserving RAG's pinned CUDA torch bootstrap channel
- `2026-09-11-binary-release-bundles-P02-S08` - Expose reproducible local commands for exact-wheel binary builds, target bundle creation, archive validation, and release checksum generation
- `2026-09-11-binary-release-bundles-P02-S09` - Build the exact release wheel, bundle each matrix target, validate archive contents, and upload only validated public archives and sidecars
- `2026-09-11-binary-release-bundles-P02-S10` - Gate release asset publication and stable/latest channel promotion on the complete declared target archive set and reject raw executable publication

### plan

- `2026-09-11-binary-release-bundles-plan` - `binary-release-bundles` plan

### reference

- `2026-09-11-binary-release-bundles-current-pipeline-reference` - `binary-release-bundles` reference: `RAG current binary release pipeline`

### research

- `2026-09-11-binary-release-bundles-rag-port-research` - `binary-release-bundles` research: `RAG binary release bundle port`
