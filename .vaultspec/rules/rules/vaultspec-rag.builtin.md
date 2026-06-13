---
name: vaultspec-rag
---

# vaultspec-rag — semantic search

Use semantic search for codebase discovery and implementation discovery. When you need
to find where or how something is done and don't know the exact name, search by meaning
instead of grepping keywords or guessing identifiers.

## Write good queries

The index is hybrid: dense embeddings match meaning, sparse vectors match exact terms,
and a cross-encoder reranks the top hits. So:

- Describe the concept or behavior in a short natural-language phrase.
- Include the concrete domain nouns the target code or docs would use - they drive the
  exact-match half of the search.
- One concept per query. Narrow with filters; don't paste bare keywords or a guessed
  function name.

```
vaultspec-rag search "where file locks are acquired during indexing" --type code
vaultspec-rag search "retry policy for failed webhook delivery" --type code --language python
vaultspec-rag search "decision on gpu lock scope" --type vault --doc-type adr
```

Code filters: `--language --path --function-name --class-name --include-path GLOB`.
Vault filters: `--doc-type --feature --date --tag`. Filters also work inline in the
query: `type:adr lang:python func:main`.

## Run the server

If the server is not running, start it:

```
vaultspec-rag server start --qdrant --qdrant-auto-provision
```

This provisions the managed Qdrant server, loads the GPU models, and serves search.
Always use `--qdrant`: local mode is orders of magnitude slower at codebase scale.

The running service auto-reindexes on file changes - DO NOT manually reindex during
normal work.

The same search is available through MCP as the `search_vault` and `search_codebase`
tools.
