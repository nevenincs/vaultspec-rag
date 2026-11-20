---
tags:
  - '#adr'
  - '#document-metadata-filters'
date: '2026-11-20'
modified: '2026-11-20'
body_schema: 'body-v2'
body_hash: 'sha256:354a5e876def7daa6da8408a6027e875ad80d0c89eaccde2960c42fe6dfe13b4'
related:
  - "[[2026-05-28-cli-search-filters-adr]]"
  - "[[2026-06-30-search-noise-filtering-adr]]"
  - "[[2026-03-07-qdrant-payload-indexes-local-adr]]"
  - "[[2026-03-07-qdrant-filter-on-prefetch-adr]]"
  - "[[2026-06-26-storage-schema-contract-adr]]"
  - "[[2026-10-12-destructive-rebuild-lifecycle-adr]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
  - "[[2026-06-10-preprocess-hooks-adr]]"
  - '[[2026-05-30-cli-path-glob-research]]'
  - '[[2026-06-27-storage-schema-contract-reference]]'
  - '[[2026-07-21-code-document-index-boundary-reference]]'
  - '[[2026-09-07-explicit-reindex-authority-research]]'
  - '[[2026-10-12-destructive-rebuild-lifecycle-reference]]'
---

# `document-metadata-filters` adr: `declared metadata filters, any-of matching, and refused unknown filter keys` | (**status:** `accepted`)

## Problem Statement

Document search can narrow only on four fixed payload keys, each by one exact value. Preprocess hooks already emit per-unit and per-document `metadata` (`src/vaultspec_rag/indexer/_preprocess_schema.py:158`, `src/vaultspec_rag/indexer/_preprocess_schema.py:183`). The indexer stores it as `unit_metadata` and `document_metadata` (`src/vaultspec_rag/store_ingest.py:127`) and returns it in results (`src/vaultspec_rag/search/_result_shaping.py:415`). No caller can filter on it. A caller also cannot ask for several values of one key, or for every extractor in a dotted family.

Every filter builder logs and drops an unknown key, then returns unfiltered results (`src/vaultspec_rag/_store_search.py:515`, `src/vaultspec_rag/_store_search.py:552`, `src/vaultspec_rag/_store_search.py:598`). A caller who asked to narrow receives a wider answer and no error.

## Considerations

- The document payload already carries the metadata. Indexing it needs no new payload field (`src/vaultspec_rag/store_schema.py:238`).
- Qdrant keyword indexes support exact and any-of matching on nested keys and on arrays. They have no prefix match (`2026-05-30-cli-path-glob-research`).
- Filter keys are declared beside the index sets so that every filter key has an index behind it (`src/vaultspec_rag/store_schema.py:269`, `src/vaultspec_rag/store_schema.py:305`).
- Payload index creation is idempotent and backfills an index on an existing collection (`src/vaultspec_rag/store_collections.py:374`). In local mode it is a no-op and filters run as scans (`2026-03-07-qdrant-payload-indexes-local-adr`).
- `STORAGE_SCHEMA_VERSION` is one global integer (`2026-06-26-storage-schema-contract-adr` D1; `src/vaultspec_rag/store_schema.py:70`). A bump makes every source on every root incompatible, and recovery is an explicit rebuild of each (`2026-06-26-storage-schema-contract-adr` D6, `2026-09-07-explicit-reindex-authority-adr`, `2026-10-12-destructive-rebuild-lifecycle-adr`). Document rebuilds take hours. One filter does not justify that cost.
- `extractor_id` already has a keyword index (`src/vaultspec_rag/store_schema.py:272`). The pinned managed server is Qdrant 1.20.0 (`src/vaultspec_rag/qdrant_runtime/_constants.py:41`); the facet API exists from Qdrant 1.12. The locked qdrant-client is 1.20.0 (`uv.lock:1791`). It exposes `QdrantClient.facet` (`qdrant_client/qdrant_client.py:819` in the installed package), and local mode implements it by payload scan (`qdrant_client/local/qdrant_local.py:646`, `qdrant_client/local/local_collection.py:1519`). Facet hits carry no truncation flag.
- Filters thread as scalar strings through `src/vaultspec_rag/search/_validation.py:26`, `src/vaultspec_rag/search/_searcher.py:1103`, `src/vaultspec_rag/server/_routes_search.py:484`, `src/vaultspec_rag/serviceclient/_search_transport.py:49`, `src/vaultspec_rag/cli/_search.py:1245`, and `src/vaultspec_rag/mcp/_tools.py:551`.
- A filter combined with a search type it does not apply to is already an explicit error, not a silent drop (`2026-05-28-cli-search-filters-adr`).

