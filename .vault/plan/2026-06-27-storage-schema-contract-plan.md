---
tags:
  - '#plan'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
tier: L2
related:
  - '[[2026-06-26-storage-schema-contract-adr]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #plan) and one feature tag.
     Replace storage-schema-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     tier is mandatory for new plans. Allowed: L1, L2, L3, L4.
     L1 = Steps only. L2 = Phases above Steps. L3 = Waves above
     Phases above Steps. L4 = Epic above Waves above Phases above
     Steps; PM association required. Pre-existing plans without this
     field default to L2.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'. The related field
     carries the AUTHORIZING documents (ADR, research, reference, prior
     plan) for every Step in this plan; Steps inherit this chain;
     per-row reference footers do not exist.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- HIERARCHY AND TIERS:
     Epic > Wave > Phase > Step. Step is the canonical leaf-row
     noun. Execution Record artifact: <Step Record>.
     Tier is declared in frontmatter as tier: L1/L2/L3/L4
     (mandatory for new plans; pre-existing plans without the
     field default to L2 and the writer adds the field on first
     edit). The tier selects containers:
       L1 = Steps only.
       L2 = Phases above Steps.
       L3 = Waves above Phases above Steps.
       L4 = Epic above Waves above Phases above Steps; MUST declare
            a project-management association in the Epic intent
            block prose.
     Selection is by complexity criteria, not container counting.
     Writer never invents containers to qualify a tier. -->

<!-- IDENTIFIERS AND ROW CONTRACT:
     S##, P##, W## are flat, per-document, append-only, immutable.
     Promotion adds containers without renumbering. Gaps are not
     reused.
     Display paths are computed from current grouping:
       Step path:    L1 S##   L2 P##.S##   L3/L4 W##.P##.S##
       Phase heading:        L2 P##       L3/L4 W##.P##
       Wave heading:                      L3/L4 W##
     Row format:
       - [ ] `<display-path>` - imperative-verb action; `path/to/file`.
     Two-state checkboxes only ([ ] open, [x] closed). No per-row
     reference footers; wiki-links and markdown links are forbidden
     in plan body. Authorizing documents go in the plan's `related:`
     frontmatter once.
     ASCII spaced hyphens everywhere; em-dash (U+2014) and en-dash
     (U+2013) are forbidden. Step rows within a Phase are
     contiguous. -->

<!-- NO COMPRESSION:
     N self-similar actions = N rows. Never collapse into "for each
     X, do Y" / "across all callers, do Z" / "in every module,
     replace W". The rule applies at every tier including L1. -->

<!-- VAULTSPEC-CORE VAULT PLAN CLI:
     The `vaultspec-core vault plan` CLI is the canonical surface for
     structural manipulation of this plan document. Writers and
     executors MUST use `vaultspec-core vault plan step add/insert/move/
     remove/check/uncheck/toggle/edit`,
     `vaultspec-core vault plan phase add/move/remove/edit`,
     `vaultspec-core vault plan wave add/move/remove/edit`,
     `vaultspec-core vault plan epic intent`, and
     `vaultspec-core vault plan tier promote/demote` for every
     identifier-affecting change rather than hand-editing the row
     grammar. Hand edits are tolerated by the parser but flagged by
     `vaultspec-core vault plan check`; canonical-identifier preservation is
     guaranteed only when the CLI performs the mutation. Run
     `vaultspec-core vault plan --help` for the full subcommand
     surface. -->

# `storage-schema-contract` plan

Codify rag's Qdrant collection, vector, and payload layout as a single versioned, typed, runtime-advertised schema contract so consumers can assert compatibility before reading.

### Phase `P01` - storage-schema module: the single source of truth

Create the neutral torch-free schema leaf that defines the version, typed payloads, index tuples, and effective descriptor (ADR D1, D2).

