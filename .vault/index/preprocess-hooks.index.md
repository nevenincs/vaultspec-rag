---
generated: true
tags:
  - '#index'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
related:
  - '[[2026-06-10-preprocess-hooks-W01-P01-S01]]'
  - '[[2026-06-10-preprocess-hooks-W01-P01-S02]]'
  - '[[2026-06-10-preprocess-hooks-W01-P01-S03]]'
  - '[[2026-06-10-preprocess-hooks-W01-P02-S04]]'
  - '[[2026-06-10-preprocess-hooks-W01-P02-S05]]'
  - '[[2026-06-10-preprocess-hooks-W02-P03-S06]]'
  - '[[2026-06-10-preprocess-hooks-W02-P03-S07]]'
  - '[[2026-06-10-preprocess-hooks-W02-P03-S08]]'
  - '[[2026-06-10-preprocess-hooks-W02-P04-S09]]'
  - '[[2026-06-10-preprocess-hooks-W02-P04-S10]]'
  - '[[2026-06-10-preprocess-hooks-W02-P04-S11]]'
  - '[[2026-06-10-preprocess-hooks-W03-P05-S12]]'
  - '[[2026-06-10-preprocess-hooks-W03-P05-S13]]'
  - '[[2026-06-10-preprocess-hooks-W03-P05-S14]]'
  - '[[2026-06-10-preprocess-hooks-W03-P06-S15]]'
  - '[[2026-06-10-preprocess-hooks-W03-P06-S16]]'
  - '[[2026-06-10-preprocess-hooks-W03-P06-S17]]'
  - '[[2026-06-10-preprocess-hooks-W03-P07-S18]]'
  - '[[2026-06-10-preprocess-hooks-W03-P07-S19]]'
  - '[[2026-06-10-preprocess-hooks-W03-P07-S20]]'
  - '[[2026-06-10-preprocess-hooks-W03-P08-S21]]'
  - '[[2026-06-10-preprocess-hooks-W03-P08-S22]]'
  - '[[2026-06-10-preprocess-hooks-W03-P08-S23]]'
  - '[[2026-06-10-preprocess-hooks-W03-P08-S24]]'
  - '[[2026-06-10-preprocess-hooks-W03-P09-S25]]'
  - '[[2026-06-10-preprocess-hooks-W03-P09-S26]]'
  - '[[2026-06-10-preprocess-hooks-W03-P09-S27]]'
  - '[[2026-06-10-preprocess-hooks-W04-P10-S28]]'
  - '[[2026-06-10-preprocess-hooks-W04-P10-S29]]'
  - '[[2026-06-10-preprocess-hooks-W04-P10-S30]]'
  - '[[2026-06-10-preprocess-hooks-W04-P11-S31]]'
  - '[[2026-06-10-preprocess-hooks-W04-P11-S32]]'
  - '[[2026-06-10-preprocess-hooks-W04-P11-S33]]'
  - '[[2026-06-10-preprocess-hooks-W04-P11-S34]]'
  - '[[2026-06-10-preprocess-hooks-W04-P11-S35]]'
  - '[[2026-06-10-preprocess-hooks-W05-P12-S36]]'
  - '[[2026-06-10-preprocess-hooks-W05-P12-S37]]'
  - '[[2026-06-10-preprocess-hooks-W05-P12-S38]]'
  - '[[2026-06-10-preprocess-hooks-W05-P13-S39]]'
  - '[[2026-06-10-preprocess-hooks-W05-P13-S40]]'
  - '[[2026-06-10-preprocess-hooks-W05-P13-S41]]'
  - '[[2026-06-10-preprocess-hooks-W06-P14-S42]]'
  - '[[2026-06-10-preprocess-hooks-W06-P15-S43]]'
  - '[[2026-06-10-preprocess-hooks-W06-P15-S44]]'
  - '[[2026-06-10-preprocess-hooks-W06-P16-S45]]'
  - '[[2026-06-10-preprocess-hooks-W07-P17-S46]]'
  - '[[2026-06-10-preprocess-hooks-W07-P17-S47]]'
  - '[[2026-06-10-preprocess-hooks-W07-P17-S48]]'
  - '[[2026-06-10-preprocess-hooks-W07-P17-S49]]'
  - '[[2026-06-10-preprocess-hooks-W07-P18-S50]]'
  - '[[2026-06-10-preprocess-hooks-W07-P18-S51]]'
  - '[[2026-06-10-preprocess-hooks-W07-P19-S52]]'
  - '[[2026-06-10-preprocess-hooks-W07-P19-S53]]'
  - '[[2026-06-10-preprocess-hooks-W07-P20-S54]]'
  - '[[2026-06-10-preprocess-hooks-W07-P20-S55]]'
  - '[[2026-06-10-preprocess-hooks-adr]]'
  - '[[2026-06-10-preprocess-hooks-plan]]'
  - '[[2026-06-10-preprocess-hooks-research]]'
  - '[[2026-06-11-preprocess-hooks-audit]]'
