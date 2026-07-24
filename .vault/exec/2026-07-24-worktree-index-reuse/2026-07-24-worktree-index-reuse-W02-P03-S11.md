---
tags:
  - '#exec'
  - '#worktree-index-reuse'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S11'
related:
  - "[[2026-07-24-worktree-index-reuse-plan]]"
---

# add unit tests for the read-through: verified hit adopts vectors and skips encode, miss encodes, flag off restores baseline behavior exactly

## Scope

- `src/vaultspec_rag/tests/test_index_reuse.py` (new)\`

## Description

- Add `src/vaultspec_rag/tests/test_index_reuse.py`: 11 tests against the real embedded backend in tmp (env isolation: `VAULTSPEC_RAG_STATUS_DIR` + `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` + `reset_config`, local mode forced). No behavior under test is mocked; the only doubles sit at the encoder boundary and at the donor-read override on real store subclasses.
- All-hits: seed exactly-unit-norm donor vectors (bit-exact under the embedded engine's cosine normalization), run the real slice path with an encoder tripwire that raises on ANY forward - completing the call is the zero-encode proof, and adopted dense plus sparse round-trip exactly. Documented why this double is acceptable: its sole subject is that the encoder is never reached.
- Content verify: same point id with different stored bytes asserts the SPECIFIC miss behavior - `reuse_hits == 0`, `reuse_misses == 1`, the exact embed text reached the encoder, the stored vector equals the freshly encoded one and differs from the donor's; a paired contrast test proves identical content adopts under the same setup, so only the byte-compare can produce the mismatch outcome. This is the assertion the W03 mutation proof binds to.
- Flag off: `VAULTSPEC_RAG_INDEX_REUSE=0` resolves to `(None, None)`, and a real-store subclass whose donor read raises `AssertionError` proves the `reuse=None` baseline never consults donors while encoding everything.
- Mixed slice alignment (crown jewel): five chunks, donors only at interleaved positions 0/2/4, distinctive four-hot donor vectors vs one-hot encoded vectors; asserts per-position exact vector identity (dense and sparse), encoder saw exactly the two miss texts in order, and hit-rate accounting.
- Degradation: a real-store subclass raising `RuntimeError` on donor reads encodes every chunk and never fails the job.
- Vault identity: adoption by `point_key` against the real vault chunk writer, plus text-mismatch miss; sparse-required rejects dense-only donor points; donor-absent telemetry snapshot shape pinned.

## Outcome

- 11 passed (plus sibling suites re-run green: donor reads and candidates 31 passed, streaming and checkpoint 25 passed, jobs and server routes 61 passed, torch-free import guards 19 passed; fresh-interpreter import of the reuse module leaves torch out of `sys.modules`).
- Guard tests proven able to fail, both directions in one sequence: (1) content-verify compare weakened -> mismatch test red on `reuse_hits == 0`; restored -> green. (2) all-hit early return removed -> zero-encode test red on "dense forward ran for a fully adopted slice"; restored -> green.
- ruff check and format, basedpyright, ty (`python-platform all`), and radon (max rank C) clean on the test file and every touched source file.

## Notes

- Donor and target are the same embedded collection in these tests (local mode reads only handles the store already holds); the cross-namespace server-mode donor path shares every line of seam code and is covered for eligibility by the donor-candidate suite. An end-to-end server-mode fork rehearsal remains for the integration wave.
