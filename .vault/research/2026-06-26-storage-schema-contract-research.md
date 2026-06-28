---
tags:
  - '#research'
  - '#storage-schema-contract'
date: '2026-06-26'
modified: '2026-06-26'
related: []
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #research) and one feature tag.
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

# `storage-schema-contract` research: `versioned typed runtime-advertised qdrant schema contract`

The vaultspec-rag Qdrant store is the substrate the dashboard's Rust engine reads
embeddings from directly (its `vectors.rs` scrolls the `dense` named vector at 1024
dimensions, bypassing rag's HTTP fence). That read is built against an **implicit,
unversioned schema** that lives as inline dictionaries and bare constants in `store.py`:
a model swap, a vector rename, a dimension change, or a payload-field restructure breaks
the consumer silently, with no version signal to detect drift. This research grounds the
current schema surface, maps who is coupled to it, separates what is already codified
from what is not, and weighs the options for a single versioned, typed, runtime-advertised
schema contract so a consumer can assert compatibility before reading and degrade honestly
on a mismatch. It is the inward follow-on to the cross-project service-management audit
(the dashboard direct-Qdrant coupling was that audit's residual seam).

## Findings

### F1 — The current schema is real, stable in practice, but entirely implicit

The Qdrant data shape is fully determined by code in `store.py` and the model identity in
`embeddings.py`, with no schema-version marker anywhere:

- **Collections** (`store.py`): `vault_docs` (`TABLE_NAME`) and `codebase_docs`
  (`CODE_TABLE_NAME`), per-root namespaced in server mode by an `r{hash}_` prefix
  (`blake2b` digest_size=6).
- **Vectors**: one dense named vector `dense` (`size = EMBEDDING_DIM = 1024`, distance
  `COSINE`) plus one sparse named vector `sparse` (`SparseVectorParams`). The `1024`
  is the Qwen3-Embedding-0.6B default; the dense model is `Qwen/Qwen3-Embedding-0.6B`
  and sparse is `naver/splade-v3` (`embeddings.py` `MODEL_NAME` / `SPARSE_MODEL_NAME` /
  `DEFAULT_DIMENSION`).
- **Vault payload** (per chunk): `chunk_ordinal`, `chunk_count`, `path`, `doc_type`,
  `feature`, `date`, `tags`, `related`, `title`, `status`, `content`, and optionally
  `doc_content`. The doc-level upsert writes the same field family plus `doc_id`.
- **Code payload** (per chunk): `chunk_id`, `path`, `language`, `content`, `line_start`,
  `line_end`, `node_type`, `function_name`, `class_name`, `source_path`,
  `preprocessor_id`, `anchor`, `locator_kind`, `locator_value_int`, `locator_value_str`,
  `locator_end_int`, `locator_end_str`.
- **Payload indexes**: vault `KEYWORD` on `doc_type`, `feature`, `date`, `tags`,
  `doc_id` and `INTEGER` on `chunk_ordinal`; code `KEYWORD` on `path`, `language`,
  `function_name`, `class_name`, `node_type`, `preprocessor_id`, `locator_kind`,
  `locator_value_str` and `INTEGER` on `line_start`, `locator_value_int`.
- **Point IDs**: vault chunk `doc_id#c{ordinal}`, code chunk the chunk `id`, both hashed
  through `_stable_id`; vault `doc_id` is the relative path without extension.

None of this is exported as a typed contract, a version, or a reference document. The
payloads are constructed as inline `dict` literals at each `upsert_*` call site — the
shape exists only as the union of those literals plus the index-creation lists.

### F2 — The schema is config-derivable, not purely constant — the contract must advertise effective values

`config.py` carries `embedding_model`, `embedding_dimension`, `sparse_model`,
`sparse_enabled`, `dense_backend`. So `EMBEDDING_DIM` is a *default*, not a guarantee:
an operator who overrides `embedding_dimension` (or swaps the model) changes the on-disk
vector size while the code constant still reads `1024`. A static `STORAGE_SCHEMA_VERSION`
captures the *shape* (vector names, payload field set, ID scheme), but the contract must
*also* surface the **effective** dense dimension, distance, vector names, and model IDs
read from the live config — because that is what a direct-Qdrant consumer actually needs
to validate a scroll against. Version answers "is the shape one I understand"; the
effective block answers "are the concrete dimensions what I will deserialize."

### F3 — Consumer coupling: three readers, one of them out-of-process and blind

- **Dashboard engine (out-of-process, the priority case)**: `vectors.rs` opens Qdrant
  directly on the `storage_port` discovered from `service.json` and scrolls the `dense`
  vector at a hard-coded 1024. It never calls rag Python. It has **no way today** to
  learn the schema version or effective dimension; it assumes them. This is the seam the
  contract must close first.
- **rag's own searcher** (`search/_searcher.py`): in-process, moves in lockstep with the
  store, so it is not at drift risk — but it is the reference implementation of "what the
  payload means" and should consume the same typed payload definitions so the contract
  has exactly one source of truth.
- **Storage survey / manifest** (`storage_survey.py`, `storage_manifest.py`): already
  reasons about collections by prefix; the manifest is the one piece that *is* versioned
  (`"version": 1`) and is the precedent to follow.

### F4 — What is already codified (the precedents to mirror)

- The storage **manifest** is a versioned, persisted JSON artifact with a frozen
  `ManifestEntry` dataclass — proof the project already accepts an explicit `version:`
  integer on a storage-side contract.
- Survey/op results are **frozen dataclasses** (`NamespaceSurvey`, `DeleteResult`,
  `PruneResult`, `MigrateResult`) with stable `--json` envelopes.
- The **namespace prefix** is an anchored regex contract (`^r[0-9a-f]{12}_$`).
- `/readiness` already returns a **typed, bounded** report: `ReadinessReport.to_dict()`
  yields `{ready, server_mode, dependencies:[{name,status,detail,info}]}`, with a small
  `ReadinessStatus` StrEnum vocabulary, and it is explicitly process-wide, read-only, and
  "bounded — never accretes into a general health console" per the
  `operator-views-are-bounded` rule.

The gap is therefore narrow and well-precedented: apply the manifest's versioning
discipline and the readiness report's typed/bounded exposure discipline to the
collection/vector/payload shape that currently has neither.

### F5 — Design axis A: versioning scheme

- **Single integer `STORAGE_SCHEMA_VERSION`** (mirrors the manifest's `version: 1`).
  Simplest; matches existing precedent; a consumer asserts `>= N` or `== N`. Bump on any
  breaking shape change (vector rename/dim change, payload field removal/rename, ID-scheme
  change). Additive payload fields are non-breaking and do **not** bump.
- *Semver string* — finer signal (major=breaking, minor=additive) but heavier than the
  project's established integer-version precedent and invites bikeshedding about what is
  "minor."
- *Per-collection versions* — vault and code shapes can evolve independently, so two
  versions is defensible; but they share the vector/ID machinery, and a single version
  with a per-collection effective block is simpler for the consumer. **Leaning: single
  integer + effective per-collection descriptor.**

### F6 — Design axis B: typing the payload (replace the inline dicts)

The mandate's "typed payload definition that replaces the inline upsert dicts" wants one
authoritative definition the upsert path, the search path, and the contract all import.

- **`@dataclass(frozen=True)`** (or `TypedDict`) per payload kind (vault doc, vault chunk,
  code chunk), with a `to_payload()`/`as_dict()` serializer the `upsert_*` methods call
  instead of building literals. Matches the project's dataclass-heavy idiom
  (`NamespaceSurvey`, readiness nodes) and the no-Pydantic-on-the-hot-path leaning.
  `TypedDict` is lighter (no construction cost, just a typed shape over the existing dict)
  and may be the better fit for the upsert hot path where the dict is handed straight to
  `PointStruct(payload=...)`.
- The field **names** become the contract surface; the typed definition is what the
  reference doc and the version are generated from / checked against. A test asserts the
  live collection's indexed fields and the typed definition agree, so drift fails CI.
- Caution (`no-dev-metadata-in-code`): the definitions state the field contract, not ADR
  IDs.

### F7 — Design axis C: runtime exposure surface

The contract must be *advertised* so an out-of-process consumer can read it before
scrolling.

- **`/readiness` (the mandate's target)**: already process-wide, read-only, typed,
  bounded, and brokered. Adding a `schema` block (version + per-collection effective
  vector/payload descriptor) fits its "tell the consumer what is provisioned" purpose.
  Risk: `operator-views-are-bounded` / "never accretes into a general health console" —
  the addition must be a single bounded `schema` node, not an open-ended dump. Acceptable
  if scoped to {version, vault:{vectors,dim,distance,payload_fields,id_scheme},
  code:{...}, models:{dense,sparse}}.
- *`/service-state`* is **project-scoped** (takes `project_root`); the schema is
  process-wide, so `/readiness` is the more honest home. But `/service-state` is what the
  dashboard already polls for freshness — a thin `schema_version` echo there may be
  ergonomic. **Leaning: full descriptor on `/readiness`; optionally a bare
  `schema_version` int on `/service-state` and `/health` for a cheap precheck.**
- The CLI (`server doctor` / a `server storage schema` read) and the MCP readiness tool
  inherit the same shared behavior per `service-domain-owns-operability` — no adapter
  grows its own copy.

### F8 — Design axis D: compatibility semantics the consumer applies

The contract is only useful if "assert compatibility before reading and degrade honestly"
has defined rules:

- Consumer reads `schema_version`; if it is **greater** than the max the consumer knows,
  degrade (the shape may have changed in a way it cannot parse) rather than scroll blind.
- Consumer validates the **effective dense dimension** against what it will deserialize;
  a mismatch is a hard "do not read" (wrong-size vectors are garbage, not degraded).
- Consumer checks the **dense vector name** (`dense`) exists in the descriptor before
  scrolling by it.
- This is the rag-side analog of the dashboard's existing `tiers`/availability degradation:
  on any contract mismatch the dashboard's embedding tier reads unavailable with a truthful
  reason, exactly as it already does for a stale heartbeat.

### F9 — Reference document

`operator-views-are-bounded` and `generated-reference-is-cli-owned` set the precedent that
machine-facing references can be partly generator-owned. The schema reference
(`.vault/reference/yyyy-mm-dd-storage-schema-contract-reference.md`) should be the
human-facing contract: the collection/vector/payload tables, the version-bump policy
(what bumps, what does not), the compatibility rules from F8, and the consumer recipe. It
is authored, not generated, in v1; a generated-from-the-typed-definition reference is a
possible later hardening (mirroring the CLI reference generator) but is not required to
ship the contract.

### F10 — Scope boundaries and non-goals

- **In scope**: the version constant, the typed payload definitions replacing the inline
  dicts, the effective-values descriptor, `/readiness` exposure (+ optional bare echo on
  `/service-state`/`/health`), the reference doc, and tests that fail on drift.
- **Out of scope**: a migration engine for old collections (a version bump that breaks
  shape is handled by `reindex(clean=True)` — the store already drops/recreates; no
  in-place vector migration is warranted at this scale), changing the actual model/dim,
  and brokering the storage *management* surface to the dashboard (that is the sibling
  "broker the storage surface" item, a separate ADR).
- **Open question for the ADR**: `dataclass` vs `TypedDict` for the payload definitions
  (hot-path construction cost vs. richer typing), and whether `/service-state` carries the
  bare `schema_version` echo or the descriptor lives on `/readiness` only.
