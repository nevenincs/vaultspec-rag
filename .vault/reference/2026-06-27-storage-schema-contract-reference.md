---
tags:
  - '#reference'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-06-27'
related:
  - "[[2026-06-26-storage-schema-contract-adr]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #reference) and one feature tag.
     Replace storage-schema-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `storage-schema-contract` reference: `qdrant storage schema contract`

The machine-facing contract for vaultspec-rag's Qdrant data shape. A consumer that
reads the store directly (notably the vaultspec-dashboard engine's direct-Qdrant
embedding scroll) builds against this document: the collection layout, the vector and
payload shapes, the version-bump policy, where the contract is advertised at runtime,
and the compatibility rules to apply before reading. The single source of truth in code
is `src/vaultspec_rag/store_schema.py`; this reference describes it. When the two
disagree, the module wins and this document is stale.

## Summary

The shape is one version integer plus an effective descriptor. `STORAGE_SCHEMA_VERSION`
(currently `1`) names the shape generation; the runtime descriptor pairs it with the
EFFECTIVE concrete values (dense dimension, model identity) read live from config, because
an operator may override `embedding_dimension` or swap the model. A consumer reads the
version to know "is the shape one I understand" and the effective block to know "are the
concrete dimensions what I will deserialize".

### Collections and namespacing

Two collections: `vault_docs` and `codebase_docs`. In server mode one shared Qdrant hosts
every workspace, so each collection name gains a stable per-root prefix matching
`^r[0-9a-f]{12}_$` (a `blake2b` digest of the resolved, case-normalised root). A consumer
matches a collection by the suffix (`vault_docs` / `codebase_docs`), not the whole name. In
local mode the names are bare.

### Vectors

Each collection carries one dense named vector and one sparse named vector:

| Vector | Name     | Type        | Params                                                 |
| ------ | -------- | ----------- | ------------------------------------------------------ |
| dense  | `dense`  | float dense | size = effective dim (default 1024), distance `Cosine` |
| sparse | `sparse` | SPLADE      | qdrant sparse vector                                   |

The dense default dimension is the Qwen3-Embedding-0.6B default (1024). The EFFECTIVE
dimension is the value in the runtime descriptor; validate against that, not the default.
The collection always carries the `sparse` slot, so the descriptor's `vectors.sparse` is
always present; when sparse encoding is disabled in config the descriptor's
`models.sparse` is `null` while the slot remains - read `models.sparse` to know whether
sparse vectors are actually populated.

### Payload fields

Vault document point (`vault_docs`, document-level): `doc_id`, `path`, `doc_type`,
`feature`, `date`, `tags`, `related`, `title`, `status`, `content`.

Vault chunk point (`vault_docs`, chunk-level): `doc_id`, `chunk_ordinal`, `chunk_count`,
`path`, `doc_type`, `feature`, `date`, `tags`, `related`, `title`, `status`, `content`, and
`doc_content` (present only on the ordinal-0 chunk).

Code chunk point (`codebase_docs`): `chunk_id`, `path`, `language`, `content`, `line_start`,
`line_end`, `node_type`, `function_name`, `class_name`, `source_path`, `preprocessor_id`,
`anchor`, `locator_kind`, `locator_value_int`, `locator_value_str`, `locator_end_int`,
`locator_end_str`. The `source_path`-through-`locator_end_str` fields are `null` for ordinary
code chunks and carry a preprocessed source's own addressing scheme when present.

### Payload indexes

Server-mode only (a local-mode Qdrant ignores payload indexes). Vault: KEYWORD on
`doc_type`, `feature`, `date`, `tags`, `doc_id`; INTEGER on `chunk_ordinal`. Code: KEYWORD
on `path`, `language`, `function_name`, `class_name`, `node_type`, `preprocessor_id`,
`locator_kind`, `locator_value_str`; INTEGER on `line_start`, `locator_value_int`.

### Point IDs

The stored Qdrant point id is a stable hash of a string key. The string key is: the document
stem (relative path without extension) for a vault document; `{doc_id}#c{ordinal}` for a
vault chunk; the chunk id for a code chunk.

### Version-bump policy

`STORAGE_SCHEMA_VERSION` bumps ONLY on a breaking shape change:

- a vector rename, or a dense dimension / distance change;
- a payload field removal, rename, or type change;
- a payload-index-set change that alters query semantics;
- a point-ID-scheme change.

An ADDITIVE payload field (a new optional key) is non-breaking and does NOT bump - a consumer
that does not know a new field ignores it. So "version unchanged" guarantees the fields you
already read are unchanged, not that no field was added.

### Runtime advertisement

The contract is read at runtime from the resident service:

- `GET /readiness` - the full descriptor under the `schema` key: `{version, vault:{collection, vectors, payload_fields, indexes, id_scheme}, code:{...}, models:{dense, sparse}}`. Read-only,
  process-wide, torch-free. This is the authoritative source for the effective dimension.
- `GET /health` (ungated) and `GET /service-state` - a bare `schema_version` integer, the
  cheapest pre-read gate; check it before deciding to fetch the full descriptor.

### Consumer compatibility recipe

Before a direct read, apply these rules (the Python reference implementation is
`store_schema.assert_compatible`; a non-Python consumer applies the same logic to the JSON):

- Read `schema_version` (or the descriptor's `version`). If it is GREATER than the newest
  version you were built against, DEGRADE - do not read blind; the shape may have changed
  beyond what you can parse. Older or equal is compatible.
- Read the effective dense `dim` from the `/readiness` descriptor. If it does NOT EQUAL the
  dimension you will deserialize, REFUSE (hard) - wrong-size vectors are garbage, not a
  degrade.
- Confirm a dense vector named `dense` exists in the descriptor before scrolling by it.

On any mismatch, surface the embedding tier as unavailable with a truthful reason - the same
degradation path a stale service heartbeat already takes - rather than reading and returning
garbage.

### Recovery on a breaking bump

There is no in-place migration engine. A version bump that breaks the on-disk shape is
recovered by a clean reindex (the store drops and recreates the collection). At this scale a
rebuild is the correct and simple path.

### Source and tests

The contract is defined once in `src/vaultspec_rag/store_schema.py` and consumed by the
upsert and ensure paths in `src/vaultspec_rag/store.py`. The shape-preserving guarantee is
held by `test_store_schema_parity.py` (golden payload shapes, CI unit gate), the internal
invariants by `test_store_schema.py` (indexes name real fields), the runtime advertisement by
`test_server_routes.py`, and the live-collection vector config by `test_store_schema_drift.py`.
