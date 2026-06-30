---
tags:
  - '#plan'
  - '#preprocess-hooks'
date: '2026-06-10'
modified: '2026-06-30'
tier: L3
related:
  - '[[2026-06-10-preprocess-hooks-adr]]'
  - '[[2026-06-10-preprocess-hooks-research]]'
---

# `preprocess-hooks` `document preprocessing hook infrastructure` plan

## Wave `W01` - foundations - contracts only, no indexing

Establish the config and schema contracts (D1-D5) that every later Wave consumes: the .vaultragpreprocess.toml loader and the pydantic PreprocOutput schema. No pipeline wiring yet. W02 depends on these contracts.

### Phase `W01.P01` - config layer

Load and resolve .vaultragpreprocess.toml into ordered, compiled rules per-root with the documented error policy (D1, D2, D3).

- [x] `W01.P01.S01` - Implement the preprocess rule dataclass, tomllib loader, pathspec compilation, determinism sort, and error policy (D1, D2, D3); `src/vaultspec_rag/indexer/_preprocess_config.py`.
- [x] `W01.P01.S02` - Resolve rules per-root via a new \_build_preprocess_rules() in the codebase indexer (D1, D2); `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W01.P01.S03` - Add unit tests for loading, ordering, ignore-composition, and error policy with real toml fixtures (D1, D2, D3); `src/vaultspec_rag/tests/test_preprocess_config.py`.

### Phase `W01.P02` - output schema

Define and validate the versioned PreprocOutput / PreprocUnit / Locator contract with per-file fault isolation (D4, D5).

- [x] `W01.P02.S04` - Define PreprocOutput, PreprocUnit, and Locator models with extra=forbid, the units/text XOR validator, and the schema-version gate (D4, D5); `src/vaultspec_rag/indexer/_preprocess_schema.py`.
- [x] `W01.P02.S05` - Add unit tests with valid, invalid, newer-version, and older-version fixtures (D4, D5); `src/vaultspec_rag/tests/test_preprocess_schema.py`.

## Wave `W02` - execution and cache - make a rule run

Make a command-form rule actually execute against one file and cache its output (D6, D7, D9, D10): the subprocess runner, the preprocess_decoded entry, and the per-source cache. Depends on W01 contracts; W03 wires this into the real pipeline.

### Phase `W02.P03` - command runner

Run a matched command rule against one file, parse and validate stdout JSON, enforce timeout and emitted-size cap and on_error (D6, D9, D10).

- [x] `W02.P03.S06` - Implement the command runner: path substitution, subprocess.run timeout, stdout JSON parse, and on_error semantics (D6, D9); `src/vaultspec_rag/indexer/_preprocess_runner.py`.
- [x] `W02.P03.S07` - Add the preprocess_max_emitted_bytes config knob and enforce the emitted-text cap in the runner (D10); `src/vaultspec_rag/config.py`.
- [x] `W02.P03.S08` - Add unit tests with a real echo-to-JSON script fixture: success, timeout, nonzero-exit, oversize, bad-json (D6, D9, D10); `src/vaultspec_rag/tests/test_preprocess_runner.py`.

### Phase `W02.P04` - preprocess cache

Cache validated output per source under the data dir keyed on content+id+version+schema, with clean-rebuild semantics (D7).

- [x] `W02.P04.S09` - Implement the preprocess cache: key composition, sharded per-source JSON, atomic tmp-plus-replace write (D7); `src/vaultspec_rag/indexer/_preprocess_cache.py`.
- [x] `W02.P04.S10` - Wire clean rebuild rmtree of the cache subtree into the codebase indexer clean path (D7); `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W02.P04.S11` - Add unit tests for cache hit/miss, version-bump invalidation, and clean rebuild (D7); `src/vaultspec_rag/tests/test_preprocess_cache.py`.

## Wave `W03` - indexing integration - wire into the pipeline

Wire preprocessing into the real index path (D2, D6, D8, D10, D11, D12): worker integration, preprocess-aware extension gates, the preproc_docs collection, failure visibility, and result surfacing. Depends on W02; W04 adds the operator surface.

### Phase `W03.P05` - worker integration

