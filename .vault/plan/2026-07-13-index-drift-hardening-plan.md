---
tags:
  - '#plan'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
tier: L2
related:
  - '[[2026-07-13-index-drift-hardening-adr]]'
  - '[[2026-07-13-index-drift-hardening-research]]'
---

# `index-drift-hardening` plan

### Phase `P01` - Config-epoch drift sentinels

Add the two-tier per-root config epoch (ADR D1-D3) to both indexers so membership drift forces an unscoped incremental and content drift forces a clean rebuild, self-escalating at every incremental entry.

- [x] `P01.S01` - Create the CPU-only config-epoch module: canonical serialization plus blake2b hashing of membership inputs (vaultragignore patterns, nested-gitignore signal, preprocess rule patterns) and content inputs (preprocess invocation fields, html_strip, and vault_chunk_chars for the vault tier), stdlib-only so the spawn worker import chain stays torch-free; `src/vaultspec_rag/indexer/_config_epoch.py`.
- [x] `P01.S02` - Stamp membership and content epoch keys in _write_meta, strip them in _load_meta, and check both in _incremental_index_locked before scoped dispatch: content mismatch escalates to _full_index_locked(clean=True), membership mismatch forces the unscoped incremental, legacy sidecars without the keys trigger one unscoped reconcile; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `P01.S03` - Mirror the content epoch over vault_chunk_chars beside _needs_layout_rebuild with clean-rebuild escalation and epoch stamping on successful writes; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [x] `P01.S04` - Unit-test the drift-class escalation matrix over real tmp roots: newly-ignored prune, newly-admitted pickup, preprocess pattern change forcing unscoped, html_strip and command change forcing clean rebuild, legacy sidecar unscoped-once, and scoped-path epoch cost staying rglob-free; `src/vaultspec_rag/tests/test_config_epoch.py`.

### Phase `P02` - Preprocess tri-state mode and TOFU trust store

Replace the blanket preprocess env gate with the tri-state mode and per-root resolved-rule-set trust store (ADR D4-D6); no backwards compatibility for the legacy enable knob.

- [x] `P02.S05` - Remove PREPROCESS_ENABLED outright (enum, override map, config field, default) and add the tri-state preprocess_mode resolved from VAULTSPEC_RAG_PREPROCESS and VAULTSPEC_RAG_PREPROCESS_TRUST_ALL with default meaning on-with-TOFU; `src/vaultspec_rag/config.py`.
- [x] `P02.S06` - Create the TOFU trust store: preprocess-trust.json sidecar under the managed status dir keyed by root collection prefix, canonical-JSON blake2b of the resolved rule set, atomic tmp-plus-replace writes under a lock, degrade-on-corrupt to untrusted, read/write/remove/hash helpers; `src/vaultspec_rag/indexer/_preprocess_trust.py`.
- [x] `P02.S07` - Enforce the mode in load_preprocess_rules after resolution: off returns empty, trust_all returns rules with a loud log, and default returns rules only on a trust-record hash match else empty plus a loud actionable warning naming the preprocess trust verb, with the loader and worker never prompting; `src/vaultspec_rag/indexer/_preprocess_config.py`.
- [x] `P02.S08` - Rework unit tests off the removed env knob onto the tri-state and trust store: loader enforcement per mode, hash stability across benign edits, hash change on command edits, corrupt-store degradation, status-dir isolation; `src/vaultspec_rag/tests/test_preprocess_config.py`.

### Phase `P03` - CLI trust verbs, server flags, operator visibility

Expose the tri-state and trust flow through the CLI and server start (ADR D7-D8): trust/untrust/status verbs, mode flags forwarded into the daemon env, and loud untrusted-config notices.

