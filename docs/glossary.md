# Glossary

Plain-English definitions for terms used across the vaultspec-rag docs. Consult this page when you hit an unfamiliar word. Entries are alphabetical. Each one gives a short explanation and a pointer to the guide that documents the term in full, and may refer to other entries here.

If you arrived without context, the [project overview](../README.md) says what vaultspec-rag is and the [architecture overview](architecture.md) explains how the pieces fit together.

## Accelerator

A supported compute device used for every dense, sparse, and reranker forward pass. vaultspec-rag resolves CUDA first, then Apple silicon MPS, and never selects CPU. See [the architecture overview](architecture.md).

## Ad-hoc mode

A single CLI command that starts its own short-lived process, loads the accelerator models, does the work, and exits. Each invocation pays the model-loading cost again. Ad-hoc mode suits a one-off search or index and is slow for repeated calls. See [the service-mode guide](service-mode.md).

## Backend

One selected implementation behind a stable interface. The compute backend is CUDA or MPS; the storage backend is the managed Qdrant server or the local-only store. `server doctor` reports both independently. See [the architecture overview](architecture.md) and [backends guide](backends.md).

## Chunk

A small slice of a vault document or source file, a few hundred tokens long, that the indexer stores as one searchable unit. Search results point back to specific chunks rather than whole files. See [the architecture overview](architecture.md).

## Codebase index

The on-disk record of chunks cut from your source files, kept alongside the vault index but searched separately through the code search type. See [the indexing guide](indexing.md).

## Content domain

One of the three bodies of content a search can target: `vault`, `code`, or `document`. Select one with `--type`. See [the search guide](search-and-index.md).

## CUDA

NVIDIA's GPU runtime and the supported accelerator on Linux and Windows. CUDA devices use discrete video memory (VRAM). Apple silicon uses MPS instead; CPU-only machines remain unsupported. See [the installation guide](installation.md).

## Dense vector (embedding)

A numeric representation of a piece of text as a list of numbers, arranged so that texts with similar meaning end up with similar numbers. The dense vector captures overall meaning and is what makes semantic search possible. See [the architecture overview](architecture.md).

## Domain

