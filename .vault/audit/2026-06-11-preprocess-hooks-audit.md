---
tags:
  - '#audit'
  - '#preprocess-hooks'
date: '2026-06-11'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# `preprocess-hooks` audit: `code review`

## Scope

Code review of the `feat/preprocess-hooks` branch against `main`, implementing the generic
document-preprocessing hook infrastructure (issue 185, ADR D1-D13). Two parallel
`vaultspec-code-reviewer` agents covered (A) safety and pipeline correctness and (B)
failure-visibility, result surfacing, the D12 storage deviation, and test quality. The
branch was all-green at review time (796 unit tests, integration on real GPU + Qdrant,
ruff + basedpyright strict zero). No code was modified during the review.

## Findings

### VIS-001 | HIGH | preprocess skip counts are dead on the incremental/watcher path

`_record_preprocess_result` runs only on the full-index path (via `chunk_and_hash_file` ->
`FileChunkResult`). The incremental and scoped paths chunk via `chunk_file`, which returns a
bare `list[CodeChunk]` and discards the worker's `preprocess_status`, so both incremental
`IndexResult`s report `preprocess_skipped=0`. The resident watcher uses the scoped path
exclusively, so the dominant production surface never surfaces a skip count - and the only
remaining signal is a `logger.warning` emitted inside a spawn-worker subprocess whose stderr
is not reliably captured into the service log. Direct violation of D11 and the codified
`preprocess-coverage-is-never-silent` rule. **Resolution: fix before merge** - thread skip
status out of the scoped path.

### VIS-002 | HIGH | jobs reindex summary drops the skip count it computes

`jobs.start_reindex_codebase` calls `full_index(clean=True)` (which DOES populate
`preprocess_skipped`) but builds its `record_finish` result string from only
`added/updated/removed/duration_ms`, so `server service jobs` never shows the count on the
one path that computes it. Plan S23 half-done. **Resolution: fix before merge.**

### TST-001 | HIGH | the incremental skip-count gap is untested

The skip-count assertion runs only through `full_index`; the incremental integration test
uses a succeeding extractor and asserts only routing. A failing-preprocessor-through-
`incremental_index` test would fail today. **Resolution: add the test with the VIS-001 fix.**

### STO-002 | MEDIUM | cache key uses `command`, not `preprocessor_version` (D7 divergence)

`_cache_key` composes `(source_hash, command, schema_version)`; D7's normative tuple names
`preprocessor_version`. Because the producing version is only known from the output (not a
priori at read time), keying on it at lookup is impossible; the code keys on `command` as
the documented invalidation lever. The module docstring is honest about this, but the ADR
text is stale. Consequence: editing an extractor's internals without changing its command
string serves stale cache until a clean rebuild. **Resolution: amend ADR D7 to document
command-as-lever (code is sound); a clean rebuild remains the escape hatch.**

### WAT-001 | MEDIUM | watcher `_CODE_EXTENSIONS` omits the new adjacent-ask extensions

`.txt/.xml/.xsd/.properties` were added to `LANGUAGE_MAP` but not to the watcher's hardcoded
`_CODE_EXTENSIONS`, so watched edits to those files do not trigger a reindex (a full or
scoped rescan still picks them up). The comment claims it mirrors the indexer. **Resolution:
add the four extensions before merge.**

### PREPROCESS-003 | MEDIUM | subprocess stdout is fully buffered before the emitted-size cap

`subprocess.run(capture_output=True)` buffers the child's entire stdout before the
`preprocess_max_emitted_bytes` cap is evaluated, so a runaway extractor can spike memory
before the cap skips its output. Under the project-root trust model (the extractor is the
project's own code) this is a project bug, not a security hole. **Resolution: accepted for
v1 with rationale; a streamed/bounded `Popen` read is a documented follow-up.**

### STO-001 | LOW | D12 collection deviation is sound but the ADR text is stale

Preprocessed units live in the existing `codebase_docs` collection with extended payload
rather than a dedicated `preproc_docs` collection. The overload is internally consistent
(upsert, split locator indexes, purge-by-path reconciliation, search mapping all hold; no
existing code-search filter breaks; preproc chunks are distinguishable via
`preprocessor_id`). The deviation was surfaced to and approved by the user. **Resolution:
amend ADR D12 to record the accepted deviation.**

### VIS-003 | LOW | ADR D11 names a `preprocess_failed` field that was not implemented

`on_error=fail` aborts the run (raises) rather than incrementing a count, so a separate
`preprocess_failed` counter is moot and the `!failed` summary token is unimplemented.
**Resolution: amend ADR D11 to the two-field reality.**

### PREPROCESS-005 | LOW | locator `end` is validated but never persisted or surfaced

`Locator.end` is accepted by the schema but dropped in `_chunks_from_output`. **Resolution:
accept for v1; documented as reserved (range-locator surfacing is a follow-up).**

### PREPROCESS-006 | LOW | byte-identical sources share a cache `.tmp` filename

Two distinct files with identical bytes share a cache key and thus a `<key>.tmp`; the atomic
`os.replace` keeps the final file uncorrupted, worst case one harmless lost write.
**Resolution: accept; a pid/uuid temp suffix is a trivial future hardening.**

### CONFIG-001 | LOW | the top-level `.vaultragpreprocess.toml` `version` field is unread

`load_preprocess_rules` ignores the document-level `version`. Harmless today (config-schema
versioning is unused). **Resolution: accept; reserved for a future config-schema bump.**

### TST-002 / TST-003 | LOW | coverage gaps: passthrough end-to-end, indexer-level version-bump

`on_error=passthrough` and cache version-bump are tested at the unit/module level but not
end-to-end through the indexer. **Resolution: accept for v1; noted as follow-up coverage.**

### Verified clean (no findings)

CPU-only / GPU-consumer invariants (worker chain torch-free; command runs in a subprocess
grandchild; entry_point rejected; embed seam untouched); subprocess injection-safety
(`shlex.split`, no shell, token-wise `{path}`); gate ordering (ignore wins before the
preprocess short-circuit); pickle-safety of `PreprocessContext` / `PreprocessConfig`; cache
atomicity (`.tmp` + `os.replace`, corrupt-as-miss, clean rmtree); result-surfacing coherence;
and test integrity (no mocks, stubs, skips, or tautologies; real subprocess + real Qdrant +
real GPU).

## Recommendations

Fix before merge: VIS-001, VIS-002, TST-001 (the no-swallow violation on the dominant path
and its missing test), and WAT-001 (watcher extension divergence). Reconcile the ADR text
for STO-002 (D7 cache key), STO-001 (D12 collection), and VIS-003 (D11 field set). Accept
with recorded rationale: PREPROCESS-003 (trust-model OOM window), PREPROCESS-005 (locator
end), PREPROCESS-006 (temp name), CONFIG-001 (version field), TST-002/003 (coverage
follow-ups).

## Codification candidates
