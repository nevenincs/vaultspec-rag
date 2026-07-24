---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S09'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# implement the encode-seam read-through: per-point payload-content verify, dense plus sparse adoption on verified hits, GPU encode of misses only, every donor lookup outside the GPU lock on the existing consumer thread

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- Add `src/vaultspec_rag/indexer/_reuse.py`: `DonorReuseContext` (store handle, ranked donor collections, stats), `ReuseStats`, `_chunk_point_identity` (per-kind string id + expected payload content mirroring upsert exactly: code `chunk.id`/`content`, vault `point_key`/`text`, document `chunk.id`/`payload.content`), and `resolve_donor_reuse` (knob check, manifest discovery, all eligibility gates, `supports_donor_reads` filter; every failure degrades to no-donors).
- Intercept at the single seam `_encode_slice_vector_fields` in `src/vaultspec_rag/indexer/_streaming.py`: an optional `reuse` parameter (default `None`, so every existing call site is byte-identical baseline) adopts verified donor vectors before any encode, then sub-slices chunks and texts to the misses with one shared hit mask under `zip(..., strict=True)`; an all-hit slice returns before any forward call and never touches the GPU. All three kinds route through this one seam.
- Verify per point: donor payload `content` must be a string equal byte-for-byte to the chunk content this run would store; when the run writes sparse vectors the donor point must carry one. Anything else - including a donor read exception - is a miss for the ordinary encode. Payloads are always rebuilt locally; only vectors are adopted.
- Thread the context once per run: `CodebaseIndexer` resolves it at `_pipeline_chunk_and_embed` entry (both full and incremental funnel through it) with the run's code content epoch, resets state at both public entrypoints, and the consumer passes it per slice; `VaultIndexer` resolves per locked run against the vault content epoch and passes it into `_stream_encode_and_upsert_vault`; `DocumentIndexer` resolves at `full_index`/`incremental_index` entry against the document policy content fingerprint.
- Keep every donor lookup on the calling consumer thread, strictly outside `gpu_lock`; the reuse module never imports torch and spawns no threads, and the chunk-worker import chain is untouched.

## Outcome

- Verified hits produce zero forward passes (proven by an encoder tripwire that raises on any forward: mutation removed the empty-miss early return, the test went red with "dense forward ran for a fully adopted slice", restore went green).
- Content-verify gate proven able to fail: mutating the byte-compare so same-id/different-content donors are adopted turned `test_content_mismatch_at_same_point_id_is_a_miss_and_encodes` red on its specific assertion (`reuse_hits == 0`, got 1); restore green. Both directions recorded here and re-run as one sequence.
- Reuse off (`VAULTSPEC_RAG_INDEX_REUSE=0`) resolves to no context, and the `reuse=None` path is structurally today's code path.
- Gates on touched files: ruff check + format clean, basedpyright 0 errors, ty clean (`python-platform all` via pyproject), radon max rank C or better on every block.

## Notes

- Local-mode donors are limited to collections the store handle already has open (`supports_donor_reads`); cross-root reuse ships server-mode first, exactly as the decision record scopes it.
- The embedded local engine returns cosine dense vectors unit-normalized; equivalent under cosine scoring, treated as valid adoption.
- Scope grew beyond `_streaming.py` by necessity: the once-per-run donor resolution lives in the three indexers (`_codebase_indexer.py`, `_vault_indexer.py`, `_document_indexer.py`) because the content epoch is per-kind, per-run state.