Names two things in these docs. See [Content domain](#content-domain) for what a search targets, and [Noise domain](#noise-domain) for how code search classifies a file's role.

## Env var

An environment variable read at process start to override a config default. vaultspec-rag's variables are prefixed `VAULTSPEC_RAG_`. See [the configuration guide](configuration.md).

## Extracted document

Text produced by a project-defined converter from a format vaultspec-rag cannot read natively, such as a PDF or a spreadsheet. The indexer stores extracted documents in their own domain, separate from the vault and the codebase. See [the preprocessing hooks guide](preprocessing-hooks.md).

## fnmatch glob

A shell-style filename pattern, for example `*.md` or `notes/**/draft-*`, used in include and exclude lists. It follows Python's `fnmatch` rules, not full regex. See [the configuration guide](configuration.md).

## HTTP service daemon

The long-running service that does the compute and serves many projects at once, listening on loopback port 8766. It speaks vaultspec-rag's own REST API - health, jobs, logs, projects, and the search and index endpoints - not MCP; the stdio MCP shim delegates to it over that REST API. See [the service-mode guide](service-mode.md).

## Hybrid search

Search that combines two signals for each query: the dense vector for overall meaning and the sparse vector for exact terms. The two result lists are merged by [reciprocal rank fusion](#reciprocal-rank-fusion-rrf) into one ranking. See [the search guide](search-and-index.md).

## Index support profile

The named set of host requirements indexing checks before it starts. The default `managed-service` profile requires 16 GiB of system memory and 8 GiB of free disk on the index volume; `embedded-local` requires 8 GiB and 5 GiB. Below those minimums, indexing refuses rather than running slowly. See [the installation guide](installation.md).

## Indexing

Reading your documents and source, cutting them into chunks, embedding each chunk, and storing the vectors. The index is the stored result that search reads from. See [the indexing guide](indexing.md).

## JSON envelope

The structured JSON object every CLI command returns when you pass `--json`, with a fixed shape (`ok`, `command`, `data` or `error`) suitable for scripting. See [the automation guide](automation.md).

## Locale deduplication

A code-search flag, `--dedup-locales`, that collapses near-duplicate translated files into a single result so one source surfaces once instead of once per locale. It acts only on search results, never on the index. See [the search guide](search-and-index.md).

## Local-only mode

A local-only store that needs no separate server process. It runs Qdrant inside the process against files under `.vault/data/search-data/qdrant/`. Select it with `--local-only`. See [the backends guide](backends.md).

## Managed Qdrant server

The supervised local Qdrant database server that the service runs by default. The service spawns it on loopback (default `127.0.0.1:8765`) before loading models, supervises its lifetime, and shuts it down last. See [the backends guide](backends.md).

## MCP (Model Context Protocol)

An open protocol that lets AI clients, such as Claude Code, call tools running in a separate server process. vaultspec-rag exposes search and indexing as MCP tools. See [the MCP guide](mcp.md).

## MPS (Metal Performance Shaders)

PyTorch's accelerator backend for Apple silicon. vaultspec-rag uses it only with CPU fallback disabled and reports its memory as unified rather than as VRAM. See [the installation guide](installation.md).

## Namespace

The per-root prefix that keeps one project's collections separate from another's inside the shared server storage - a short hash derived from the project's resolved path (see [Project root](#project-root)). It applies in server mode only; the local-only store separates projects by location instead. See [the backends guide](backends.md).

## Noise domain

How code search classifies a source file's role: `prod`, `tests`, `docs`, `locale`, `generated`, `vendored`, or `worktree`. The default profile treats the other six in two ways rather than one: `worktree` and `generated` are hidden, and `tests`, `docs`, `locale` and `vendored` are kept but score-penalised so production ranks above them. A demoted result still comes back. Filter on it with the inline `exclude:`, `only:`, and `include:` tokens. See [writing a query](query-craft.md).

## Preprocessing hook

A rule in a project's `.vaultragpreprocess.toml` naming a command or entry point that converts a file into indexable text. A hook runs with your own privileges and is not sandboxed, so indexing a repository means trusting the commands its hooks run. See [the preprocessing hooks guide](preprocessing-hooks.md).

## Project root

The directory vaultspec-rag treats as the project boundary, the folder holding `.vault`. It is resolved from `--target`, then `VAULTSPEC_RAG_ROOT`, then the current working directory. See [the configuration guide](configuration.md).

## Provisioning

The one-time setup, run during `install`, that obtains the external dependencies vaultspec-rag needs: platform-appropriate PyTorch, search models cached from Hugging Face, and the managed Qdrant server binary. CUDA uses the configured cu130 source; macOS uses the standard MPS-capable wheel. See [the installation guide](installation.md).

## Readiness

Whether the service can serve requests: torch sees a supported accelerator, the models are cached, and the active storage backend is present and usable. The `server doctor` command reports it. See [the service-mode guide](service-mode.md).

## Reciprocal rank fusion (RRF)

The method that merges the dense and sparse result lists into one ranking. It scores each result by its rank position in each list rather than by raw scores, so the two signals combine fairly. See [the search guide](search-and-index.md).

## Reranker (cross-encoder)

A second-stage model that rescores the top results from hybrid search. It reads the query and each result's full content together to improve the final order. See [the search guide](search-and-index.md).

## Score

The numeric relevance value attached to each search result. Higher is better, but absolute values are not comparable across queries. Scores show only when you pass `--scores`. See [the search guide](search-and-index.md).

## Semantic search

Search that ranks results by meaning rather than exact word matches, using vectors to compare the query against indexed chunks. See [the search guide](search-and-index.md).

## Server mode

The storage arrangement in which the index lives in the managed Qdrant server rather than inside the project, which is the default. Its opposite is [local-only mode](#local-only-mode), and the choice is about where the index lives rather than whether the background service runs. Commands that require it report `server_mode_required` and exit `2` when it is off. See [the backends guide](backends.md).

## Service

The long-running background process that keeps the accelerator models loaded, so requests skip the per-call model-loading cost. It also supervises the managed Qdrant server. Running as a service is the default. See [the service-mode guide](service-mode.md).

## Slot

A reserved seat for one project in the running service. The service keeps a fixed number of slots warm; opening a new project may evict the least recently used one. See [the service-mode guide](service-mode.md).

## Sparse vector (SPLADE)

A numeric representation that records which specific terms a piece of text emphasizes, produced by a model called SPLADE. The sparse vector captures exact wording and pairs with the dense vector in hybrid search. See [the architecture overview](architecture.md).

## stdio transport

The MCP transport where the client launches the server as a subprocess and exchanges messages over standard input and output. It is the default for local AI clients. See [the MCP guide](mcp.md).

## Unified memory

Memory shared by the CPU, GPU, and system on Apple silicon. MPS allocator and recommended-working-set readings describe this shared pool rather than discrete video memory (VRAM). See [the architecture overview](architecture.md).

## Vault

The `.vault/` directory in a project containing structured Markdown documents (ADRs, research, plans, audits, and exec records) that vaultspec-rag indexes for semantic search. See [the architecture overview](architecture.md).

## Watcher (automatic updates)

The background facility that watches your files and re-indexes changed content automatically while the service runs. A debounce window and a per-project cooldown keep bursts of edits from triggering constant re-indexing. See [the service-mode guide](service-mode.md).

## Need help?

If a term is missing or unclear, the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues) takes questions as well as bug reports.