Insert preprocess_decoded at the top of both worker chunk functions and thread rules and knobs into the spawn worker pickle-safely (D6).

- [x] `W03.P05.S12` - Insert preprocess_decoded at the top of both chunk_file and chunk_and_hash_file (D6); `src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `W03.P05.S13` - Thread resolved rules and knobs pickle-safely from the codebase indexer into the worker calls (D6); `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W03.P05.S14` - Add a fresh-interpreter regression test that the worker import chain stays torch-free with preprocess wired (D6); `src/vaultspec_rag/tests/test_preprocess_worker.py`.

### Phase `W03.P06` - gate awareness and size cap

Make the three extension-gate sites preprocess-rule-aware and relax source size/binary gates for matched files (D2, D8, D10).

- [x] `W03.P06.S15` - Make the full-scan extension, size, and binary gate preprocess-rule-aware (D2, D10); `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W03.P06.S16` - Make the scoped incremental gate preprocess-rule-aware (D2, D8, D10); `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W03.P06.S17` - Make the watcher \_is_code_change preprocess-rule-aware (D8); `src/vaultspec_rag/watcher.py`.

### Phase `W03.P07` - preproc_docs collection

Add the dedicated Qdrant collection, payload mapping with split locator indexes, stored-chunk id, and purge-by-source-path reconciliation (D12).

- [x] `W03.P07.S18` - Add the preproc_docs collection schema and payload indexes with the split locator fields (D12); `src/vaultspec_rag/store.py`.
- [x] `W03.P07.S19` - Implement upsert, stored-chunk id, and purge-by-source-path reconciliation for preproc units (D12); `src/vaultspec_rag/store.py`.
- [x] `W03.P07.S20` - Add unit tests for collection upsert, the locator-index split, and purge-by-path (D12); `src/vaultspec_rag/tests/test_preprocess_store.py`.

### Phase `W03.P08` - failure visibility

Extend IndexResult and FileChunkResult with preprocess skip/fail counts and the failure list, surfaced no-swallow in jobs and CLI JSON (D11).

- [x] `W03.P08.S21` - Extend IndexResult with preprocess_skipped, preprocess_failed, and the preprocess_failures list (D11); `src/vaultspec_rag/indexer/_vault_prep.py`.
- [x] `W03.P08.S22` - Carry preprocess status on FileChunkResult and accumulate counts in the orchestrator (D11); `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W03.P08.S23` - Surface preprocess counts in the jobs registry and watcher summary strings (D11); `src/vaultspec_rag/server/jobs.py`.
- [x] `W03.P08.S24` - Surface preprocess counts in the CLI index --json output (D11); `src/vaultspec_rag/cli/_index.py`.

### Phase `W03.P09` - result surfacing

Carry anchor and locator onto the search result types and the CLI renderer, populated at the codebase-result mapping seam (D12).

- [x] `W03.P09.S25` - Add anchor and locator fields to SearchResult and populate them at the codebase-result mapping seam (D12); `src/vaultspec_rag/search/_models.py`.
- [x] `W03.P09.S26` - Add anchor and locator to the pydantic SearchResultItem wire model (D12); `src/vaultspec_rag/server/_models.py`.
- [x] `W03.P09.S27` - Render anchor and locator in the CLI result table (D12); `src/vaultspec_rag/cli/_render.py`.

## Wave `W04` - surface and adjacent asks - operator-facing

Ship the operator surface and the two independent adjacent asks (D13): the preprocess CLI verb group, the default-extension additions, and HTML-to-text normalisation. Depends on W03 for the runtime it inspects; the adjacent asks are independent.

### Phase `W04.P10` - preprocess CLI verbs

Add the vaultspec-rag preprocess list/check/run-one verb group with the --json envelope and check as the only hard-fail path (D13).

- [x] `W04.P10.S28` - Add the preprocess Typer sub-app with list, check, and run-one verbs and the --json envelope (D13); `src/vaultspec_rag/cli/_preprocess.py`.
- [x] `W04.P10.S29` - Register the preprocess sub-app on the CLI root (D13); `src/vaultspec_rag/cli/__init__.py`.
- [x] `W04.P10.S30` - Add unit tests for the three verbs including check non-zero exit on invalid config (D13); `src/vaultspec_rag/tests/test_cli_preprocess.py`.

### Phase `W04.P11` - adjacent asks

Add the four default plain-text extensions and the default-on HTML-to-text normalisation step (D13).

- [x] `W04.P11.S31` - Add the .txt, .xml, .xsd, and .properties entries to LANGUAGE_MAP (D13); `src/vaultspec_rag/indexer/_chunking.py`.
- [x] `W04.P11.S32` - Bump the SUPPORTED_EXTENSIONS test floor and add positive map assertions (D13); `src/vaultspec_rag/tests/test_indexer_unit.py`.
- [x] `W04.P11.S33` - Implement the stdlib html.parser strip with raw-markup fallback and thread html_strip into the worker (D13); `src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `W04.P11.S34` - Add the html_strip config default and env override (D13); `src/vaultspec_rag/config.py`.
- [x] `W04.P11.S35` - Add unit tests for HTML stripping and the new extension behaviour (D13); `src/vaultspec_rag/tests/test_html_strip.py`.

