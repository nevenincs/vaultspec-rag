---
tags:
  - '#adr'
  - '#binary-release-bundles'
date: '2026-09-11'
modified: '2026-09-11'
body_schema: 'body-v2'
body_hash: 'sha256:09841b8e077b1016cd0fb77f6ad2db9d7b37d0c360ad7039bee964ead5f594aa'
related:
  - "[[2026-09-11-binary-release-bundles-rag-port-research]]"
  - "[[2026-09-11-binary-release-bundles-current-pipeline-reference]]"
  - '[[2026-04-01-cicl-pipeline-adr]]'
---

# `binary-release-bundles` adr: `RAG binary release bundles` | (**status:** `accepted`)

## Problem Statement

RAG needs a single public contract for standalone binary downloads and package channels. The current release surface exposes target-qualified executables while channel definitions separately reconstruct stable command names, and Python distribution artifacts are attached through a parallel workflow. This port adopts the accepted Core bundle direction while making the contract explicit for RAG's GPU-oriented runtime and target set. Grounding: `2026-09-11-binary-release-bundles-rag-port-research`, `2026-09-11-binary-release-bundles-current-pipeline-reference`.

## Considerations

- RAG has two commands, three supported binary targets, and first-launch CUDA/network requirements; the public artifact must describe those constraints: `2026-09-11-binary-release-bundles-rag-port-research`.
- Existing channel generators and validators are organized around one digest per executable and must converge on one public artifact per target: `2026-09-11-binary-release-bundles-current-pipeline-reference`.
- Binary and Python publication are separate release workflows that merge a shared checksum aggregate; publication must remain race-safe and complete-target aware: `2026-09-11-binary-release-bundles-current-pipeline-reference`.
- Windows icon stamping already happens before checksums, so version-resource metadata must join that finalization boundary rather than become a later mutation: `2026-09-11-binary-release-bundles-rag-port-research`.

## Considered options

- **One versioned archive per target with stable inner executables - chosen.** It gives direct downloads and package channels one immutable artifact unit while preserving the two RAG commands after extraction.
- **Continue publishing raw target-qualified executables - rejected.** It keeps the current build surface but leaves naming, metadata, and integrity semantics split across channels and direct-download consumers.
- **One archive for all targets - rejected.** It couples unrelated platform payloads, weakens target-specific installation, and makes the CUDA-oriented support matrix less precise.
- **One archive per executable and target - rejected.** It mirrors the current internal layout and requires users and channels to coordinate multiple downloads for one product installation.

## Constraints

- The public bundle unit is one versioned archive per RAG target: ZIP on Windows and TAR.GZ on Unix. The archive contains stable `vaultspec-rag` and `vaultspec-search-mcp` executables, generated `manifest.json`, license material, and RAG usage material.
- The manifest carries schema, product/version/target, executable roles, sizes and hashes, source revision, runtime/build versions, and platform-floor metadata. It does not hash the enclosing archive; `SHA256SUMS` carries the completed top-level artifact digest.
- Stable/latest may be published only when every target declared by the RAG binary matrix has a validated bundle. A missing, malformed, or incomplete target set must fail or demote the release rather than silently publish a partial stable surface.
- Raw target-qualified names are staging details. Direct downloads and Scoop/Homebrew consume one archive and its digest per target; extraction yields stable command names.
- Bundle metadata is descriptive, not an offline-runtime promise. The manifest and usage material must state RAG's GPU, network, CUDA-runtime, and supported-target requirements.
- Every byte-changing finalization operation, including Windows icon and version-resource stamping and Unix permissions, completes before per-file or top-level checksums are written.
- The binary build must consume a version-checked wheel built from the release source (or an equivalent same-run artifact handoff), so binary contents do not depend on a race with PyPI publication. The existing Python release path remains responsible for publishing the wheel and source distribution.
- The existing `2026-04-01-cicl-pipeline-adr` governs the established CI/release/PyPI automation. Its explicit release dispatch and checksum merge behavior are stable parent constraints for this extension; this ADR does not replace them.
- Archive creation should use the standard library and the existing pinned build environment. No runtime or application code may depend on `.vault` documents or development-only release metadata.

## Implementation

The product model becomes the single source for supported targets, stable executable names, bundle names, archive suffixes, and release metadata. A packaging layer stages the finalized binaries, emits deterministic target archives and their manifest, and writes a checksum sidecar only after validating required members. The existing binary builder delegates Windows PE version metadata to the resource module and keeps icon, permissions, platform-floor, and digest finalization ordered.

The binary workflow builds or receives the exact wheel, creates and validates one bundle for each matrix target, uploads only validated public archives plus the shared checksum aggregate, and gates the stable/latest channel on complete target coverage. The Python publication workflow continues to attach wheel and source artifacts and merges the same aggregate without overwriting entries. Scoop/Homebrew generation and validation consume archive names and digests, while the installation and release documents explain the extraction and runtime contract. Detailed source ownership is recorded in `2026-09-11-binary-release-bundles-current-pipeline-reference`.

## Rationale

Per-target archives provide the smallest stable public boundary that serves direct downloads, Scoop, and Homebrew without forcing those consumers to reproduce staging-name logic. Stable inner names make extraction predictable, while the manifest and top-level checksum preserve inspectable integrity without pretending the GPU runtime is self-contained. This keeps the Core contract intact and addresses the RAG-specific split workflows, CUDA/network behavior, and three-target completeness requirement identified in `2026-09-11-binary-release-bundles-rag-port-research` and `2026-09-11-binary-release-bundles-current-pipeline-reference`.

## Consequences

Direct-download users receive a coherent, versioned artifact and package channels no longer need to publish two independent binary assets per target. Release validation becomes stronger because archive contents, metadata, and target completeness are checked before a stable pointer moves.

The release pipeline gains a bundle build and an exact-wheel handoff, and the aarch64 matrix leg becomes part of the hard stable-release contract. The archive format and manifest schema become compatibility surfaces that require deliberate evolution. The bundle remains dependent on GPU hardware, network access, and CUDA runtime acquisition at first launch, so documentation and verification must keep that limitation visible.
