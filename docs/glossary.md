# Glossary

Plain-English definitions for terms used across the vaultspec-rag docs. Consult this page when you hit an unfamiliar word. Each entry gives a one-paragraph explanation and a pointer to the doc that defines the term.

**Ad-hoc**. A single CLI command that starts its own short-lived process, loads the GPU models, does the work, and exits. Each invocation pays the model-loading cost again, which is convenient for a one-off search or index but slow for repeated calls. See [the service-mode guide](service-mode.md).

**Backend**. The storage layer that holds the index. vaultspec-rag has two backend implementations: the managed Qdrant server and the local-only on-disk store. The active backend is chosen once and reported by `server doctor`. See [the backends guide](backends.md).

**Chunk**. A small slice of a vault document or source file, a few hundred tokens long, that the indexer stores as one searchable unit. Search results point back to specific chunks rather than whole files. See [the architecture overview](architecture.md).

**Codebase index**. The on-disk record of chunks cut from your source files, kept alongside the vault index but searched separately through the code search type. See [the indexing guide](indexing.md).

**CUDA**. NVIDIA's GPU runtime. vaultspec-rag requires it because all embedding and re-ranking runs on the GPU; CPU-only machines are not supported. See [the installation guide](installation.md).

**Dense vector (embedding)**. A numeric representation of a piece of text as a list of numbers, arranged so that texts with similar meaning end up with similar numbers. The dense vector captures overall meaning and is what makes semantic search possible. See [the architecture overview](architecture.md).

**Env var**. An environment variable read at process start to override a config default. vaultspec-rag's variables are prefixed `VAULTSPEC_RAG_`. See [the configuration guide](configuration.md).

**fnmatch glob**. A shell-style filename pattern, for example `*.md` or `notes/**/draft-*`, used in include and exclude lists. It follows Python's `fnmatch` rules, not full regex. See [the configuration guide](configuration.md).

**HTTP transport**. The MCP transport where the server listens on a TCP port and clients connect over HTTP. The long-running service uses it on loopback port 8766. See [the MCP guide](mcp.md).

**Hybrid search**. Search that combines two signals for each query: the dense vector for overall meaning and the sparse vector for exact terms. The two result lists are merged by reciprocal rank fusion into one ranking. See [the search guide](search-and-index.md).

**Indexing**. Reading your documents and source, cutting them into chunks, embedding each chunk, and storing the vectors. The index is the stored result that search reads from. See [the indexing guide](indexing.md).

**JSON envelope**. The structured JSON object returned by every CLI command when `--json` is passed, with a fixed shape (`ok`, `command`, `data` or `error`) suitable for scripting. See [the automation guide](automation.md).

**Local-only mode**. An embedded on-disk store that needs no separate server process. It runs Qdrant inside the process against files under `.vault/data/search-data/`, and is the single-flag alternative selected by `--local-only`. See [the backends guide](backends.md).

**Locale deduplication**. A code-search flag, `--dedup-locales`, that collapses near-duplicate translated files into a single result so one source surfaces once instead of once per locale. It acts only on search results, at search time. See [the search guide](search-and-index.md).

**Managed Qdrant server**. The supervised local Qdrant database server that the service runs by default. The daemon spawns it on loopback (default `127.0.0.1:8765`) before loading models. It supervises the server's lifetime and shuts it down last. See [the backends guide](backends.md).

**MCP (Model Context Protocol)**. An open protocol that lets AI clients, such as Claude Code, call tools running in a separate server process. vaultspec-rag exposes search and indexing as MCP tools. See [the MCP guide](mcp.md).

**Project root**. The directory vaultspec-rag treats as the project boundary, the folder holding `.vault`. It is resolved from the current working directory or from `VAULTSPEC_RAG_ROOT`. See [the configuration guide](configuration.md).

**Provisioning**. The one-time setup, run during `install`, that obtains the three external dependencies vaultspec-rag needs. These are the CUDA PyTorch build, the search models cached from Hugging Face, and the managed Qdrant server binary. See [the installation guide](installation.md).

**Readiness**. Whether the service can serve requests: torch sees CUDA, the models are cached, and the active backend is present and usable. The `server doctor` command reports it. See [the service-mode guide](service-mode.md).

**Reciprocal rank fusion (RRF)**. The method that merges the dense and sparse result lists into one ranking. It scores each result by its rank position in each list rather than by raw scores, so the two signals combine fairly. See [the search guide](search-and-index.md).

**Reranker (cross-encoder)**. A second-stage model that rescores the top results from hybrid search. It reads the query and each result's full content together to improve the final order. See [the search guide](search-and-index.md).

**Score**. The numeric relevance value attached to each search result. Higher is better, but absolute values are not comparable across different queries. Scores show only when you pass `--scores`. See [the search guide](search-and-index.md).

**Semantic search**. Search that ranks results by meaning rather than exact word matches, using vectors to compare the query against indexed chunks. See [the search guide](search-and-index.md).

**Service**. The long-running background process that keeps the GPU models loaded, so requests skip the per-call model-loading cost. It also supervises the managed Qdrant server. Running as a service is the default. See [the service-mode guide](service-mode.md).

**Slot**. A reserved seat for one project in the running service. The service keeps a fixed number of slots warm; opening a new project may evict the least recently used one. See [the service-mode guide](service-mode.md).

**Sparse vector (SPLADE)**. A numeric representation that records which specific terms a piece of text emphasizes, produced by the SPLADE model. The sparse vector captures exact wording and pairs with the dense vector in hybrid search. See [the architecture overview](architecture.md).

**stdio transport**. The MCP transport where the client launches the server as a subprocess and exchanges messages over standard input and output. It is the default for local AI clients. See [the MCP guide](mcp.md).

**Vault**. The `.vault/` directory in a project containing structured Markdown documents (ADRs, research, plans, audits, and exec records) that vaultspec-rag indexes for semantic search. See [the architecture overview](architecture.md).

**Watcher / automatic updates**. The background facility that watches your files and re-indexes changed content automatically while the service runs. A debounce window and a per-project cooldown keep bursts of edits from triggering constant re-indexing. See [the service-mode guide](service-mode.md).

## Need help?

If a term is missing or unclear, see the [Support](../README.md#support-and-help) section of the repo README.
