---
tags:
  - '#adr'
  - '#sparseencode'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:e6ab7aa035aeed15c08044921b40fcb87501c126bf24880e628a45b6536fcb0e'
related:
  - "[[2026-09-30-sparseencode-research]]"
  - "[[2026-03-06-gpu-only-rag-stack-adr]]"
  - "[[2026-06-26-storage-schema-contract-adr]]"
  - "[[2026-09-26-gpu-single-owner-adr]]"
  - "[[2026-07-29-encode-batch-adaptivity-adr]]"
  - '[[2026-07-25-storage-conformance-adr]]'
---

# `sparseencode` adr: `Pinned ModernBERT sparse encoder and anonymous model acquisition` | (**status:** `accepted`)

## Problem Statement

The sparse dependency upgrade changes the tokenizer vocabulary and learned weights, requiring coordinated inference, index compatibility, provisioning and documentation changes. The user requested replacement with the new ModernBERT model, removal of the previous model's authentication support and references, performance optimization, and a minor package version increment.

## Considerations

`2026-09-30-sparseencode-research` establishes the public model contract and the upstream Sentence Transformers loader's lost-kwargs behavior. Existing storage identity already compares model IDs; the storage shape version is distinct from model identity.

## Considered options

- Use the published SparseEncoder module directly: concise, but its loader drops revision, offline and precision arguments and bundles preprocessing inside encoding.
- Use a canonical adapter around the pinned upstream Transformers model: chosen because it preserves specialized pooling while giving the project control over loading, preprocessing, forward locking and conversion.
- Reconstruct generic masked-language-model sparse pooling: rejected because it discards the learned representation contract.

## Constraints

The public model is `Linkup-Platform/linkup-sparseup-embed-v1`, revision `08314498d4f6a3a205b930ab9f27001404ea94b8`. Trust only that pinned implementation for the default model; use safetensors. Preserve upstream query/document preprocessing, lengths and vocabulary folding. All model acquisition and operator guidance use public access, with the previous authentication feature removed entirely. Keep GPU ownership/admission and one dedicated consumer; preprocessing and result conversion remain outside the forward lock.

Existing model identity must refuse mixed old/new vectors and drive a full rebuild through established publication machinery. Do not destroy the operator's live indexes during development. A model-only change does not bump the storage wire-shape version.

This ruling refines the sparse-model and dependency subsections of `2026-03-06-gpu-only-rag-stack-adr`, and retires the authentication-specific guidance in `2026-06-09-operability-hardening-adr` and relevant GPU-runner/provisioning records. Their unrelated commitments remain authoritative. The user's explicit reference-removal instruction authorizes removal of obsolete model/authentication mentions from historical records as maintenance.

The sparse-model mismatch case is a scoped refinement of `2026-07-25-storage-conformance-adr` D4: reads and writes against a collection stamped with a different sparse model refuse with a rebuild remedy. Matching-geometry dense-model disagreement continues to degrade under that ruling. Read-only catalog/administrative access and explicit rebuild remain available for recovery.

## Implementation

We will replace the sparse loader and encode seam with one adapter around the reviewed upstream model, share its profile across configuration and provisioning, raise compatible GPU dependency floors, and publish version `0.6.0`. Reuse the existing bucket planner, adaptive memory ceiling and progress hooks. Use pooled batch output and vectorized CPU sparse conversion. Validate attention/precision choices and throughput on real admitted GPU runs before claiming an improvement; these tuning choices remain implementation hypotheses.

Authorization: the user's 2026-09-30 request explicitly directs the breaking replacement, removal, optimization and minor version bump. Acceptance authorizes implementation of this scope.

## Rationale

The pinned upstream model preserves the trained representation while the adapter avoids uncontrolled nested loading. Existing model identity supplies the comparison input, but its current degradation policy still permits incompatible sparse scoring and writes. Refusing sparse-model mismatches at the established ensure seam protects the changed vocabulary without inventing a migration engine or changing wire geometry; dense-model mismatch continues to follow its existing degradation policy.

## Consequences

All domains containing sparse vectors need rebuilding under the new model. Provisioning no longer depends on gated-model credentials. Pinned remote Python code is an explicit dependency and must be reviewed again before any revision change. Hardware performance and reduced-precision accuracy require measured evidence; no speedup follows merely from choosing ModernBERT.
