---
tags:
  - '#plan'
  - '#binary-release-bundles'
date: '2026-09-11'
tier: L2
related:
  - '[[2026-09-11-binary-release-bundles-adr]]'
  - '[[2026-09-11-binary-release-bundles-rag-port-research]]'
  - '[[2026-09-11-binary-release-bundles-current-pipeline-reference]]'
modified: '2026-09-11'
body_schema: body-v2
body_hash: 'sha256:e0285ac33635cca1e774be16fed68b25ecb1dcc88c44b967457e7cf6ea1cf62c'
---

# `binary-release-bundles` plan

Publish one validated, versioned binary archive per supported RAG target and make every release consumer use that same artifact contract.

## Description

This plan executes the accepted RAG port in `2026-09-11-binary-release-bundles-adr`, grounded by `2026-09-11-binary-release-bundles-rag-port-research` and `2026-09-11-binary-release-bundles-current-pipeline-reference`. Phase P01 establishes deterministic archives, stable inner command names, generated metadata, and finalization proof. Phase P02 feeds binaries from the exact release input, publishes bundles alongside Python artifacts, and blocks stable/latest on complete target coverage. Phase P03 moves Scoop and Homebrew to the archive boundary and documents direct installation and maintainer recovery.

## Steps

### Phase `P01` - define the RAG bundle contract

Centralize the RAG product contract, finalize executable metadata, and prove deterministic target archives before workflow publication depends on them.

- [x] `P01.S01` - Centralize RAG's supported targets, stable executable names, private staging names, archive suffixes, and release metadata; `tools/packaging/products.py`.
- [x] `P01.S02` - Implement deterministic per-target ZIP and TAR.GZ bundle creation with stable executables, manifest, license, usage material, and checksum sidecars; `tools/packaging/bundles.py`.
- [x] `P01.S03` - Add Windows PE version-resource stamping and read-back verification while retaining icon resource verification; `tools/binaries/windows_icon.py`.
- [x] `P01.S04` - Order binary finalization and bundle inputs so icon, version metadata, permissions, platform-floor checks, and all digests complete before release archives are emitted; `tools/binaries/build_pyapp.py`.
- [x] `P01.S05` - Prove deterministic archive bytes, exact member layout, manifest hashes and metadata, target naming, and refusal of missing or malformed inputs; `tools/packaging/tests`.
- [x] `P01.S06` - Prove Windows icon and version resources, finalization ordering, platform-floor behavior, and checksum timing with fixture and real PE coverage; `tools/binaries/tests`.

### Phase `P02` - publish complete validated release artifacts

Build bundles from the exact release inputs, publish them alongside Python artifacts, and gate stable/latest pointers on complete validated target coverage.

- [x] `P02.S07` - Accept a version-checked release wheel as the PyApp input while preserving RAG's pinned CUDA torch bootstrap channel; `tools/binaries/build_pyapp.py`.
- [x] `P02.S08` - Expose reproducible local commands for exact-wheel binary builds, target bundle creation, archive validation, and release checksum generation; `justfile`.
- [x] `P02.S09` - Build the exact release wheel, bundle each matrix target, validate archive contents, and upload only validated public archives and sidecars; `.github/workflows/binaries.yml`.
- [x] `P02.S10` - Gate release asset publication and stable/latest channel promotion on the complete declared target archive set and reject raw executable publication; `.github/workflows/binaries.yml`.
- [x] `P02.S11` - Merge Python wheel and source artifacts with binary bundle digests and assets without clobbering concurrent release checksums; `.github/workflows/publish.yml`.
- [x] `P02.S12` - Coordinate explicit release-tag dispatch so Python and binary workflows use the same tag and neither partial workflow advances stable/latest; `.github/workflows/release-please.yml`.

### Phase `P03` - converge package channels and user guidance

Make Scoop and Homebrew consume the archive contract and document installation, verification, runtime prerequisites, and release recovery.

- [ ] `P03.S13` - Generate and validate Scoop and Homebrew channels from one archive URL and digest per target while preserving stable extracted command names and glibc caveats; `tools/packaging`.
- [ ] `P03.S14` - Update channel, checksum, pointer, target-coverage, and archive-contract tests for bundle assets and failure cases; `tools/packaging/tests`.
- [ ] `P03.S15` - Document direct-download archive layout, supported targets, manifest and checksum verification, and GPU/network/CUDA first-launch requirements; `docs/installation.md`.
- [ ] `P03.S16` - Document maintainer bundle publication, complete-target gating, checksum reconciliation, and release recovery; `RELEASING.md`.

## Parallelization

P01 is the hard prerequisite for the publication work. Within P01, product naming and the bundle builder can proceed in parallel with Windows resource work; the finalization wiring follows both, and the focused tests follow their respective implementations. P02.S07 and P02.S08 can proceed once the P01 contract is settled. P02.S09 and P02.S10 are ordered within the binary workflow; P02.S11 and P02.S12 can be developed in parallel but must be verified together against the shared release asset behavior. P03 follows the published archive contract; channel implementation and documentation can proceed in parallel after P02, with P03.S14 following channel changes.

## Verification

- Every supported target produces exactly one deterministic archive with stable command names, required license/usage members, a schema-valid manifest, and a matching top-level checksum entry.
- Archive tests prove member hashes, metadata, reproducibility, input refusal, and platform-specific formats; Windows tests prove icon and version-resource read-back before digest generation.
- The binary workflow consumes a version-checked release wheel, uploads no raw executable as a public release asset, and refuses or demotes stable/latest when any declared target archive is absent or invalid.
- Python wheel and source-distribution publication preserve binary bundle assets and merge `SHA256SUMS` entries without clobbering either workflow's completed artifacts.
- Scoop and Homebrew manifests reference one archive URL and digest per target, extract the two stable commands, and retain target and glibc-floor validation.
- Installation and release documentation state checksum/manifest verification, supported targets, GPU/network/CUDA first-launch requirements, and complete-target recovery behavior.
- Focused packaging and workflow-contract tests, repository gates, full vault checks, and formal code review pass before all plan Steps are closed.
