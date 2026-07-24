---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S01'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# implement the throwaway env-flag-gated donor-lookup prototype at the encode-seam caller (retrieve-by-id from one named donor namespace, content verify, adopt vectors, encode misses)

## Scope

- `src/vaultspec_rag/indexer/_streaming.py` (temporary patch`
- `not for landing)`

## Description

- Add throwaway env-gated helper `_prototype_adopt_donor_vectors` to `src/vaultspec_rag/indexer/_streaming.py`: reads `VAULTSPEC_RAG_REUSE_PROTOTYPE=<donor_prefix>`, maps the slice's chunks to deterministic Qdrant point ids (`VaultStore._stable_id` over chunk id / vault `point_key` / document id), batch `client.retrieve` from `<donor_prefix><suffix>` with vectors and the `content` payload field, verifies fetched payload content equals the expected chunk content byte-for-byte, adopts donor dense plus sparse vectors on verified hits, returns miss indices.
- Gate the single encode seam `_encode_slice_vector_fields` on the returned misses: hits skip the forward pass entirely; only miss chunks and their texts are GPU-encoded; a fully-hit slice performs zero forward passes.
- Wire the three seam callers (`encode_and_upsert_code_slice`, `encode_and_upsert_document_slice`, `_encode_and_upsert_vault_slice`) to pass `reuse_store`/`reuse_kind` (`code`/`document`/`vault`).
- Cumulative per-kind hit/total counters plus first/last lookup timestamps persist to the JSON path in `VAULTSPEC_RAG_REUSE_PROTOTYPE_STATS` after every slice.
- Any donor retrieve failure logs a warning and permanently disables lookups for the run (all-miss fallback), so the prototype can never fail an index job.

## Outcome

- Patch is ~130 lines, entirely inside `src/vaultspec_rag/indexer/_streaming.py`, flag-off path byte-identical to baseline (helper returns all-miss without touching chunk state when the env flag is unset).
- All donor lookups run before the GPU lock is taken, on the existing consumer thread; no new threads, no chunk-worker changes, no new torch imports.
- Functional micro-test against the live donor collection (`rea7120f40662_codebase_docs`, shared Qdrant server port 8765): exact-content point adopted dense(1024) + sparse(367) vectors; content-mutated point and absent point both reported as misses. Verified before any indexing run.

## Notes

- Measurement scaffolding only; reverted in step S03 of this phase. Never committed.
- Vault chunk point identity (`doc_id#c{ordinal}`) is not content-addressed, unlike code/document chunk ids; the per-point content verify is what makes vault reuse safe. Production design (W02) should keep the verify mandatory for all kinds.

## Closeout

The standalone throwaway measurement this prototype existed for was NOT carried
to a full fork run: maintaining a separate flag-gated patch under single-GPU
contention with the resident service was fragile, and the production off-switch
flag built in W02 is the same A/B lever with none of the throwaway maintenance.
The decision-grade fork numbers were therefore captured through the production
flag instead (see S02), which supersedes this prototype. The prototype patch
was never landed and no throwaway reuse code remains in the working tree
(confirmed in S03).
