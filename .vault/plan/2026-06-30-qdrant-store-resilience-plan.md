---
tags:
  - '#plan'
  - '#qdrant-store-resilience'
date: '2026-06-30'
modified: '2026-06-30'
tier: L2
related:
  - '[[2026-06-30-qdrant-store-resilience-adr]]'
  - '[[2026-06-30-qdrant-store-resilience-research]]'
---

# `qdrant-store-resilience` plan

### Phase `P01` - Quarantine primitive

Move a corrupt collection directory aside to a reversible quarantine location, independent of Qdrant internals (QR2).

- [x] `P01.S01` - Add \_quarantine_collection that moves a collection directory into a timestamped quarantine sibling of collections; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.

### Phase `P02` - Corrupt-collection detection

Identify the offending collection from the captured startup tail by matching a real on-disk collection name against a failure marker, abstaining when none is found (QR1, QR4).

- [x] `P02.S02` - Add \_corrupt_collection_from_output that returns an on-disk collection name found in the failure tail or None; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.

### Phase `P03` - Bounded auto-quarantine-and-retry

Wire detection plus quarantine into the supervised start failure path with a bounded retry, on by default (QR3).

- [x] `P03.S03` - Wrap supervised start with a bounded detect-quarantine-retry loop, on by default, abstaining when no culprit is identified; `src/vaultspec_rag/qdrant_runtime/_supervise.py`.

### Phase `P04` - Operator escape-hatch verb

Add a server qdrant CLI verb to list collections and quarantine a named one, sharing the quarantine primitive (QR5).

- [x] `P04.S04` - Add a server qdrant quarantine CLI verb that lists collections and quarantines a named one; `src/vaultspec_rag/cli/_service_qdrant.py`.

### Phase `P05` - Tests

Real-behavior tests for the quarantine move, the detection parser, the bounded retry, and the CLI verb, under an isolated storage dir.

- [x] `P05.S05` - Add real-behavior tests for quarantine move, detection parser, bounded retry, and the CLI verb under an isolated storage dir; `src/vaultspec_rag/tests/test_qdrant_store_resilience.py`.

## Description

## Steps

## Parallelization

## Verification