## Considered options

- **Index every metadata key automatically.** Rejected: extractor-controlled keys grow the index set without bound, and `2026-06-10-preprocess-hooks-adr` D12 forbids indexing arbitrary keys.
- **Promote declared keys to new top-level payload fields.** Rejected: duplicates stored data and adds payload fields for values the payload already holds at a stable nested path.
- **Declare keys and index the existing nested fields.** Chosen.
- **Prefix match by query-time scan or a full-text index on `extractor_id`.** Rejected: a scan defeats pushdown, and a text index changes exact-match semantics on the existing key.
- **Store the dotted prefixes of `extractor_id` as an indexed keyword array.** Rejected: stored points lack the field, so it needs a global schema bump and a rebuild of every source.
- **Resolve the prefix at query time with a facet over the indexed `extractor_id`.** Chosen: no storage change, and the result is an exact `MatchAny`.
- **Coerce non-string metadata values to strings.** Rejected; see Rationale.
- **Reject files with non-string values for a declared key.** Rejected: declaring a key would fail files that previously indexed fine.

## Constraints

- Only keys the project declares are filterable. Nothing indexes an undeclared key.
- Validation, key resolution, and value splitting live in the service search domain. The HTTP route, CLI, MCP tool, and service client pass parameters through and render the domain's typed error. No adapter validates or drops keys itself.
- Every filter applies to each `Prefetch` branch of a hybrid query, as `2026-03-07-qdrant-filter-on-prefetch-adr` requires.
- Index declarations stay in `store_schema`. A root's declared metadata keys extend the document index set for that root; they do not create a second index registry.
- This decision does not change `STORAGE_SCHEMA_VERSION` and requires no rebuild of any source.
- Declared filterable keys are excluded from the membership, content, and policy fingerprints. Changing them never raises `full_reindex_required`.
- This record amends `2026-06-10-preprocess-hooks-adr` D12. D12's per-rule allowlist that promotes metadata keys to top-level keyword fields is replaced by a project-level declaration that indexes the existing nested fields. D12's rule that arbitrary keys are never indexed stays binding. The amendment is applied in that record.
- Unchanged: the closed `DocumentLocatorKind` literal (`src/vaultspec_rag/_store_models.py:53`), the metadata size bounds (`src/vaultspec_rag/indexer/_preprocess_schema.py:201`), and the existing per-type filter scoping.

## Implementation

We will make declared document metadata filterable with any-of matching, add extractor-family prefix filtering, accept value lists on existing document filters, and refuse every unknown filter key with a typed error.

**D1 - Declared filterable metadata.** The root content-policy file, `.vaultragpreprocess.toml`, declares filterable metadata keys. Each declaration names a key and exactly one scope, `unit` or `document`. A key declared in both scopes is a configuration error. Key names are non-empty, bounded, and contain no `.`, `[`, or `]`, so the nested path is unambiguous. Each declared key gets a keyword payload index on `unit_metadata.<key>` or `document_metadata.<key>` in the document collection. No new payload field is added for metadata. The exact TOML spelling is an implementation choice.

**D2 - Value model.** A declared key's value is a string or a list of strings. A list payload matches when any element matches. An absent key matches no filter on that key. An empty list is valid and matches nothing.

**D3 - Filter syntax and threading.** A metadata filter is `meta.<key>=v1,v2` and resolves to `MatchAny` on the declared nested path. Conditions on different keys combine with AND. The surfaces are:

- service HTTP route: a `metadata_filters` object mapping each key to a list of strings;
- CLI: `--meta key=v1,v2`, repeatable;
- MCP: a `metadata_filters` mapping of key to list of strings;
- service client: the same mapping, sent unchanged;
- inline query tokens: `meta.<key>=v1,v2`.

The CLI and inline forms split values on commas, so a value containing a comma is reachable only through the HTTP, MCP, or client mapping. Metadata filters follow the existing document-filter type scoping.

**D4 - Value lists on existing filters.** `extractor_id` and `locator_kind` accept a comma-separated list and resolve to `MatchAny`. A single value keeps exact-match behaviour. A `locator_kind` value outside the closed literal is refused.

