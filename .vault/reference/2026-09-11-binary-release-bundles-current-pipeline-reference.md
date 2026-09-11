---
tags:
  - '#reference'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:8177457970598f2fd790063bbea1662f246b4a1870d783a8bac0d4b2cade16f7'
related:
  - "[[2026-09-11-binary-release-bundles-rag-port-research]]"
---

# `binary-release-bundles` reference: `RAG current binary release pipeline`

## Summary

The RAG release surface has one product, two executable entry points, and three declared build targets. The implementation seam is a post-finalization bundle layer: keep target-qualified names private in `tools/binaries/build_pyapp.py`, centralize public names and target policy in `tools/packaging/products.py`, and let workflows, channels, and documentation consume the target archive.

## Build and finalization

`tools/binaries/build_pyapp.py:79-103` defines the two binaries (`vaultspec-rag` and `vaultspec-search-mcp`), the `gpu,mcp` feature set, and the PyApp/Python inputs. `build_one` at `tools/binaries/build_pyapp.py:316-409` builds a target-qualified executable, copies it into the output directory, stamps the Windows icon or applies Unix execute permissions, checks the glibc floor, and writes the adjacent `.sha256` file. The finalization order is important: every byte-changing operation must complete before any digest is written.

The builder currently resolves the project from the published package channel and has no exact-wheel input. The release workflow therefore needs an explicit version-checked wheel handoff (or an equivalent same-run dependency) so the binary embeds the release commit’s package rather than racing PyPI availability. RAG has no `CPYTHON_VERSION` constant comparable to Core; its runtime contract is currently represented by `PYTHON_VERSION = "3.13"`, `PYAPP_VERSION = "0.29.0"`, and the project’s supported Python range in `pyproject.toml`.

## Product and target policy

`tools/packaging/products.py:18-152` is the shared product model used by the binary builder and package-channel generators. `VAULTSPEC_RAG` exposes the two commands, the `gpu,mcp` packaging assumptions, first-launch CUDA/runtime downloads, and the supported binary targets: Windows x86_64, Linux x86_64, and Linux aarch64. Darwin targets are represented by platform constants but are intentionally not supported by this product because the binary path requires NVIDIA CUDA.

The build matrix in `.github/workflows/binaries.yml:220-337` declares those same three targets. Linux x86_64 and aarch64 use pinned manylinux 2.28 environments; `tools/binaries/build_pyapp.py:203-214` enforces the corresponding glibc floor. A bundle completeness gate must derive its expected target set from this policy/matrix relationship, not from whichever artifacts happened to upload.

## Existing package channels

`tools/packaging/scoop.py:34-75` currently publishes two raw target-qualified executable URLs and maps those names to stable command names in the Scoop manifest. `tools/packaging/homebrew.py:39-245` does the equivalent with a primary executable and a resource executable, then renames both target-qualified files during installation. `tools/packaging/generate.py:40-156` requires a digest for every executable asset before generating channels, while `tools/packaging/validate.py:70-200` reconstructs raw asset names from the workflow matrix and validates channel references.

The bundle port should make those raw names an internal staging detail. Each supported target should expose one archive URL and one archive digest; extraction should yield stable `vaultspec-rag` and `vaultspec-search-mcp` command names. The generators and validators should retain their current target coverage, hash, version, pointer, and glibc-floor checks while changing the public asset unit from executable to archive.

## Windows metadata owner

`tools/binaries/windows_icon.py:1-263` owns PE resource editing and verification today, but only for `RT_ICON` and `RT_GROUP_ICON`. The bundle contract needs stable Windows file metadata as well, so this module is the natural owner for version-resource stamping and read-back verification. `tools/packaging/tests/test_windows_icon.py:1-100` already provides the focused resource-test boundary; the builder must preserve icon verification, add version verification, and perform both before the platform-floor check and checksum generation.

## Workflow and release surfaces

`.github/workflows/binaries.yml:350-499` builds one raw executable set per matrix target, uploads `dist-bin/`, aggregates the sidecar hashes, generates channels, and uploads binary assets to the GitHub Release. Its release verification currently checks for target substrings and can demote a release when expected binary assets are absent; it does not validate archive contents or enforce one complete archive per target.

`.github/workflows/publish.yml:132-200` independently builds and attaches the Python wheel and source distribution, while also merging its artifacts into `SHA256SUMS`. Both workflows can attach assets to the same release, so the bundle change must preserve the existing merge behavior and make the checksum aggregate include archives without clobbering entries produced by the other workflow. `.github/workflows/release-please.yml` explicitly dispatches both publication workflows because the release bot’s tag creation does not trigger tag workflows; that dispatch relationship must remain intact unless orchestration is deliberately redesigned.

`justfile:444-457` exposes `release-binaries` and `release-channels` as the local entry points. The bundle implementation should add a reproducible bundle recipe beside them so CI and local validation use the same command surface.

## Documentation boundary

`RELEASING.md:9-22` currently describes the Python/PyPI release path and the three release workflows, while `docs/installation.md` is the user-facing installation reference. The RAG bundle documentation belongs in those existing documents: explain direct-download archive names, stable extracted commands, manifest and checksum verification, supported targets, and the fact that first launch still needs a GPU-capable environment, network access, and CUDA runtime downloads. Do not describe the bundle as an offline/self-contained runtime.

## Sources

- Core accepted decision: `Y:/code/vaultspec-core-worktrees/artefacts/.vault/adr/2026-09-11-binary-release-bundles-adr.md`
- Core current-pipeline reference: `Y:/code/vaultspec-core-worktrees/artefacts/.vault/reference/2026-09-11-binary-release-bundles-current-pipeline-reference.md`
- Core implementation plan: `Y:/code/vaultspec-core-worktrees/artefacts/.vault/plan/2026-09-11-binary-release-bundles-plan.md`
- RAG builder and runtime channel: `tools/binaries/build_pyapp.py:66-409`, `tools/binaries/torch_channel.py:1-130`
- RAG packaging and channel surfaces: `tools/packaging/products.py:18-152`, `tools/packaging/scoop.py:34-75`, `tools/packaging/homebrew.py:39-245`, `tools/packaging/generate.py:40-156`, `tools/packaging/validate.py:70-200`
- RAG release workflows and package metadata: `.github/workflows/binaries.yml:220-729`, `.github/workflows/publish.yml:132-200`, `.github/workflows/release-please.yml`, `pyproject.toml:1-76`, `justfile:444-457`
