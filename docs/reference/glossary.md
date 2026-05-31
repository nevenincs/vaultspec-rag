# Glossary

Definitions for terms used throughout the vaultspec-rag docs. Consult this page when a term elsewhere in the documentation is unfamiliar.

**Ad-hoc mode**. How the CLI runs by default. The process loads the models, runs the command, and exits. Each invocation pays the model-load cost. See [Ad-hoc vs service](../explanation/ad-hoc-vs-service.md).

**Chunk**. A piece of a larger file. The indexer splits long documents and source files into chunks so each piece is small enough to search independently. See [How it works](../explanation/how-it-works.md).

**Codebase index**. The search index built from your source code files. It is separate from the vault index. See [How it works](../explanation/how-it-works.md).

**CUDA**. NVIDIA's parallel-computing platform. vaultspec-rag uses the CUDA build of PyTorch to run the models on the GPU. See [Why GPU](../explanation/why-gpu.md).

**Embedding model**. The program that turns text into a list of numbers so two pieces of text can be compared mathematically. See [How it works](../explanation/how-it-works.md).

**Env var**. Short for environment variable. A configuration value the tool reads from the shell environment. The full list lives in [Configuration](../reference/configuration.md).

**fnmatch glob**. A pattern-matching syntax used in shells. `**` matches any directory depth, `*` matches any string, and `?` matches any single character. `--include-path` and `--exclude-path` use this syntax. See [Narrow results](../how-to/narrow-results.md).

**HTTP mode**. One of two ways the MCP server talks to clients. A single daemon listens on an HTTP port and serves any project. See [Use with MCP clients](../how-to/use-with-mcp-clients.md).

**JSON envelope**. The single JSON document every `--json` invocation emits. See [JSON envelope](../reference/json-envelope.md).

**Locale variant**. A near-duplicate file that differs only in language. `locales/en.yml` and `locales/es.yml` are locale variants. `--dedup-locales` collapses them. See [Narrow results](../how-to/narrow-results.md).

**MCP**. Short for Model Context Protocol. The JSON-RPC interface that AI assistants use to call external tools. vaultspec-rag ships an MCP server. See [Use with MCP clients](../how-to/use-with-mcp-clients.md).

**Project root**. The directory the tool treats as your project. Defaults to the current directory; override it with `--target` or `VAULTSPEC_RAG_ROOT`. See [Configuration](../reference/configuration.md).

**Reranker**. A third model that re-scores the top results to improve their ordering. It is part of the GPU stack. See [How it works](../explanation/how-it-works.md).

**Score**. A number between roughly 0 and 1 that ranks how relevant a result is to the query. Higher is more relevant. See [How it works](../explanation/how-it-works.md).

**Semantic search**. Search by meaning rather than exact-keyword match. It returns files that talk about the same concept even when no shared keyword exists. See [Why semantic search](../explanation/why-semantic-search.md).

**Service mode**. How the CLI runs when the background service is started. Commands route through `--port` and reuse the warm models. See [Ad-hoc vs service](../explanation/ad-hoc-vs-service.md).

**Slot**. An in-memory workspace the service holds open for one project. The service can hold several slots at once. See [Ad-hoc vs service](../explanation/ad-hoc-vs-service.md).

**stdio mode**. One of two ways the MCP server talks to clients. The client launches one process per project and communicates over standard input and output. See [Use with MCP clients](../how-to/use-with-mcp-clients.md).

**Vault**. The directory tree of documentation files (the `.md` files under your project root). The vault index covers these. See [How it works](../explanation/how-it-works.md).