## Wave `W05` - verification and docs

End-to-end verification on real GPU + real Qdrant + real subprocess and the documentation/rule updates. Depends on every prior Wave landing; gates the PR.

### Phase `W05.P12` - integration tests

Prove the hook end-to-end on real GPU, real Qdrant, and a real command preprocessor across full, incremental, and watcher paths (D6, D8, D11, D12).

- [x] `W05.P12.S36` - Add an end-to-end integration test: a command preprocessor fixture indexed on real GPU and Qdrant and searchable with anchors (D6, D12); `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`.
- [x] `W05.P12.S37` - Add incremental and watcher routing coverage for a preprocessable change (D8); `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`.
- [x] `W05.P12.S38` - Add coverage-count assertions for a failing preprocessor skip/fail surfacing (D11); `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`.

### Phase `W05.P13` - documentation

Update the vaultspec-rag rule, README/user docs, and the security posture and illustrative-plugin notes (D9, D13).

- [x] `W05.P13.S39` - Write the preprocessing-hooks user guide covering config, schema, and the command-only v1 security posture (D9, D13); `docs/preprocessing-hooks.md`.
- [x] `W05.P13.S40` - Add illustrative licence-clean extractor plugin sketches with the pypdf-BSD versus PyMuPDF-AGPL note (D13); `docs/preprocessing-hooks.md`.
- [x] `W05.P13.S41` - Update the README with the feature, new env vars, and CLI verbs (D13); `README.md`.

## Wave `W06` - manual production-like integration validation

Non-test-driven, hands-on validation: an agent drives the real vaultspec-rag CLI and service against a toy project with sample binary data and a project-supplied extractor, confirming the preprocess hook works as a real user experiences it, then validates the pre-commit hook suite in a production-like pass. Depends on every prior Wave landing; final sign-off before release.

### Phase `W06.P14` - toy project and sample corpus

Stand up a disposable toy workspace with a real .vaultragpreprocess.toml, a project-side extractor script, and sample binary/unsupported data, mirroring a downstream consumer (D1, D13).

- [x] `W06.P14.S42` - Scaffold a disposable toy workspace with sample binary data, a project-side extractor, and a .vaultragpreprocess.toml (D1, D13); `tmp toy project (manual)`.

### Phase `W06.P15` - drive the real CLI end-to-end

Run the installed vaultspec-rag preprocess verbs, index, and search against the toy project and confirm extraction, anchors/locators, and skip visibility behave as documented (D11, D12, D13).

- [x] `W06.P15.S43` - Drive vaultspec-rag preprocess list/check/run-one against the toy project and capture output (D13); `vaultspec-rag preprocess (manual)`.
- [x] `W06.P15.S44` - Index and search the toy project on real GPU, confirming anchors/locators and skip visibility (D11, D12); `vaultspec-rag index/search (manual)`.

### Phase `W06.P16` - production-like pre-commit validation

Run the repository pre-commit hook suite over the feature branch in a production-like pass and confirm it is green (vault-fix, mdformat, pymarkdown, ruff, ty, spec-check, provider artifacts).

