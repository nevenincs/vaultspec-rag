---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S05'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# implement the donor eligibility gate: collection kind, dense dims and named-vector layout, embedding model identity including revision, and content-epoch sentinel equality

## Scope

- `src/vaultspec_rag/indexer/_donor_candidates.py`

## Description

- Implement `evaluate_donor_eligibility(candidate, *, kind, expected_content_epoch, expected_schema, donor_schema_probe, expected_model)` returning a structured `DonorEligibility(eligible, reasons)` with one `IneligibilityReason` per failed gate.
- Gate 1 (kind): candidate's collection kind must equal the requested kind; discovery additionally requires the kind's collection to be recorded in the donor's manifest entry.
- Gate 2 (dims/layout): compare `VectorSchema(dense_name, dense_dim, sparse_name)` against the candidate collection's actual schema via the caller-supplied `donor_schema_probe`; an unreachable/absent collection fails closed (`SCHEMA_UNAVAILABLE`); without a probe both sides resolve from the same live config (`expected_vector_schema()` reads `effective_dense_dim` and the sparse toggle). Also gate the manifest-recorded `storage_schema_version` against the current storage shape generation.
- Gate 3 (model identity): gate on everything recorded today - the per-root embed-input format marker (`__code_embed_schema__` / `__vault_point_schema__` / document `meta_schema_version`) via `read_donor_recorded_state` and `current_model_identity`. Configured dense/sparse model names are process-global (not persisted per root) and model revision is recorded nowhere, so neither can be honestly gated per donor; the limitation is documented at the comparison site.
- Gate 4 (content epoch): the donor root's sidecar-stamped content epoch for the kind (`__code_content_epoch__`, `__vault_content_epoch__`, document `content_fingerprint`) must equal the caller-supplied effective epoch of the indexing root; missing/unreadable/legacy sidecars and incomplete document publications fail closed (`SIDECAR_UNAVAILABLE`).

## Outcome

- Eligibility surface in `src/vaultspec_rag/indexer/_donor_candidates.py`: `IneligibilityReason` enum (KIND_MISMATCH, STORAGE_SCHEMA_MISMATCH, VECTOR_LAYOUT_MISMATCH, SCHEMA_UNAVAILABLE, MODEL_IDENTITY_MISMATCH, CONTENT_EPOCH_MISMATCH, SIDECAR_UNAVAILABLE), `VectorSchema`, `ModelIdentity`, `DonorRecordedState`, `read_donor_recorded_state`, `current_model_identity`, `expected_vector_schema`, `evaluate_donor_eligibility`.
- Every unevaluable gate fails closed to ineligible; the module performs no writes and never imports torch.
- ruff, ruff format, basedpyright, and ty all clean on the module.

## Notes

- Residual identity gap: no per-root record of the embedding model name or revision exists anywhere today (config is process-global; sidecars record only embed-format markers). A same-dimensionality model swap between donor indexing and reuse is therefore invisible to this gate and is bounded by the dims gate (dimension-changing swaps) plus the per-point payload-content verification at the seam. Closing it fully would require new persisted state, which the governing decision forbids.
- The vault sidecar's reserved keys are private to the vault indexer's write side; this module mirrors the literals read-only, and a writer-side rename degrades to fail-closed ineligibility (hit-rate loss, never stale reuse).
