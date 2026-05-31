# Glossary

Plain-English definitions for terms used across the vaultspec-rag docs. Consult this page when you hit an unfamiliar word and want a one-paragraph explanation plus a pointer to the doc that uses it most.

**Ad-hoc mode**. A way of running searches and indexing where each CLI command starts its own short-lived process, loads models, does the work, and exits. Convenient for one-off use but slow for repeated calls. See [search-and-index.md](search-and-index.md) and [service-mode.md](service-mode.md).

**Chunk**. A small slice of a vault document or source file (a few hundred tokens) that the indexer stores as one searchable unit. Search results point back to specific chunks rather than whole files. See [architecture.md](architecture.md).

**Codebase index**. The on-disk store of chunks cut from your source files, kept alongside the vault index but searched separately. See [search-and-index.md](search-and-index.md).

**CUDA**. NVIDIA's GPU runtime. vaultspec-rag requires it because all embedding and re-ranking runs on the GPU; CPU-only machines are not supported. See [installation.md](installation.md).

**Embedding**. A numeric representation of a piece of text as a list of numbers, arranged so that texts with similar meaning end up with similar numbers. This is what makes semantic search possible. See [architecture.md](architecture.md).

**Env var**. An environment variable read at process start to override a config default. vaultspec-rag's variables are prefixed `VAULTSPEC_RAG_`. See [configuration.md](configuration.md).

**fnmatch glob**. A shell-style filename pattern (for example `*.md` or `notes/**/draft-*`) used in include and exclude lists. Follows Python's `fnmatch` rules, not full regex. See [configuration.md](configuration.md).

**HTTP mode**. The MCP transport where the server listens on a TCP port and clients connect over HTTP. Used by the long-running service mode. See [service-mode.md](service-mode.md) and [mcp.md](mcp.md).

**JSON envelope**. The structured JSON object returned by every CLI command when `--json` is passed, with a fixed shape (status, data, error) suitable for scripting. See [automation.md](automation.md).

**Locale variant**. A regional or language-specific tag (for example `en-GB`, `fr-FR`) attached to a vault document so search can prefer or filter by locale. See [configuration.md](configuration.md).

**MCP**. Model Context Protocol. An open protocol that lets AI clients (such as Claude Code) call tools running in a separate server process. vaultspec-rag exposes search and indexing as MCP tools. See [mcp.md](mcp.md).

**Project root**. The directory vaultspec-rag treats as the project boundary: usually the folder containing `.vault/` and `pyproject.toml`. Resolved from the current working directory or `VAULTSPEC_RAG_ROOT`. See [configuration.md](configuration.md).

**RAG**. Retrieval-augmented generation. A pattern where a system first retrieves relevant text snippets and then feeds them to a language model as context. vaultspec-rag provides the retrieval half. See [architecture.md](architecture.md).

**Re-ranker**. A second-stage model that takes the top results from the initial embedding search and rescores them by reading the query and each result together, improving the final order. See [search-and-index.md](search-and-index.md).

**Score**. The numeric relevance value attached to each search result. Higher is better, but absolute values are not comparable across different queries. See [search-and-index.md](search-and-index.md).

**Semantic search**. Search that ranks results by meaning rather than exact word matches, using embeddings to compare the query against indexed chunks. See [search-and-index.md](search-and-index.md).

**Service mode**. Running vaultspec-rag as a long-lived background process that keeps GPU models loaded between requests, instead of starting fresh each time. See [service-mode.md](service-mode.md).

**Slot**. A reserved seat for one project in the running service. The service keeps a fixed number of slots warm; opening a new project may evict the least recently used one. See [service-mode.md](service-mode.md).

**stdio mode**. The MCP transport where the client launches the server as a subprocess and exchanges messages over standard input and output. The default for local AI clients. See [mcp.md](mcp.md).

**Vault**. The `.vault/` directory in a project containing structured Markdown documents (ADRs, research, plans, audits, exec records) that vaultspec-rag indexes for semantic search. See [architecture.md](architecture.md).

## Need help?

If a term is missing or unclear, see the [Support](../README.md#support-and-help) section of the repo README.