- [x] `W06.P16.S45` - Run the pre-commit hook suite over the feature branch in a production-like pass and confirm green; `.pre-commit-config.yaml (manual)`.

## Wave `W07` - follow-up hardening (deferred items pulled into scope)

Closes the deferred/accepted items from the code review and ADR: out-of-process entry_point support (the safe form of D9), a bounded subprocess stdout read (PREPROCESS-003), range-locator end surfacing (PREPROCESS-005), and the small robustness/coverage tidies (cache temp-suffix PREPROCESS-006, config version-field CONFIG-001, passthrough and version-bump coverage TST-002/003). The dedicated preproc_docs collection item (original ADR D12) is resolved by decision to keep the reviewer-confirmed codebase_docs approach; no rebuild. Depends on W01-W06 having landed.

### Phase `W07.P17` - out-of-process entry_point support

Ship the entry_point rule form by invoking module:callable in a dedicated subprocess so CPU-only isolation and timeout hold by construction, reusing the command validate/cap path (D9 follow-up, codification candidate preprocessors-run-out-of-process).

- [x] `W07.P17.S46` - Add an out-of-process entry-point runner that imports module:callable and emits PreprocOutput JSON (D9 follow-up); `src/vaultspec_rag/indexer/_preprocess_entry.py`.
- [x] `W07.P17.S47` - Resolve entry_point rules in the loader instead of rejecting them (D9 follow-up); `src/vaultspec_rag/indexer/_preprocess_config.py`.
- [x] `W07.P17.S48` - Dispatch entry_point rules through the subprocess runner (interpreter -m entry runner) with timeout (D9 follow-up); `src/vaultspec_rag/indexer/_preprocess_runner.py`.
- [x] `W07.P17.S49` - Add unit tests for entry_point success, bad reference, and timeout (D9 follow-up); `src/vaultspec_rag/tests/test_preprocess_entry.py`.

### Phase `W07.P18` - bounded subprocess stdout read

Cap the preprocessor's stdout capture so a runaway extractor cannot spike memory before the emitted-size cap fires (PREPROCESS-003).

- [x] `W07.P18.S50` - Replace subprocess.run with a bounded Popen read capping captured stdout (PREPROCESS-003); `src/vaultspec_rag/indexer/_preprocess_runner.py`.
- [x] `W07.P18.S51` - Add a unit test that oversize stdout is bounded and skipped (PREPROCESS-003); `src/vaultspec_rag/tests/test_preprocess_runner.py`.

### Phase `W07.P19` - range-locator end surfacing

Carry the validated Locator.end through payload, chunk, and rendering so range locators are not silently dropped (PREPROCESS-005).

