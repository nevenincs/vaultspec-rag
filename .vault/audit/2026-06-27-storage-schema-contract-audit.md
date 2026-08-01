---
tags:
  - '#audit'
  - '#storage-schema-contract'
date: '2026-06-27'
modified: '2026-07-03'
body_hash: 'sha256:c5defabeebce3f518cb55a5cf04fe66853629dbbe99e1e3136c28ce0ef97db51'
related:
  - "[[2026-06-27-storage-schema-contract-plan]]"
---

# `storage-schema-contract` audit: `code review verification`

## Scope

Verify-phase review of the `storage-schema-contract` feature: the new
`store_schema.py` contract module, the `store.py` upsert/ensure refactor, the
`/readiness` / `/health` / `/service-state` runtime exposure, and the five test
files. The review compared every payload builder and the collection-create path
against the pre-refactor inline literals to confirm the refactor is byte-for-byte
shape-preserving, checked the torch-free invariant, validated `assert_compatible`,
and audited project-convention compliance. Verdict: ship.

## Findings

- **Shape preservation (highest priority): PASS.** The three payload builders
  reproduce the prior inline dicts key-for-key, in the same order, with the
  ordinal-0 `doc_content` conditional intact; the vector config resolves
  `Cosine` to the `COSINE` distance exactly; the index tuples equal the prior
  literals; no upsert/ensure site bypasses the module.
- **Torch-free invariant: PASS.** The contract module imports only `typing` at
  module scope; config is read lazily; a fresh-interpreter import leaves torch
  out of `sys.modules`.
- **`assert_compatible`: PASS.** The version/dimension/vector-name rules and the
  dict-narrowing helper match the contract; a malformed descriptor yields an
  incompatible verdict rather than raising.
- **Conventions: PASS.** No mocks/patches/skips; production code states
  constraints without dev-metadata identifiers.
- **Medium (addressed): descriptor dimension vs collection dimension source
  split.** The descriptor read `embedding_dimension` from config while the
  collection was always built from the bare constant, so under a config override
  the advertised dimension could diverge from the live collection - the
  "descriptor lies under an override" pitfall the ADR named.
- **Low (addressed): a per-point `dict()` copy** on the upsert hot path, a shared
  vector-dict aliased between the vault and code descriptor blocks, and ADR-id
  citations in three new test docstrings.

## Recommendations

All actionable findings were fixed in the same feature branch before merge:

- Promoted the dense-dimension resolver to the public
  `store_schema.effective_dense_dim()` and wired `VaultStore`'s collection-build
  default to it, so the advertised dimension equals the live collection's by
  construction under any config; added a drift assertion that the store's build
  dim and the descriptor source are one function.
- Replaced the per-point `dict()` copy with a zero-cost `cast`, gave each
  descriptor collection block a fresh vector dict, and removed the ADR-id
  citations from the new test docstrings.
- Documented the always-present sparse slot vs config-disabled sparse model in
  the reference.

The remaining Low (the wire descriptor advertises the bare collection suffix
without the server-mode `r{hash}_` prefix hint) is acknowledged and covered by
the reference's suffix-match note; no code change.

## Codification candidates

- **Source:** the ADR's accepted decision plus the shape-preservation finding.
  **Rule slug:** `qdrant-payload-shape-is-defined-once`.
  **Rule:** Every Qdrant point payload and collection index set must be built
  from the typed definitions and constants in the single storage-schema module;
  never hand-write an inline payload dict or index list at an `upsert`/`ensure`
  call site, and bump `STORAGE_SCHEMA_VERSION` on any breaking shape change while
  leaving additive fields unversioned.

Per the `vaultspec-codify` discipline, this candidate is NOT yet promoted: a
rule qualifies only after it has held across at least one full execution cycle,
and this is its first. Promote with
`vaultspec-core vault rule promote --from 2026-06-27-storage-schema-contract-audit --as qdrant-payload-shape-is-defined-once` once the contract has survived one
follow-on change (the natural occasion is the dashboard's adoption of the
descriptor, or the first additive payload field).