- [x] `P03.S09` - Add trust, untrust, and status verbs to the preprocess group: trust prints the resolved command set and confirms (auto-accept with --yes) then persists the record, untrust removes it, status reports mode, hash, and per-root trust state, all with --json envelopes; `src/vaultspec_rag/cli/_preprocess.py`.
- [x] `P03.S10` - Add --no-preprocess and --preprocess-trust-all to server start and the index/reindex verbs, forward the mode into the daemon env like --local-only, and print the untrusted-config notice with the remediation verb at server start; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P03.S11` - Cover the new verbs and flags: trust confirm and --yes flows, untrust, status JSON envelope, flag-to-env forwarding, and the reworked _enable_preprocess fixtures across the CLI test modules; `src/vaultspec_rag/tests/test_cli_preprocess.py`.

### Phase `P04` - Watcher fixes, integration proof, docs

Close the residual watcher gaps (ADR D9), prove the drift self-heal and TOFU enforcement end-to-end against real backends, and document the new behavior (ADR D10).

- [x] `P04.S12` - Re-resolve the preprocess config when .vaultragpreprocess.toml changes by admitting it in the change filter for that purpose only, and add .md to the watcher code-extension set to match the indexer language map; `src/vaultspec_rag/watcher.py`.
- [x] `P04.S13` - Prove the drift self-heal and TOFU enforcement end-to-end against real backends: an ignore-file edit prunes stale chunks on the next watcher or reindex run, an untrusted preprocess config skips with the loud warning while a trusted one executes, and the trust store isolates via the status-dir knob; `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`.
- [x] `P04.S14` - Document the tri-state, the trust flow, and the drift-epoch self-healing in the README and the server start help text, replacing every mention of the removed enable knob; `README.md`.

## Description

Implements the accepted `index-drift-hardening` ADR (D1-D10), grounded in the
same-day research. Two halves land as one feature. First, a two-tier per-root
config epoch in the index meta sidecars makes index-shaping configuration drift a
dependable, self-healing reindex signal: membership drift (ignore-file and
preprocess-pattern edits) forces the unscoped incremental whose set arithmetic
prunes newly-ignored and admits newly-un-ignored files, while content drift
(preprocess invocation fields, `html_strip`, `vault_chunk_chars`) escalates to a
clean rebuild, checked at every incremental entry beside the existing embed-schema
sentinel. Second, preprocess hooks flip on by default under per-root
trust-on-first-use: a status-dir trust store keyed on the blake2b of the resolved
rule set, tri-state control (`default`, `trust_all`, `off`) with env and CLI
parity modeled on `local_only`, trust/untrust/status CLI verbs, loud
skip-warnings on daemon paths, and no backwards compatibility for the removed
`VAULTSPEC_RAG_PREPROCESS_ENABLED` knob (owner decision at ADR approval).

## Steps

## Parallelization

`P01` and `P02` are independent of each other and may run in parallel: the epoch
sentinel touches the indexers and a new epoch module, while the tri-state and
trust store touch config and the preprocess loader. Within `P01`, `S01` precedes
`S02` and `S03` (both consume the epoch module); `S04` closes the phase. Within
`P02`, `S05` and `S06` may run in parallel and both precede `S07`; `S08` closes
the phase. `P03` hard-depends on `P02` (the verbs and flags drive the trust store
and mode). `P04` hard-depends on `P01` through `P03`: the integration proof
(`S13`) exercises the epoch self-heal and the TOFU enforcement together, and the
docs step (`S14`) documents the final surface.

## Verification

- The drift-class escalation matrix from the research holds in unit tests over
  real tmp roots: an ignore edit prunes on the next incremental entry without a
  clean rebuild, a preprocess command edit forces the clean rebuild, and a legacy
  sidecar triggers exactly one unscoped reconcile.
- The scoped watcher path performs no extra full-tree walk per run (epoch inputs
  are root control files and config knobs only).
- With no env set and no trust record, indexing a root with a preprocess config
  executes nothing and emits the loud warning naming the trust verb; after
  `preprocess trust`, the same index run executes the commands; editing a command
  reverts the root to untrusted.
- `VAULTSPEC_RAG_PREPROCESS=off` and `--no-preprocess` load zero rules;
  `VAULTSPEC_RAG_PREPROCESS_TRUST_ALL=1` and `--preprocess-trust-all` bypass the
  trust check loudly; no reference to `VAULTSPEC_RAG_PREPROCESS_ENABLED` remains
  in src, tests, or docs.
- Full gate green locally: ruff, ty, basedpyright, unit suite, and the
  integration suite including GPU tests (no GPU CI; run locally before merge).
- Every Step row is closed and each has a Step Record under the exec folder;
  vaultspec-code-review passes with an audit artifact.
