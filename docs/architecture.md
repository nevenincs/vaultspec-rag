# Architecture and concepts

## What vaultspec-rag does

vaultspec-rag is the retrieval layer of a vaultspec-core project. It indexes the `.vault/` directory and your project's source code, then answers a query with a ranked list of file locations and snippets. A query like `"file lock reentrant collection ordering during indexing"` returns the chunks that match it most closely.

This is the retrieval that the R in RAG refers to. vaultspec-rag finds and ranks the grounding, and a separate client reads it. That client is an AI assistant or another tool, and it reaches vaultspec-rag through the command-line tool or over the Model Context Protocol (MCP). The [MCP integration guide](mcp.md) covers that connection.

## How indexing and search work

Indexing splits every document and source file into self-contained chunks. Each chunk is encoded as two vectors. A dense vector captures meaning, and a sparse vector captures exact terms. Both vectors are stored in a local vector database. At search time, vaultspec-rag encodes the query the same two ways. It fuses the two signals into one ranking by how closely each chunk matches, and a reranking model reorders the top results.

Results are ranked rather than exhaustive. A query always returns its closest matches, so an exact string can rank below a looser conceptual hit. Encoding and reranking both run on the GPU, and loading those models is slow, so a [background service](service-mode.md) keeps them resident between searches. The [indexing internals](indexing.md) page names the specific models and explains how the pipeline fits together.

## Why a GPU is required

Encoding and reranking run on the GPU, and on a CPU they are too slow to be usable. vaultspec-rag has no CPU fallback. When no GPU is present it refuses to start and reports why. The hardware floor is an NVIDIA card with CUDA support and roughly 3 GB of free GPU memory. The [installation guide](installation.md) and [configuration reference](configuration.md) carry the exact specifics.

## Server mode versus local-only mode

Server mode is the default. vaultspec-rag runs the database as a standalone supervised server, so concurrent reads and writes go straight to it instead of serializing through the tool's own process. vaultspec-rag downloads a verified pinned binary and supervises it, so you install no separate service. The server still runs as a process and holds a port. Its storage is shared across projects and lives in your home directory at `~/.vaultspec-rag/qdrant-server/storage`.

Local-only mode runs the database in-process behind a single flag. No server is provisioned or supervised, and the storage stays inside the project under `.vault/data/`. Without a separate process, concurrent operations contend for the single one, so this mode trades throughput under load for a self-contained setup. Use it where a running service is impractical, such as continuous integration runs or air-gapped machines. The [storage backends](backends.md) page explains how to switch between the two modes and operate each.

## Where to go next

- [Getting started](getting-started.md) is a hands-on tutorial that takes you from install to first search.
- [Installation guide](installation.md) covers prerequisites, the hardware floor, and setup.
- [Storage backends](backends.md) covers choosing and operating the server or local-only mode.
- [Indexing internals](indexing.md) covers the models and data structures behind the concepts on this page.
- For help, file an issue on the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues).
