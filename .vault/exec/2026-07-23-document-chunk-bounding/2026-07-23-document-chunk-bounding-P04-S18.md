---
tags:
  - '#exec'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
body_hash: 'sha256:979cdfeee7dd97a320911ede5dcfc9668d1cc77834724338ad7cf633ee3c7a8d'
step_id: 'S18'
related:
  - "[[2026-07-23-document-chunk-bounding-plan]]"
---

# add a test asserting a unit above the token window yields multiple fragments rather than one truncated chunk

## Scope

- `src/vaultspec_rag/tests/test_chunk_worker_parity.py`

## Description

- Add `test_oversized_unit_is_split_into_bounded_fragments`: a unit above the derived budget yields multiple fragments, each within the budget, each carrying full provenance, with gapless in-order coverage of the original text.

## Outcome

The silent-truncation defect is demonstrated gone rather than relabelled: no fragment exceeds the budget and the fragments reconstruct the unit's content without a gap.

## Notes

Lives in `src/vaultspec_rag/tests/test_document_unit_bounding.py` (same module deviation as S09/S10).
