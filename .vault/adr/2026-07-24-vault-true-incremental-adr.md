---
tags:
  - '#adr'
  - '#vault-true-incremental'
date: '2026-07-24'
modified: '2026-07-27'
related:
  - "[[2026-07-24-index-throughput-research]]"
  - "[[2026-07-24-index-throughput-adr]]"
  - "[[2026-07-24-worktree-index-reuse-adr]]"
  - '[[2026-07-27-vault-true-incremental-grounding-research]]'
---

# `vault-true-incremental` adr: `frontmatter-volatility-agnostic vault change detection` | (**status:** `accepted`)

## Problem Statement

Vault incremental indexing re-embeds documents whose meaning never changed. Change detection digests the raw whole file - `_hash_documents` and `_save_index_metadata` blake2b the file bytes including frontmatter (`src/vaultspec_rag/indexer/_vault_indexer.py:719-723,1044-1048`) - so the CLI-maintained `modified:` stamp, refreshed by every mutating vault verb and by the vault check fixer, flips the digest on a byte-identical body. Measured consequence: incremental vault jobs spending 796-1,516 s to commit +0 to +6 chunks (`2026-07-24-index-throughput-research`). A second amplifier: any watcher attempt failure escalates the next incremental to an unscoped full-corpus pass (`src/vaultspec_rag/server/watcher_retry.py:255` consumed at `src/vaultspec_rag/server/watcher.py:1648-1658`), turning transient failures into full re-embed cycles. What invalidates a vector is a storage/index contract, so the fix is decided here rather than patched ad hoc.

## Considerations

- The chunk layer already separates concerns: frontmatter parses into payload, and the content fingerprint covers the body - only the change-detection layer conflates them (research locators above).
- A GPU re-encode is orders of magnitude costlier than a payload update; metadata-only edits are the common case in a CLI-stamped vault.
- Encode-seam vector reuse (accepted separately) reduces the cost of a wrong re-embed decision but must not be used to excuse one - correct classification is upstream of reuse.
- Guard tests must prove they can fail per project rule; a fingerprint change is exactly the silent-degradation class that demands mutation-proven tests.
- Escalation-to-unscoped exists for real convergence reasons (a failed attempt leaves unknown state); the fix must preserve convergence while removing the re-embed penalty.

## Considered options

- Keep raw-file digests and rely on vector reuse to absorb waste: leaves parse cost, ledger churn, and job-time inflation; classification stays wrong. Rejected.
- Ignore all frontmatter in the digest: breaks refresh of indexed metadata (tags/related/title would go stale in payloads). Rejected.
- CHOSEN: split the fingerprint - hash(normalized body) plus hash(indexed-frontmatter subset), explicitly excluding the volatile `modified:` stamp and pure canonicalization/whitespace churn; body change re-embeds, indexed-metadata change performs a payload-only update with vectors untouched, volatile-stamp change classifies as unchanged.
- CHOSEN companion: watcher failure escalation becomes a convergence pass - the unscoped sweep re-classifies via the split fingerprint and converges by hash comparison and payload updates, never a blanket re-embed of unchanged bodies.

## Constraints

- The indexed-frontmatter subset must be defined once, next to the payload schema that consumes it, so the fingerprint and the payload can never drift apart silently.
- Fingerprint scheme change invalidates existing sidecar hashes exactly once: the first run under the new scheme re-classifies every document (payload/hash refresh), which must not be a full re-embed - vectors refresh only where the body hash actually differs (vector reuse from the root's own collection covers the migration).
- Backend-neutral: pure CPU classification; no torch, no new lifecycle or storage surface; sidecar schema evolution follows the existing meta-versioning conventions.
- Implementation is sequenced after the in-flight throughput plan lands (shared files); the decision binds now.

## Implementation

Change detection computes two digests per vault document: the normalized body (frontmatter block stripped, newline-normalized - matching the chunker's own normalization) and the canonicalized indexed-frontmatter subset (the fields that enter point payloads; the volatile stamp excluded by construction). The sidecar stores both. Classification: body-hash delta -> re-chunk and re-embed the document; subset-hash-only delta -> rebuild payloads for the document's existing points and upsert payload-only, vectors untouched; neither -> unchanged, zero work. The watcher's unscoped escalation runs the same classifier over the full corpus - convergence without blanket re-embeds.

Guard tests, each mutation-proven red-then-green: bump only `modified:` -> classified unchanged with zero encodes (weaken the fingerprint back to raw-file digest -> the zero-encode assertion goes red); tags-only change -> payload updated, zero encodes (route metadata changes into the re-embed branch -> red); body edit -> re-embed occurs (drop the body hash from the fingerprint -> red).

## Rationale

The split fingerprint aligns the change-detection layer with the separation the chunk layer already implements, eliminating the measured +0-chunk re-embed class at its root instead of compensating downstream, and it converts the failure-amplification loop (transient failure -> unscoped re-embed -> more contention) into a cheap convergence sweep. Alternatives either keep wrong classification (raw digest) or break metadata freshness (ignore-all-frontmatter). Grounded end-to-end in `2026-07-24-index-throughput-research`.

## Consequences

- Metadata-churn workflows (stamp refreshes, tag curation, link maintenance) stop costing GPU time; incremental vault time for such edits drops from hundreds of seconds to payload-update time.
- One-time migration cost on first run under the new scheme (full re-classification, vectors preserved where bodies match).
- The indexed-subset definition becomes a contract: adding a frontmatter field to payloads must add it to the subset hash, enforced by co-location and test.
- Unscoped escalation keeps its convergence guarantee with its penalty removed; watcher failure handling needs no semantic change.
