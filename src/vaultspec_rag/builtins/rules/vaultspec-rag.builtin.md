---
name: vaultspec-rag
---

# vaultspec-rag — semantic search

Use semantic search for codebase discovery and implementation discovery. When you need
to find where or how something is done and don't know the exact name, search by meaning
instead of grepping keywords or guessing identifiers.

## Write good queries

The index is hybrid: dense embeddings match meaning, sparse vectors match exact terms,
and a cross-encoder reranks the top hits. A good query feeds both halves. So:

- Describe the concept or behavior in a short phrase - this drives the dense, semantic
  half.
- In that same phrase, name the concrete domain nouns the target code or docs would use
  - these drive the sparse, exact-match half. A query of pure natural language leaves
    the sparse half nothing to match.
- One concept per query. Narrow with filters; don't paste bare keywords or a guessed
  function name.

```
vaultspec-rag search "file lock acquired around incremental index write" --type code
vaultspec-rag search "retry policy backoff for failed webhook delivery" --type code --language python
vaultspec-rag search "decision on gpu_lock scope around forward pass" --type vault --doc-type adr
```

Code filters: `--language --path --function-name --class-name --include-path GLOB`.
Vault filters: `--doc-type --feature --date --tag`. Filters also work inline in the
query: `type:adr lang:python func:main`.

## Run the server

If the server is not running, start it:

```
vaultspec-rag server start
```

Server mode is the default backend: `server start` supervises the managed Qdrant
server and loads the GPU models. The server is the only workable backend at codebase
scale - local mode is orders of magnitude slower - so it is the assumed default, not an
opt-in. Provision the binary and models once with `vaultspec-rag install` (it fetches
torch, the models, and the Qdrant binary by default).

Local mode is a first-class explicit opt-out for small projects, CI, or air-gapped
hosts: `vaultspec-rag server start --local-only` (or `VAULTSPEC_RAG_LOCAL_ONLY=1`, or
`vaultspec-rag install --local-only` which persists the choice). It uses the on-disk
store and needs no server binary.

Check dependency readiness any time with `vaultspec-rag server doctor` (`--json` for the
machine-readable snapshot): it reports torch CUDA, model presence, and the Qdrant binary
and supervised-server state.

The running service auto-reindexes on file changes - DO NOT manually reindex during
normal work.

The same search is available through MCP as the `search_vault` and `search_codebase`
tools.
