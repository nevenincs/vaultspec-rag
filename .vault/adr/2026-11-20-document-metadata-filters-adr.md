---
tags:
  - '#adr'
  - '#document-metadata-filters'
date: '2026-11-20'
modified: '2026-11-20'
body_schema: 'body-v2'
body_hash: 'sha256:d10e9722c08f3c75cef0106dcac0aa12247a1fdbbdbb55bb72b4af55c3df29d8'
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
- An index-set change that alters query semantics bumps `STORAGE_SCHEMA_VERSION`, and a breaking bump is recovered by clean rebuild (`2026-06-26-storage-schema-contract-adr` D1 and D6; `src/vaultspec_rag/store_schema.py:70`).
- Detected incompatibility never starts a full rebuild automatically. It surfaces `rebuild_required` with an executable command (`2026-09-07-explicit-reindex-authority-adr`). An explicit rebuild resets the source and serves the growing index (`2026-10-12-destructive-rebuild-lifecycle-adr`).
- Filters thread as scalar strings through `src/vaultspec_rag/search/_validation.py:26`, `src/vaultspec_rag/search/_searcher.py:1103`, `src/vaultspec_rag/server/_routes_search.py:484`, `src/vaultspec_rag/serviceclient/_search_transport.py:49`, `src/vaultspec_rag/cli/_search.py:1245`, and `src/vaultspec_rag/mcp/_tools.py:551`.
- A filter combined with a search type it does not apply to is already an explicit error, not a silent drop (`2026-05-28-cli-search-filters-adr`).

## Considered options

- **Index every metadata key automatically.** Rejected: extractor-controlled keys grow the index set without bound, and `2026-06-10-preprocess-hooks-adr` D12 forbids indexing arbitrary keys.
- **Promote declared keys to new top-level payload fields.** Rejected: duplicates stored data and adds payload fields for values the payload already holds at a stable nested path.
- **Declare keys and index the existing nested fields.** Chosen.
- **Prefix match by query-time scan or a full-text index on `extractor_id`.** Rejected: a scan defeats pushdown, and a text index changes exact-match semantics on the existing key.
- **Store the dotted prefixes of `extractor_id` as an indexed keyword array.** Chosen: a prefix query becomes an exact match.
- **Coerce non-string metadata values to strings.** Rejected; see Implementation D6 and Rationale.

## Constraints

- Only keys the project declares are filterable. Nothing indexes an undeclared key.
- Validation, key resolution, and value splitting live in the service search domain. The HTTP route, CLI, MCP tool, and service client pass parameters through and render the domain's typed error. No adapter validates or drops keys itself.
- Every filter applies to each `Prefetch` branch of a hybrid query, as `2026-03-07-qdrant-filter-on-prefetch-adr` requires.
- Index declarations stay in `store_schema`. A root's declared metadata keys extend the document index set for that root; they do not create a second index registry.
- The schema version bump does not authorize automatic rebuild. Explicit reindex authority stays binding.
- This record amends `2026-06-10-preprocess-hooks-adr` D12. D12's per-rule allowlist that promotes metadata keys to top-level keyword fields is replaced by a project-level declaration that indexes the existing nested fields. D12's rule that arbitrary keys are never indexed stays binding. The D12 amendment text is presented separately and is not applied by this record.
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

**D5 - Extractor-family prefix.** At ingest, each document chunk stores `extractor_id_prefixes`: the dotted prefixes of its `extractor_id`, so `a.b.c` stores `a`, `a.b`, and `a.b.c`. The field joins `DOCUMENT_KEYWORD_INDEXES`. `--extractor-prefix a.b` is an exact match on that field and also accepts a comma list. Prefixes align to segments: `a.b` matches `a.b.c` and not `a.bc`. A prefix argument with an empty segment is refused. The field name is an implementation choice.

**D6 - Non-string values for declared keys are refused at ingest.** When a declared key holds a value that is not a string or a list of strings, including `null`, numbers, booleans, and objects, the source file fails validation. It takes the existing per-file failure path: it is not stored, it is counted and surfaced, and other files continue. Undeclared keys keep the free-form `JsonValue` contract.