**D5 - Extractor-family prefix.** We will resolve `--extractor-prefix p` at query time. The search domain runs a Qdrant facet over the indexed `extractor_id` key of the root's document collection, with `exact=True` and a limit of 1025. It keeps each value equal to `p` or starting with `p.`, so `a.b` matches `a.b.c` and not `a.bc`. The kept values become a `MatchAny` on `extractor_id`, combined with the other conditions. A comma list of prefixes unions the kept values. The bound is 1024 distinct `extractor_id` values per collection. When the facet returns more than 1024 values, its answer may be truncated, so the search refuses with a typed `extractor_prefix_unbounded` error rather than apply a partial filter. A prefix that matches no value yields an empty result, not an error. A prefix with an empty segment is refused. The facet runs outside the GPU lock. No payload field is added.

**D6 - Non-string values for declared keys are counted, not rejected.** We will store such a value unchanged. A keyword index does not match a value of another type, so the unit does not match filters on that key. Ingest logs a warning and adds the unit to a per-key counter surfaced in the job result. The file still indexes. This covers `null`, numbers, booleans, objects, and lists that hold a non-string element. Undeclared keys keep the free-form `JsonValue` contract.

**D7 - Unknown keys are refused.** A filter key that is not a filterable key for its collection, or a `meta.<key>` that the root does not declare, raises a typed `unknown_filter_key` error naming the key and the accepted keys. HTTP returns 400. The CLI exits non-zero and emits one JSON envelope in JSON mode. MCP returns a tool error. This applies to the code, vault, and document filter builders, and replaces the log-and-drop branches at `src/vaultspec_rag/_store_search.py:515`, `src/vaultspec_rag/_store_search.py:552`, and `src/vaultspec_rag/_store_search.py:598`.

**D8 - Existing collections.** We will add no stored field and keep `STORAGE_SCHEMA_VERSION` at 2. Existing collections need no rebuild. The metadata payload is already stored, so the ensure pass creates the keyword index for each newly declared key on the existing collection (`src/vaultspec_rag/store_collections.py:374`), and the server builds it over the stored points. When a key is no longer declared, the ensure pass drops its index and leaves the payload untouched. This keeps the live index set equal to the declaration, which the schema conformance check compares. Dropping an index deletes no data, and re-declaring the key rebuilds the index. A change to the declared key set never raises `full_reindex_required`.

## Rationale

Indexing the nested fields the payload already holds is the smallest change that makes metadata filterable. It adds no storage and keeps one home for each value. Project-level declaration bounds the index count, which preserves the preprocess-hooks rule against arbitrary indexing. A facet over the existing `extractor_id` index turns a prefix query into an exact `MatchAny` with no storage change. Extractor-id value sets are small, and a hard bound with refusal keeps the filter exact.

Refusing unknown keys follows `2026-05-28-cli-search-filters-adr`. A wider answer than the caller asked for, with no signal, is worse than an error. The comment at `src/vaultspec_rag/store_schema.py:293` already records one defect of that kind.

Counting non-string values, rather than rejecting files, is the conservative choice. Rejection would make declaring a key fail files that indexed fine before, and would remove their content from every search. Coercion would make match spelling depend on serialization: `1`, `1.0`, and `true` need exact string forms the caller cannot know. Storing the value unchanged and counting it loses no content, keeps filters exact, and shows the extractor defect.

Avoiding a schema bump keeps the cost of this feature proportional to its scope. No source on any root needs a rebuild.

## Consequences

- Callers can narrow document search by declared metadata, by several values per key, and by extractor family, on every surface with one contract.
- Calls that relied on an unknown key being ignored now fail. That is the intended behaviour change. Callers must remove or correct the key.
- Upgrading and changing the declared key set need no rebuild. Server-side index creation over existing points takes time proportional to collection size; filters stay correct meanwhile, only slower.
- An extractor that emits a non-string value for a declared key keeps its files indexed. Those units do not match filters on that key, and the job result counts them.
- Each `--extractor-prefix` query adds one facet call. A collection with more than 1024 distinct extractor ids cannot use prefix filtering until the bound is revisited.
- In local mode the new indexes are no-ops, and filters and facets run as payload scans. Results are the same; only latency differs.
- Reconsider D5 if distinct extractor-id counts approach the bound in practice. A stored prefix field would then need its own schema decision.

## Authorization

The user authorized this decision on 2026-11-20 by replying "go ahead, no need to ask" to the concrete proposal covering declared filterable metadata, the `meta.<key>` syntax on every surface, value lists on `extractor_id` and `locator_kind`, extractor-prefix filtering, and refusal of unknown keys. On 2026-11-20, before implementation and on the same authorization, the coordinating session revised it: the prefix is resolved by a bounded facet, the schema version bump and its rebuild are dropped, and a declared-key change needs no rebuild. D6's counted warning and D8's index drop on undeclaration are the author's choices within that authorization. The D12 amendment to `2026-06-10-preprocess-hooks-adr` is applied there.