- [x] `W07.P19.S52` - Carry Locator.end through the chunk payload, CodeChunk, and result rendering (PREPROCESS-005); `src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `W07.P19.S53` - Add a unit test asserting a range locator end persists and renders (PREPROCESS-005); `src/vaultspec_rag/tests/test_preprocess_store.py`.

### Phase `W07.P20` - robustness and coverage tidies

Per-process cache temp-suffix (PREPROCESS-006), read/validate the top-level config version field (CONFIG-001), and add passthrough end-to-end and indexer-level version-bump coverage (TST-002/003).

- [x] `W07.P20.S54` - Use a per-process cache temp-file suffix and read/validate the top-level config version field (PREPROCESS-006, CONFIG-001); `src/vaultspec_rag/indexer/_preprocess_cache.py`.
- [x] `W07.P20.S55` - Add passthrough end-to-end and indexer-level cache version-bump coverage (TST-002, TST-003); `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`.

## Description

This plan implements the generic document-preprocessing hook infrastructure decided in
the `preprocess-hooks` ADR (decisions D1-D13) and grounded in the `preprocess-hooks`
research. It is tracked upstream as issue 185. The feature lets any downstream project
register its own extraction logic for binary, unsupported, or poorly-indexing formats and
have the output indexed first-class against a versioned contract vaultspec-rag owns; v1
ships the command-form rule only (D9), with the in-process entry_point form deferred to a
follow-up.

The work is sequenced as five Waves that mirror the decision layering. Wave W01 builds the
two contracts every later Wave consumes - the `.vaultragpreprocess.toml` loader (D1, D2,
D3) and the pydantic `PreprocOutput` / `PreprocUnit` schema (D4, D5) - with no pipeline
wiring. Wave W02 makes a single command rule execute and cache its output: the subprocess
runner with timeout and emitted-size cap (D6, D9, D10) and the per-source cache keyed on
content plus preprocessor and schema versions (D7). Wave W03 wires preprocessing into the
real index path below the existing chunk seam: worker integration (D6), preprocess-aware
extension gates across the full-scan, scoped, and watcher sites (D2, D8, D10), the
dedicated `preproc_docs` collection with split locator indexes and purge-by-source-path
(D12), no-swallow failure visibility (D11), and anchor/locator result surfacing (D12).
Wave W04 ships the operator surface - the `preprocess list/check/run-one` CLI verbs (D13) -
and the two independent adjacent asks: the four default plain-text extensions and the
default-on HTML-to-text normalisation (D13). Wave W05 verifies the whole feature end-to-end
on real GPU, real Qdrant, and a real command preprocessor, and writes the documentation and
security-posture notes.

Decision-to-Wave coverage map (every ADR decision is owned by at least one Wave): D1 W01;
D2 W01+W03; D3 W01; D4 W01; D5 W01; D6 W02+W03; D7 W02; D8 W03; D9 W02; D10 W02+W03; D11
W03; D12 W03; D13 W04+W05. The embed/upsert seam and the single GPU consumer are never
touched, so the `gpu-consumer-single-thread` and `index-workers-stay-cpu-only` rules hold
throughout (the command form is CPU-only by process construction).

## Steps

## Parallelization

Waves are sequenced by default: W01 must land before W02 (the runner consumes the rule and
schema types), W02 before W03 (the pipeline wires the runner and cache), W03 before W05
(verification needs the full runtime). W04 depends on W03 for the runtime its CLI verbs
inspect, except the two adjacent asks in W04.P11 (default extensions and HTML strip) which
are fully independent and may be done at any time, including first as a quick warm-up.

Within a Wave, Phases that share no file may run in parallel: W01.P01 (config) and W01.P02
(schema) are independent; in W03, P07 (the `preproc_docs` store), P08 (failure-visibility
plumbing), and P09 (result surfacing) touch disjoint files and may proceed concurrently
once P05 (worker integration) and P06 (gate awareness) have landed, since P05 and P06 both
mutate the codebase indexer and must be serialised against each other. In W04, P10 (CLI)
and P11 (adjacent asks) are independent. Within any Phase, the implementation Step precedes
its test Step.

## Verification

The plan is complete when every Step in every Wave is closed and all of the following
verifiable checks pass:

- A `.vaultragpreprocess.toml` with a command rule causes a matched non-source file (a
  binary fixture outside `SUPPORTED_EXTENSIONS`, above `_MAX_FILE_SIZE`) to be extracted,
  indexed into `preproc_docs`, and returned by `search_codebase` with a populated `anchor`
  and `locator` (D2, D6, D12).
- A preprocessor that times out, exits non-zero, emits invalid JSON, emits a newer
  `schema_version`, or emits over the emitted-bytes cap is skipped per-file with a logged
  warning and a surfaced count in `IndexResult`, `server service jobs`, and the index
  `--json` output - never a crash and never a silent gap (D5, D10, D11).
- A second incremental pass over an unchanged corpus is a cache hit (no preprocessor
  re-invocation); bumping a rule's preprocessor version re-runs exactly that rule's files;
  `clean=true` rebuilds cold (D7).
- A watched edit to a preprocessable file routes through the existing debounce/cooldown
  single-writer path and reindexes it (D8).
- `vaultspec-rag preprocess check` exits non-zero on an invalid config and zero on a valid
  one; `list` and `run-one` honour the `--json` envelope (D3, D13).
- `.txt/.xml/.xsd/.properties` index as plain text; `.html` indexes with tags stripped by
  default, falling back to raw markup on a parse error (D13).
- The full unit and integration suite passes on real GPU + real Qdrant + real subprocess
  (no mocks, stubs, or skips); `basedpyright` strict reports zero and `ruff` reports zero;
  the worker import chain stays torch-free; and `vaultspec-code-review` signs off.
