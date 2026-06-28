---
tags:
  - '#adr'
  - '#storage-schema-contract'
date: '2026-06-26'
modified: '2026-06-26'
related:
  - "[[2026-06-26-storage-schema-contract-research]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #adr) and one feature tag.
     Replace storage-schema-contract with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     Status convention: the H1 status value is one of proposed, accepted,
     rejected, or deprecated. A new ADR starts as proposed; it moves to
     accepted or rejected when the decision is made, and to deprecated
     when a later ADR supersedes it.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `storage-schema-contract` adr: `versioned typed runtime-advertised qdrant schema contract` | (**status:** `accepted`)

## Problem Statement

vaultspec-rag's Qdrant data shape — collection names, dense/sparse vector layout, the
per-point payload fields, the payload index set, and the point-ID scheme — is fully
implicit. It exists only as inline `dict` literals at each `upsert_*` call site and bare
constants in `store.py` and `embeddings.py`, with no version marker, no typed definition,
and no runtime advertisement. The cross-project service-management audit found that the
vaultspec-dashboard Rust engine reads embeddings **directly** out of Qdrant (its
`vectors.rs` scrolls the `dense` named vector at a hard-coded 1024 dimensions over the
discovered `storage_port`), bypassing rag's HTTP fence entirely. That out-of-process
consumer is coupled to an unversioned shape it cannot interrogate: a model swap, a vector
rename, a dimension change, or a payload restructure breaks it silently with no signal to
detect the drift. This ADR decides how rag codifies that shape into a single versioned,
typed, runtime-advertised contract so any consumer can assert compatibility before reading
and degrade honestly on a mismatch. It is the inward follow-on to the audit, grounded in
the `storage-schema-contract` research.

## Considerations

- The shape is **stable in practice but config-derivable**, not constant: `embedding_model`,
  `embedding_dimension`, and `sparse_model` are config keys, so `1024` is a default and the
  effective dimension can diverge from the code constant. The contract must advertise both a
  static shape **version** and the **effective** concrete values (dense dimension, distance,
  vector names, model IDs) read from the live config.
- The project already accepts this discipline elsewhere: the storage manifest is a
  versioned JSON artifact (`"version": 1`) with a frozen dataclass; survey/op results are
  frozen dataclasses with stable `--json` envelopes; `/readiness` is a typed, bounded,
  process-wide, read-only report (`ReadinessReport.to_dict()` → `{ready, server_mode, dependencies:[…]}`) governed by `operator-views-are-bounded` and
  `service-domain-owns-operability`. The contract mirrors these precedents rather than
  inventing a new pattern.
- The priority consumer is **out-of-process and cannot call rag Python**, so the contract's
  authority is the **wire descriptor** (JSON), not a Python API. rag's job is to advertise
  truthfully and document the consumer rules; rag cannot enforce assertion on a Rust reader.
- The payload is built on the **upsert hot path** (potentially thousands of points per
  batch), so the typed definition must add no construction cost over the dict that is
  already handed to `PointStruct(payload=…)`.
- `/readiness` is explicitly **torch-free and GPU-free** (safe to call before the runtime is
  up). Whatever builds the descriptor must stay a torch-free leaf depending only on config —
  it must not import the embedding model or touch CUDA.

## Constraints

- **Parent stability.** Depends on `store.py` (stable), `config.py` (stable), `_readiness.py`
  / `get_readiness` (stable, shipped), `get_service_state`, and the server route table — all
  on `main`. No frontier risk: this is a typing-and-exposure refactor over an existing,
  working store, not new infrastructure.
- The schema module must be a **neutral torch-free leaf** (the `_machine_lock.py` pattern):
  importable by both `store.py` and the server routes with no `store ↔ server` cycle and no
  torch import, so `/readiness` keeps its no-GPU guarantee.
- **Testing mandate:** drift is caught by a real-store test (no mocks) asserting the live
  collection's vector config and indexed payload fields equal the declared schema — so a
  future inline change that diverges from the typed definition fails CI.
- **No silent shape change.** The refactor must be shape-preserving: the typed payloads and
  index lists must serialize byte-for-byte the same points the inline dicts do today, or it
  is itself a breaking change. A reindex parity check guards this.
- The dashboard side is an **external cross-repo consumer**: rag ships the contract and the
  reference; the dashboard's adoption (reading the descriptor, asserting before scroll) is
  their work, tracked in the handover — out of scope here beyond publishing a stable wire
  shape and the compatibility rules.

## Implementation

Six decisions.