**D7 - Unknown keys are refused.** A filter key that is not a filterable key for its collection, or a `meta.<key>` that the root does not declare, raises a typed `unknown_filter_key` error naming the key and the accepted keys. HTTP returns 400. The CLI exits non-zero and emits one JSON envelope in JSON mode. MCP returns a tool error. This applies to the code, vault, and document filter builders, and replaces the log-and-drop branches at `src/vaultspec_rag/_store_search.py:515`, `src/vaultspec_rag/_store_search.py:552`, and `src/vaultspec_rag/_store_search.py:598`.

**D8 - Existing collections.** `STORAGE_SCHEMA_VERSION` bumps from 2 to 3, because the document index set gains `extractor_id_prefixes` and stored points lack it. Per `2026-06-26-storage-schema-contract-adr` D6, recovery is a clean rebuild, not a migration engine. Per `2026-09-07-explicit-reindex-authority-adr`, the service does not rebuild by itself. Each source whose publication carries the old payload schema reports `rebuild_required` with its rebuild command through HTTP, CLI, and MCP. The operator runs that explicit rebuild for each affected root and source. The rebuild follows `2026-10-12-destructive-rebuild-lifecycle-adr`: it resets the source and searches the growing index until completion. The extraction cache survives the rebuild, so extractors do not re-run.

Declared metadata indexes need no schema bump. The ensure pass creates indexes for newly declared keys on the existing collection (`src/vaultspec_rag/store_collections.py:374`) and removes indexes for keys no longer declared, so the live index set matches the declaration. A change to the declared key set enters the document content fingerprint. Incremental document indexing then returns the typed `full_reindex_required`, and the operator rebuilds the document source. That rebuild re-validates every stored unit against D6, so no stored non-string value hides from a filter.

## Rationale

Indexing the nested fields the payload already holds is the smallest change that makes metadata filterable. It adds no storage and keeps one home for each value. Project-level declaration bounds the index count, which preserves the preprocess-hooks rule against arbitrary indexing. Stored prefixes turn a query Qdrant cannot run into an exact match it runs as pushdown.

Refusing unknown keys follows `2026-05-28-cli-search-filters-adr`. A wider answer than the caller asked for, with no signal, is worse than an error. The comment at `src/vaultspec_rag/store_schema.py:293` already records one defect of that kind.

Refusal at ingest is the conservative choice for non-string values. Coercion makes match spelling depend on serialization: `1`, `1.0`, and `true` need exact string forms the caller cannot know. Without coercion, a keyword index skips values of other types, so a stored number is invisible to the filter. Both outcomes are silent misses. Refusal surfaces the defect at the extractor that produced it.

The rebuild path reuses the existing schema-version, `rebuild_required`, and reset-first rebuild mechanisms. It adds no migration code and grants no automatic full-rebuild authority.

## Consequences

- Callers can narrow document search by declared metadata, by several values per key, and by extractor family, on every surface with one contract.
- Calls that relied on an unknown key being ignored now fail. That is the intended behaviour change. Callers must remove or correct the key.
- After upgrade, sources report `rebuild_required` until the operator rebuilds them. `STORAGE_SCHEMA_VERSION` is global (`2026-06-26-storage-schema-contract-adr` D1), so this includes code and vault sources whose shape did not change. Each rebuild re-embeds its source and needs GPU time.
- Changing the declared key set requires a document-source rebuild.
- An extractor that emits a non-string value for a declared key loses those files from the index until it is fixed. The failure count makes this visible.
- In local mode the new indexes are no-ops and filters run as scans. Results are the same; only latency differs.
- Reconsider D8 if per-collection schema versions are adopted, or if declared-key rebuilds become too costly for large document collections. A validate-in-place pass could then replace the rebuild.

## Authorization

The user authorized this decision on 2026-11-20 by replying "go ahead, no need to ask" to the concrete proposal covering declared filterable metadata, the `meta.<key>` syntax on every surface, value lists on `extractor_id` and `locator_kind`, the extractor-prefix field, refusal of unknown keys, and the schema version bump. D6's refusal of non-string values and D8's operator rebuild path are the author's choices within that authorization. The D12 amendment to `2026-06-10-preprocess-hooks-adr` is pending separate application.