---

# `preprocess-hooks` feature index

Auto-generated index of all documents tagged with `#preprocess-hooks`.

## Documents

### adr

- `2026-06-10-preprocess-hooks-adr` - `preprocess-hooks` adr: `document preprocessing hook infrastructure` | (**status:** `accepted`)

### audit

- `2026-06-11-preprocess-hooks-audit` - `preprocess-hooks` audit: `code review`

### exec

- `2026-06-10-preprocess-hooks-W01-P01-S01` - Implement the preprocess rule dataclass, tomllib loader, pathspec compilation, determinism sort, and error policy (D1, D2, D3)
- `2026-06-10-preprocess-hooks-W01-P01-S02` - Resolve rules per-root via a new \_build_preprocess_rules() in the codebase indexer (D1, D2)
- `2026-06-10-preprocess-hooks-W01-P01-S03` - Add unit tests for loading, ordering, ignore-composition, and error policy with real toml fixtures (D1, D2, D3)
- `2026-06-10-preprocess-hooks-W01-P02-S04` - Define PreprocOutput, PreprocUnit, and Locator models with extra=forbid, the units/text XOR validator, and the schema-version gate (D4, D5)
- `2026-06-10-preprocess-hooks-W01-P02-S05` - Add unit tests with valid, invalid, newer-version, and older-version fixtures (D4, D5)
- `2026-06-10-preprocess-hooks-W02-P03-S06` - Implement the command runner: path substitution, subprocess.run timeout, stdout JSON parse, and on_error semantics (D6, D9)
- `2026-06-10-preprocess-hooks-W02-P03-S07` - Add the preprocess_max_emitted_bytes config knob and enforce the emitted-text cap in the runner (D10)
- `2026-06-10-preprocess-hooks-W02-P03-S08` - Add unit tests with a real echo-to-JSON script fixture: success, timeout, nonzero-exit, oversize, bad-json (D6, D9, D10)
- `2026-06-10-preprocess-hooks-W02-P04-S09` - Implement the preprocess cache: key composition, sharded per-source JSON, atomic tmp-plus-replace write (D7)
- `2026-06-10-preprocess-hooks-W02-P04-S10` - Wire clean rebuild rmtree of the cache subtree into the codebase indexer clean path (D7)
- `2026-06-10-preprocess-hooks-W02-P04-S11` - Add unit tests for cache hit/miss, version-bump invalidation, and clean rebuild (D7)
- `2026-06-10-preprocess-hooks-W03-P05-S12` - Insert preprocess_decoded at the top of both chunk_file and chunk_and_hash_file (D6)
- `2026-06-10-preprocess-hooks-W03-P05-S13` - Thread resolved rules and knobs pickle-safely from the codebase indexer into the worker calls (D6)
- `2026-06-10-preprocess-hooks-W03-P05-S14` - Add a fresh-interpreter regression test that the worker import chain stays torch-free with preprocess wired (D6)
- `2026-06-10-preprocess-hooks-W03-P06-S15` - Make the full-scan extension, size, and binary gate preprocess-rule-aware (D2, D10)
- `2026-06-10-preprocess-hooks-W03-P06-S16` - Make the scoped incremental gate preprocess-rule-aware (D2, D8, D10)
- `2026-06-10-preprocess-hooks-W03-P06-S17` - Make the watcher \_is_code_change preprocess-rule-aware (D8)
- `2026-06-10-preprocess-hooks-W03-P07-S18` - Add the preproc_docs collection schema and payload indexes with the split locator fields (D12)
- `2026-06-10-preprocess-hooks-W03-P07-S19` - Implement upsert, stored-chunk id, and purge-by-source-path reconciliation for preproc units (D12)
- `2026-06-10-preprocess-hooks-W03-P07-S20` - Add unit tests for collection upsert, the locator-index split, and purge-by-path (D12)
- `2026-06-10-preprocess-hooks-W03-P08-S21` - Extend IndexResult with preprocess_skipped, preprocess_failed, and the preprocess_failures list (D11)
- `2026-06-10-preprocess-hooks-W03-P08-S22` - Carry preprocess status on FileChunkResult and accumulate counts in the orchestrator (D11)
- `2026-06-10-preprocess-hooks-W03-P08-S23` - Surface preprocess counts in the jobs registry and watcher summary strings (D11)
- `2026-06-10-preprocess-hooks-W03-P08-S24` - Surface preprocess counts in the CLI index --json output (D11)
- `2026-06-10-preprocess-hooks-W03-P09-S25` - Add anchor and locator fields to SearchResult and populate them at the codebase-result mapping seam (D12)
- `2026-06-10-preprocess-hooks-W03-P09-S26` - Add anchor and locator to the pydantic SearchResultItem wire model (D12)
- `2026-06-10-preprocess-hooks-W03-P09-S27` - Render anchor and locator in the CLI result table (D12)
- `2026-06-10-preprocess-hooks-W04-P10-S28` - Add the preprocess Typer sub-app with list, check, and run-one verbs and the --json envelope (D13)
- `2026-06-10-preprocess-hooks-W04-P10-S29` - Register the preprocess sub-app on the CLI root (D13)
- `2026-06-10-preprocess-hooks-W04-P10-S30` - Add unit tests for the three verbs including check non-zero exit on invalid config (D13)
- `2026-06-10-preprocess-hooks-W04-P11-S31` - Add the .txt, .xml, .xsd, and .properties entries to LANGUAGE_MAP (D13)
- `2026-06-10-preprocess-hooks-W04-P11-S32` - Bump the SUPPORTED_EXTENSIONS test floor and add positive map assertions (D13)
- `2026-06-10-preprocess-hooks-W04-P11-S33` - Implement the stdlib html.parser strip with raw-markup fallback and thread html_strip into the worker (D13)
- `2026-06-10-preprocess-hooks-W04-P11-S34` - Add the html_strip config default and env override (D13)
- `2026-06-10-preprocess-hooks-W04-P11-S35` - Add unit tests for HTML stripping and the new extension behaviour (D13)
- `2026-06-10-preprocess-hooks-W05-P12-S36` - Add an end-to-end integration test: a command preprocessor fixture indexed on real GPU and Qdrant and searchable with anchors (D6, D12)
- `2026-06-10-preprocess-hooks-W05-P12-S37` - Add incremental and watcher routing coverage for a preprocessable change (D8)
- `2026-06-10-preprocess-hooks-W05-P12-S38` - Add coverage-count assertions for a failing preprocessor skip/fail surfacing (D11)
- `2026-06-10-preprocess-hooks-W05-P13-S39` - Write the preprocessing-hooks user guide covering config, schema, and the command-only v1 security posture (D9, D13)
- `2026-06-10-preprocess-hooks-W05-P13-S40` - Add illustrative licence-clean extractor plugin sketches with the pypdf-BSD versus PyMuPDF-AGPL note (D13)
- `2026-06-10-preprocess-hooks-W05-P13-S41` - Update the README with the feature, new env vars, and CLI verbs (D13)
- `2026-06-10-preprocess-hooks-W06-P14-S42` - Scaffold a disposable toy workspace with sample binary data, a project-side extractor, and a .vaultragpreprocess.toml (D1, D13)
- `2026-06-10-preprocess-hooks-W06-P15-S43` - Drive vaultspec-rag preprocess list/check/run-one against the toy project and capture output (D13)
- `2026-06-10-preprocess-hooks-W06-P15-S44` - Index and search the toy project on real GPU, confirming anchors/locators and skip visibility (D11, D12)
- `2026-06-10-preprocess-hooks-W06-P16-S45` - Run the pre-commit hook suite over the feature branch in a production-like pass and confirm green
- `2026-06-10-preprocess-hooks-W07-P17-S46` - Add an out-of-process entry-point runner that imports module:callable and emits PreprocOutput JSON (D9 follow-up)
- `2026-06-10-preprocess-hooks-W07-P17-S47` - Resolve entry_point rules in the loader instead of rejecting them (D9 follow-up)
- `2026-06-10-preprocess-hooks-W07-P17-S48` - Dispatch entry_point rules through the subprocess runner (interpreter -m entry runner) with timeout (D9 follow-up)
- `2026-06-10-preprocess-hooks-W07-P17-S49` - Add unit tests for entry_point success, bad reference, and timeout (D9 follow-up)
- `2026-06-10-preprocess-hooks-W07-P18-S50` - Replace subprocess.run with a bounded Popen read capping captured stdout (PREPROCESS-003)
- `2026-06-10-preprocess-hooks-W07-P18-S51` - Add a unit test that oversize stdout is bounded and skipped (PREPROCESS-003)
- `2026-06-10-preprocess-hooks-W07-P19-S52` - Carry Locator.end through the chunk payload, CodeChunk, and result rendering (PREPROCESS-005)
- `2026-06-10-preprocess-hooks-W07-P19-S53` - Add a unit test asserting a range locator end persists and renders (PREPROCESS-005)
- `2026-06-10-preprocess-hooks-W07-P20-S54` - Use a per-process cache temp-file suffix and read/validate the top-level config version field (PREPROCESS-006, CONFIG-001)
- `2026-06-10-preprocess-hooks-W07-P20-S55` - Add passthrough end-to-end and indexer-level cache version-bump coverage (TST-002, TST-003)

### plan

- `2026-06-10-preprocess-hooks-plan` - `preprocess-hooks` `document preprocessing hook infrastructure` plan

### research

- `2026-06-10-preprocess-hooks-research` - `preprocess-hooks` research: `document preprocessing hook infrastructure`