- [x] `P01.S01` - Define STORAGE_SCHEMA_VERSION, the dense/sparse vector-name and distance constants, and the TypedDict payload shapes for vault doc, vault chunk, and code chunk; `src/vaultspec_rag/store_schema.py`.
- [x] `P01.S02` - Declare the canonical KEYWORD and INTEGER payload-index field tuples per collection; `src/vaultspec_rag/store_schema.py`.
- [x] `P01.S03` - Implement describe_storage_schema building the effective config-derived wire descriptor without importing torch; `src/vaultspec_rag/store_schema.py`.
- [x] `P01.S04` - Implement assert_compatible applying the version, dense-dimension, and dense-vector-name rules; `src/vaultspec_rag/store_schema.py`.
- [x] `P01.S05` - Unit-test the descriptor shape and the compatibility helper across match and mismatch cases; `src/vaultspec_rag/tests/test_store_schema.py`.

### Phase `P02` - route store.py through the schema module

Refactor the upsert and ensure paths to build payloads and indexes from the schema module, shape-preserving, guarded by a reindex-parity test (ADR D2 constraint).

- [x] `P02.S06` - Build vault document and vault chunk payloads from the TypedDicts in the upsert paths; `src/vaultspec_rag/store.py`.
- [x] `P02.S07` - Build code chunk payloads from the TypedDict in the code upsert path; `src/vaultspec_rag/store.py`.
- [x] `P02.S08` - Consume the schema index tuples in ensure_table and ensure_code_table instead of inline literals; `src/vaultspec_rag/store.py`.
- [x] `P02.S09` - Source the dense vector params (name, default dimension, distance) from the schema module in collection create; `src/vaultspec_rag/store.py`.
- [x] `P02.S10` - Add a reindex-parity integration test asserting points serialize byte-for-byte unchanged; `src/vaultspec_rag/tests/integration/test_store_schema_parity.py`.

### Phase `P03` - advertise the contract at runtime

Surface the descriptor on /readiness and the bare schema_version on /health and /service-state, plus the assert_compatible helper (ADR D3, D4).

- [x] `P03.S11` - Add the bounded schema descriptor node to the readiness report to_dict; `src/vaultspec_rag/_readiness.py`.
- [x] `P03.S12` - Echo the bare schema_version on the raw /health payload; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `P03.S13` - Echo the bare schema_version on the get_service_state snapshot; `src/vaultspec_rag/api.py`.
- [x] `P03.S14` - Add server-route tests asserting the schema descriptor on /readiness and the version echo on /health and /service-state; `src/vaultspec_rag/tests/test_server_routes.py`.

### Phase `P04` - document and guard the contract

Author the reference doc and add the drift and propagation tests that fail when an inline shape diverges from the typed definition (ADR D4, D5).

- [x] `P04.S15` - Author the storage-schema reference document with the field tables, version-bump policy, and consumer compatibility recipe; `.vault/reference/2026-06-27-storage-schema-contract-reference.md`.
- [x] `P04.S16` - Add a real-store drift test asserting the live collection vector config and indexed payload fields equal the declared schema; `src/vaultspec_rag/tests/integration/test_store_schema_drift.py`.

## Description

Codify the Qdrant data shape into a single versioned, typed, runtime-advertised contract,
per the accepted ADR. Phase P01 builds one neutral torch-free schema leaf that is the sole
source of truth: the `STORAGE_SCHEMA_VERSION` integer, the dense and sparse vector
constants, the TypedDict payload shapes, the canonical payload-index tuples, a
config-derived effective descriptor, and the consumer compatibility helper. Phase P02
routes the store through that leaf, replacing the inline upsert dicts and inline index
lists, guarded by a reindex-parity check that proves the refactor is shape-preserving.
Phase P03 advertises the contract at runtime - the full descriptor on the read-only
torch-free readiness report, and the bare version on the raw health endpoint and the
service-state snapshot for a cheap pre-read gate. Phase P04 publishes the human-facing
reference and adds the drift test that fails CI when an inline shape diverges from the
typed definition. The work is grounded in the storage-schema-contract ADR and research;
the priority consumer is the dashboard engine's direct-Qdrant embedding read, which today
assumes the shape with no version signal.

