---
generated: true
tags:
  - '#index'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
related:
  - '[[2026-06-26-storage-schema-contract-adr]]'
  - '[[2026-06-26-storage-schema-contract-research]]'
  - '[[2026-06-27-storage-schema-contract-P01-S01]]'
  - '[[2026-06-27-storage-schema-contract-P01-S02]]'
  - '[[2026-06-27-storage-schema-contract-P01-S03]]'
  - '[[2026-06-27-storage-schema-contract-P01-S04]]'
  - '[[2026-06-27-storage-schema-contract-P01-S05]]'
  - '[[2026-06-27-storage-schema-contract-P02-S06]]'
  - '[[2026-06-27-storage-schema-contract-P02-S07]]'
  - '[[2026-06-27-storage-schema-contract-P02-S08]]'
  - '[[2026-06-27-storage-schema-contract-P02-S09]]'
  - '[[2026-06-27-storage-schema-contract-P02-S10]]'
  - '[[2026-06-27-storage-schema-contract-P03-S11]]'
  - '[[2026-06-27-storage-schema-contract-P03-S12]]'
  - '[[2026-06-27-storage-schema-contract-P03-S13]]'
  - '[[2026-06-27-storage-schema-contract-P03-S14]]'
  - '[[2026-06-27-storage-schema-contract-P04-S15]]'
  - '[[2026-06-27-storage-schema-contract-P04-S16]]'
  - '[[2026-06-27-storage-schema-contract-audit]]'
  - '[[2026-06-27-storage-schema-contract-plan]]'
  - '[[2026-06-27-storage-schema-contract-reference]]'
---

# `storage-schema-contract` feature index

Auto-generated index of all documents tagged with `#storage-schema-contract`.

## Documents

### adr

- `2026-06-26-storage-schema-contract-adr` - `storage-schema-contract` adr: `versioned typed runtime-advertised qdrant schema contract` | (**status:** `accepted`)

### audit

- `2026-06-27-storage-schema-contract-audit` - `storage-schema-contract` audit: `code review verification`

### exec

- `2026-06-27-storage-schema-contract-P01-S01` - Define STORAGE_SCHEMA_VERSION, the dense/sparse vector-name and distance constants, and the TypedDict payload shapes for vault doc, vault chunk, and code chunk
- `2026-06-27-storage-schema-contract-P01-S02` - Declare the canonical KEYWORD and INTEGER payload-index field tuples per collection
- `2026-06-27-storage-schema-contract-P01-S03` - Implement describe_storage_schema building the effective config-derived wire descriptor without importing torch
- `2026-06-27-storage-schema-contract-P01-S04` - Implement assert_compatible applying the version, dense-dimension, and dense-vector-name rules
- `2026-06-27-storage-schema-contract-P01-S05` - Unit-test the descriptor shape and the compatibility helper across match and mismatch cases
- `2026-06-27-storage-schema-contract-P02-S06` - Build vault document and vault chunk payloads from the TypedDicts in the upsert paths
- `2026-06-27-storage-schema-contract-P02-S07` - Build code chunk payloads from the TypedDict in the code upsert path
- `2026-06-27-storage-schema-contract-P02-S08` - Consume the schema index tuples in ensure_table and ensure_code_table instead of inline literals
- `2026-06-27-storage-schema-contract-P02-S09` - Source the dense vector params (name, default dimension, distance) from the schema module in collection create
- `2026-06-27-storage-schema-contract-P02-S10` - Add a reindex-parity integration test asserting points serialize byte-for-byte unchanged
- `2026-06-27-storage-schema-contract-P03-S11` - Add the bounded schema descriptor node to the readiness report to_dict
- `2026-06-27-storage-schema-contract-P03-S12` - Echo the bare schema_version on the raw /health payload
- `2026-06-27-storage-schema-contract-P03-S13` - Echo the bare schema_version on the get_service_state snapshot
- `2026-06-27-storage-schema-contract-P03-S14` - Add server-route tests asserting the schema descriptor on /readiness and the version echo on /health and /service-state
- `2026-06-27-storage-schema-contract-P04-S15` - Author the storage-schema reference document with the field tables, version-bump policy, and consumer compatibility recipe
- `2026-06-27-storage-schema-contract-P04-S16` - Add a real-store drift test asserting the live collection vector config and indexed payload fields equal the declared schema

### plan

- `2026-06-27-storage-schema-contract-plan` - `storage-schema-contract` plan

### reference

- `2026-06-27-storage-schema-contract-reference` - `storage-schema-contract` reference: `qdrant storage schema contract`

### research

- `2026-06-26-storage-schema-contract-research` - `storage-schema-contract` research: `versioned typed runtime-advertised qdrant schema contract`