**D1 — A single integer `STORAGE_SCHEMA_VERSION`, starting at 1.** One module-level constant
(mirroring the manifest's `version: 1`) names the shape generation. It bumps **only** on a
breaking shape change: a vector rename or dimension/distance change, a payload field removal
or rename or type change, an index-set change that alters query semantics, or an ID-scheme
change. **Additive** payload fields (a new optional key) are non-breaking and do **not** bump
— a consumer that does not know a new field ignores it. Rejected: semver (heavier than the
project's integer precedent, invites minor/major bikeshedding) and per-collection versions
(vault and code share the vector/ID machinery; one version plus a per-collection effective
descriptor is simpler for the consumer).

**D2 — One schema module is the single source of truth, with `TypedDict` payloads replacing
the inline upsert dicts.** A new neutral leaf (e.g. `src/vaultspec_rag/store_schema.py`)
exports: `STORAGE_SCHEMA_VERSION`; the vector-name constants (`dense`, `sparse`) and distance;
a `TypedDict` per payload kind (vault doc, vault chunk, code chunk); the canonical payload
index field tuples (KEYWORD / INTEGER per collection); and a `describe_storage_schema()` that
builds the effective wire descriptor from the live config. `TypedDict` is chosen over a
dataclass precisely because the upsert path already produces a plain dict handed to
`PointStruct` — `TypedDict` types that exact shape at zero construction cost. `store.py`'s
`upsert_*` methods build their payloads as those `TypedDict`s, and `ensure_table` /
`ensure_code_table` consume the index tuples from this module instead of inline literals.
There is then exactly one place the shape is defined; the search path reads the same names.

**D3 — The wire descriptor is advertised on `/readiness`; a bare `schema_version` echoes on
`/health` and `/service-state` for a cheap pre-read gate.** `describe_storage_schema()` is
surfaced as a single bounded `schema` node in the readiness report: `{version, vault:{collection, vectors:{dense:{dim,distance}, sparse:true}, payload_fields[], indexes{}, id_scheme}, code:{…}, models:{dense, sparse}}`. Bounded per `operator-views-are-bounded` — a
fixed descriptor, never an open-ended dump. The full descriptor lives on `/readiness`
(process-wide, read-only, torch-free — the honest home for a process-wide shape). The bare
integer `schema_version` is additionally echoed on the ungated `/health` (the cheapest
pre-scroll gate, which the dashboard already calls for the token) and on `/service-state`
(which the dashboard already polls for freshness), so a consumer can precheck the version
without the full descriptor round-trip. CLI (`server doctor`) and the MCP readiness tool
inherit the descriptor through the shared `get_readiness` behavior per
`service-domain-owns-operability` — no adapter grows its own copy.

**D4 — Consumer compatibility semantics are defined as the contract (rag advertises; the
consumer asserts).** The reference codifies the rules a reader applies before scrolling:
(a) if `schema_version` exceeds the max the consumer was built against, **degrade** (the
shape may have changed beyond what it can parse) rather than read blind; (b) validate the
effective dense **dimension** against what it will deserialize — a mismatch is a hard refuse,
not a degrade, because wrong-size vectors are garbage; (c) confirm the `dense` vector **name**
exists in the descriptor before scrolling by it. This is the rag-side analog of the
dashboard's existing availability/`tiers` degradation: a contract mismatch reads the embedding
tier unavailable with a truthful reason, exactly as a stale heartbeat already does. rag ships
a small Python `assert_compatible()` helper for in-process / MCP / Python consumers; the Rust
reader applies the same rules against the JSON.

**D5 — An authored reference document is the human-facing contract.** A
`.vault/reference/` schema reference carries the collection/vector/payload tables, the D1
version-bump policy (what bumps, what does not), the D4 compatibility rules, and the consumer
recipe. Authored, not generated, in v1; a later generated-from-the-typed-definition reference
(mirroring the CLI reference generator) is a possible hardening, recorded not built.

**D6 — A breaking bump is handled by clean reindex, not a migration engine.** When
`STORAGE_SCHEMA_VERSION` bumps in a way that breaks the on-disk shape, recovery is
`reindex(clean=True)` — the store already drops and recreates the collection. No in-place
vector/payload migration engine is built; at this scale a rebuild is correct and simple.

## Rationale

The decisions follow from where the truth lives and who must read it (research F1–F8). The
shape is implicit but real and config-derivable (F1/F2), so the contract pairs a static
version with an effective descriptor. The project already versions the manifest and ships a
typed bounded readiness report (F4), so D1/D3 reuse established discipline instead of new
machinery. The priority consumer is out-of-process and blind (F3), so the authority is the
wire descriptor and the compatibility rules (D4), not a Python API it cannot call. `TypedDict`
(D2) satisfies the "replace the inline dicts with one typed definition" mandate while
respecting the upsert hot path. `/readiness` (D3) is the bounded, torch-free, process-wide
surface the mandate names, and the bare-version echoes give a cheap pre-read gate without
bloating the hot endpoints. Clean-reindex recovery (D6) matches the store's existing
drop-and-recreate behavior and the project's scale.

## Consequences

- **Gains.** The dashboard's direct-Qdrant read stops being a silent coupling: it can read
  `schema_version` and the effective dimension and refuse or degrade truthfully on drift,
  closing the audit's residual seam. rag gains one authoritative shape definition that the
  upsert path, the search path, the reference, and the wire all share, and a drift test that
  fails CI when an inline change diverges. Any future second-order consumer inherits the same
  guarantee for free.
- **Honest difficulties.** The refactor must be exactly shape-preserving — the typed payloads
  and index tuples must reproduce today's points byte-for-byte, or the very first version is
  itself a breaking change; a reindex parity check is mandatory, not optional. The
  config-derivable dimension means the descriptor must read live config, not the constant, or
  it lies under an override. The contract only protects consumers that actually read it — the
  dashboard adoption is cross-repo follow-up, not delivered here.
- **Pathways opened.** A stable schema descriptor is the seam every richer second-order
  semantic feature (clustering, similarity edges, cross-project embedding reads) builds on. It
  also enables a later generated reference and, if ever needed, a real migration path keyed on
  the version.
- **Pitfalls to avoid.** Letting the schema module import torch (breaks `/readiness`);
  advertising the constant dimension instead of the effective one; bumping the version for an
  additive field (needless consumer churn); or re-introducing an inline payload dict that
  bypasses the typed definition and silently re-opens the drift.

## Codification candidates

- **Rule slug:** `qdrant-payload-shape-is-defined-once`.
  **Rule:** Every Qdrant point payload and collection index set must be built from the typed
  definitions and constants in the single storage-schema module; never hand-write an inline
  payload dict or index list at an `upsert`/`ensure` call site, and bump
  `STORAGE_SCHEMA_VERSION` on any breaking shape change while leaving additive fields
  unversioned.

(Holds one full execution cycle before promotion, per the `vaultspec-codify` discipline.)