## Steps

<!-- The plan's tier (declared in frontmatter as `tier: L1`, `L2`, `L3`, or
`L4`) determines the structure under this section:

- `L1`: a flat list of Step rows (no Phase, Wave, or Epic).
- `L2`: one or more `### Phase` blocks each containing Step rows.
- `L3`: one or more `## Wave` blocks each containing Phase blocks.
- `L4`: a `## Epic intent` block, followed by Wave blocks. -->

<!-- Replace this scaffold with the tier-appropriate structure for your plan.
Format examples for each block type are embedded below as commented
templates. -->

<!-- IMPORTANT: This document must be updated between execution runs to
     track progress. -->

<!-- PHASE BLOCK FORMAT (L2, L3, L4):
     ### Phase `P02` - rewrite the writer-agent contract

     One sentence stating what this Phase delivers.

     - [ ] `P02.S01` - imperative-verb action; `path/to/file`.
     - [ ] `P02.S02` - imperative-verb action; `path/to/file`.

     At L3/L4 the Phase heading uses the ancestor-aware path
     (### Phase `W01.P02` - ...). The intent sentence is mandatory. -->

<!-- WAVE BLOCK FORMAT (L3, L4):
     ## Wave `W01` - language-only convention rollout

     One paragraph stating what this Wave delivers, which downstream
     Wave depends on it, and which authorizing documents back it.

     ### Phase `W01.P01` - ...
     ### Phase `W01.P02` - ...

     The Wave intent paragraph is mandatory. -->

<!-- EPIC INTENT BLOCK FORMAT (L4 only):
     ## Epic intent

     One paragraph stating the strategic goal, the external project-
     management association (milestone name, project board identifier,
     roadmap entry), the timeline horizon, and the teams or agents
     involved.

     ## Wave `W01` - ...
     ## Wave `W02` - ...

     The ## Epic intent block is mandatory at L4 and absent at L1, L2,
     L3. The plan title (the level-one # heading at the top of the
     document) is the Epic title; no separate Epic heading is emitted. -->

## Parallelization

The phases carry hard ordering: P02 consumes the definitions P01 creates, and P03 and P04
advertise and document the descriptor P01 defines, so P01 must land first. Within P01,
S01-S04 are mostly independent definitions and may be authored together, but S05 (the unit
test) follows them. Within P02, S06-S09 all edit `store.py` and should be done as one
cohesive change, with S10 (parity test) closing the phase. P03's S11-S13 touch three
different surfaces and may proceed in parallel once P01 lands, with S14 verifying them.
P04's S15 (reference) is independent of the test steps and may be authored anytime after
the ADR; S16 follows P01/P02. Across the plan, the test steps (S05, S10, S14, S16) gate
their phase's completion.

## Verification

The plan is complete when every Step is closed and these criteria hold:

- One schema module exists and is the only place the version, payload shapes, and index
  tuples are defined; no `upsert`/`ensure` call site builds an inline payload dict or index
  list (verified by inspection and the drift test).
- The schema module imports no torch at module scope (verified by a fresh-interpreter
  import assertion, mirroring the index-worker lazy-import guard), so `/readiness` keeps its
  no-GPU guarantee.
- The reindex-parity test passes: points serialized through the TypedDicts equal the points
  the prior inline dicts produced for the same input (shape-preserving refactor).
- The drift test passes: a live `vault_docs` and `codebase_docs` collection's vector config
  and indexed payload fields equal the declared schema.
- `/readiness` carries the bounded `schema` descriptor (version, per-collection vectors and
  payload fields, models), and `/health` and `/service-state` carry the bare
  `schema_version` integer (verified by route tests).
- `assert_compatible` returns the defined verdicts across matching, newer-version, and
  dimension-mismatch inputs (unit test).
- The storage-schema reference document exists with the field tables, the version-bump
  policy, and the consumer compatibility recipe; `vaultspec-core vault check all` stays
  green.
- `just ci` (lint, basedpyright at zero, tests) is green on the branch.
