---
tags:
  - '#exec'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
body_hash: 'sha256:f06e618a6ebff302a0b10979e55ac36cb8a9f675248e9f695ae89941bea891df'
step_id: 'S10'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# Add a reindex-parity integration test asserting points serialize byte-for-byte unchanged

## Scope

- `src/vaultspec_rag/tests/integration/test_store_schema_parity.py`

## Description

- Authored `test_store_schema_parity.py` asserting each builder produces the exact golden payload dict for a constructed dataclass: the vault document (10 fields), the vault chunk at a non-zero ordinal (no doc_content), the ordinal-0 chunk (carries doc_content), the ordinal-0 chunk with no doc_content (omits it), and the code chunk (17 fields).
- Marked the test `unit` (pure: no Qdrant, no GPU, no network) so it runs in the CI gate.

## Outcome

The shape-preserving guarantee is regression-guarded: a field added/removed/renamed against the frozen golden shape fails this test. 6 parity tests pass; the full 1136-test unit suite is unchanged.

## Notes

Realised as a unit test over the pure builders rather than a live-store round trip, because the CI gate runs `pytest -m unit` only; the live-collection check is the P04 drift test (S16).
