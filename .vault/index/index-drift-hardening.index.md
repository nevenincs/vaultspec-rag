---
generated: true
tags:
  - '#index'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
related:
  - '[[2026-07-13-index-drift-hardening-P01-S01]]'
  - '[[2026-07-13-index-drift-hardening-P01-S02]]'
  - '[[2026-07-13-index-drift-hardening-P01-S03]]'
  - '[[2026-07-13-index-drift-hardening-P01-S04]]'
  - '[[2026-07-13-index-drift-hardening-P01-summary]]'
  - '[[2026-07-13-index-drift-hardening-P02-S05]]'
  - '[[2026-07-13-index-drift-hardening-P02-S06]]'
  - '[[2026-07-13-index-drift-hardening-P02-S07]]'
  - '[[2026-07-13-index-drift-hardening-P02-S08]]'
  - '[[2026-07-13-index-drift-hardening-P02-summary]]'
  - '[[2026-07-13-index-drift-hardening-P03-S09]]'
  - '[[2026-07-13-index-drift-hardening-P03-S10]]'
  - '[[2026-07-13-index-drift-hardening-P03-S11]]'
  - '[[2026-07-13-index-drift-hardening-P03-summary]]'
  - '[[2026-07-13-index-drift-hardening-P04-S12]]'
  - '[[2026-07-13-index-drift-hardening-P04-S13]]'
  - '[[2026-07-13-index-drift-hardening-P04-S14]]'
  - '[[2026-07-13-index-drift-hardening-P04-summary]]'
  - '[[2026-07-13-index-drift-hardening-adr]]'
  - '[[2026-07-13-index-drift-hardening-audit]]'
  - '[[2026-07-13-index-drift-hardening-plan]]'
  - '[[2026-07-13-index-drift-hardening-research]]'
---

# `index-drift-hardening` feature index

Auto-generated index of all documents tagged with `#index-drift-hardening`.

## Documents

### adr

- `2026-07-13-index-drift-hardening-adr` - `index-drift-hardening` adr: `config-epoch drift sentinel and preprocess TOFU default` | (**status:** `accepted`)

### audit

- `2026-07-13-index-drift-hardening-audit` - `index-drift-hardening` audit: `feature code review and closeout`

### exec

- `2026-07-13-index-drift-hardening-P01-S01` - Create the CPU-only config-epoch module: canonical serialization plus blake2b hashing of membership inputs (vaultragignore patterns, nested-gitignore signal, preprocess rule patterns) and content inputs (preprocess invocation fields, html_strip, and vault_chunk_chars for the vault tier), stdlib-only so the spawn worker import chain stays torch-free
- `2026-07-13-index-drift-hardening-P01-S02` - Stamp membership and content epoch keys in \_write_meta, strip them in \_load_meta, and check both in \_incremental_index_locked before scoped dispatch: content mismatch escalates to \_full_index_locked(clean=True), membership mismatch forces the unscoped incremental, legacy sidecars without the keys trigger one unscoped reconcile
- `2026-07-13-index-drift-hardening-P01-S03` - Mirror the content epoch over vault_chunk_chars beside \_needs_layout_rebuild with clean-rebuild escalation and epoch stamping on successful writes
- `2026-07-13-index-drift-hardening-P01-S04` - Unit-test the drift-class escalation matrix over real tmp roots: newly-ignored prune, newly-admitted pickup, preprocess pattern change forcing unscoped, html_strip and command change forcing clean rebuild, legacy sidecar unscoped-once, and scoped-path epoch cost staying rglob-free
- `2026-07-13-index-drift-hardening-P01-summary` - `index-drift-hardening` `P01` summary
- `2026-07-13-index-drift-hardening-P02-S05` - Remove PREPROCESS_ENABLED outright (enum, override map, config field, default) and add the tri-state preprocess_mode resolved from VAULTSPEC_RAG_PREPROCESS and VAULTSPEC_RAG_PREPROCESS_TRUST_ALL with default meaning on-with-TOFU
- `2026-07-13-index-drift-hardening-P02-S06` - Create the TOFU trust store: preprocess-trust.json sidecar under the managed status dir keyed by root collection prefix, canonical-JSON blake2b of the resolved rule set, atomic tmp-plus-replace writes under a lock, degrade-on-corrupt to untrusted, read/write/remove/hash helpers
- `2026-07-13-index-drift-hardening-P02-S07` - Enforce the mode in load_preprocess_rules after resolution: off returns empty, trust_all returns rules with a loud log, and default returns rules only on a trust-record hash match else empty plus a loud actionable warning naming the preprocess trust verb, with the loader and worker never prompting
- `2026-07-13-index-drift-hardening-P02-S08` - Rework unit tests off the removed env knob onto the tri-state and trust store: loader enforcement per mode, hash stability across benign edits, hash change on command edits, corrupt-store degradation, status-dir isolation
- `2026-07-13-index-drift-hardening-P02-summary` - `index-drift-hardening` `P02` summary
- `2026-07-13-index-drift-hardening-P03-S09` - Add trust, untrust, and status verbs to the preprocess group: trust prints the resolved command set and confirms (auto-accept with --yes) then persists the record, untrust removes it, status reports mode, hash, and per-root trust state, all with --json envelopes
- `2026-07-13-index-drift-hardening-P03-S10` - Add --no-preprocess and --preprocess-trust-all to server start and the index/reindex verbs, forward the mode into the daemon env like --local-only, and print the untrusted-config notice with the remediation verb at server start
- `2026-07-13-index-drift-hardening-P03-S11` - Cover the new verbs and flags: trust confirm and --yes flows, untrust, status JSON envelope, flag-to-env forwarding, and the reworked \_enable_preprocess fixtures across the CLI test modules
- `2026-07-13-index-drift-hardening-P03-summary` - `index-drift-hardening` `P03` summary
- `2026-07-13-index-drift-hardening-P04-S12` - Re-resolve the preprocess config when .vaultragpreprocess.toml changes by admitting it in the change filter for that purpose only, and add .md to the watcher code-extension set to match the indexer language map
- `2026-07-13-index-drift-hardening-P04-S13` - Prove the drift self-heal and TOFU enforcement end-to-end against real backends: an ignore-file edit prunes stale chunks on the next watcher or reindex run, an untrusted preprocess config skips with the loud warning while a trusted one executes, and the trust store isolates via the status-dir knob
- `2026-07-13-index-drift-hardening-P04-S14` - Document the tri-state, the trust flow, and the drift-epoch self-healing in the README and the server start help text, replacing every mention of the removed enable knob
- `2026-07-13-index-drift-hardening-P04-summary` - `index-drift-hardening` `P04` summary

### plan

- `2026-07-13-index-drift-hardening-plan` - `index-drift-hardening` plan

### research

- `2026-07-13-index-drift-hardening-research` - `index-drift-hardening` research: `config-drift signals and preprocess-on-by-default`
