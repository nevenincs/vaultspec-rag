# Architecture and concepts

## What vaultspec-rag does

vaultspec-rag is the retrieval layer of a vaultspec-core project. It indexes your content and answers a query with a ranked list of file locations and passages. It doesn't answer the question itself: something else reads what it returns. That client is an AI assistant or another tool, and it reaches vaultspec-rag through the command line or over the Model Context Protocol (MCP). The [MCP integration guide](mcp.md) covers that connection.

This is the retrieval in retrieval-augmented generation (RAG). vaultspec-rag finds and ranks the grounding; the client reads it.

It builds three separate indexes: the `.vault/` decision records a vaultspec-core project keeps, your source code, and extracted documents routed in by [preprocessing hooks](preprocessing-hooks.md). You search one at a time, or all of them together.

Encoding text this way finds things you can't name. Keyword matching needs you to supply a word the target contains. That fails when you've forgotten the wording, or when the author chose different words than you would. Searching by meaning removes that dependency, at the cost of a GPU requirement.

## How indexing and search work

Indexing splits every document and source file into self-contained chunks. Each chunk is encoded as two vectors: a dense vector that captures meaning, and a sparse vector that captures exact terms. Both are stored in a local vector database.

At search time vaultspec-rag encodes your query the same two ways, fuses the two signals into a single ranking, and then a third model, the reranker, reorders the top of that list. The [indexing internals](indexing.md) page names the specific models and how the pipeline fits together.

## Why results are ranked, not exhaustive

A query always returns its closest matches. No relevance threshold filters results out, so a search never reports "no results" the way a keyword search does.

Two consequences follow. An exact string can rank below a looser conceptual hit, because the ranking weighs meaning alongside wording. And a query with nothing genuinely relevant to match still returns its ten closest chunks, which look like poor results rather than an empty answer. [Writing a query](query-craft.md) covers how to tell the two apart.

## Why vaultspec-rag needs a GPU

Every dense, sparse, and reranker pass runs on the GPU, at index time and again at search time. On a central processing unit (CPU) those models are too slow to be useful, so vaultspec-rag ships no CPU fallback at all.

It resolves CUDA first, then Apple silicon Metal Performance Shaders (MPS). When neither is available, startup refuses with an accelerator-required error rather than degrading.

That refusal is deliberate. A search that silently ran a hundred times longer would look as though the tool had stopped responding. A background service that appeared to start and then never returned results would be harder to diagnose than a refusal at launch.

When `PYTORCH_ENABLE_MPS_FALLBACK` is set, vaultspec-rag refuses MPS too: the variable moves unsupported operators to the CPU and reintroduces the behavior the refusal exists to prevent.

### Accelerator and GPU

The code and the [glossary](glossary.md) say *accelerator*, because the resolved device is either CUDA or MPS and the error messages name which. Elsewhere the documentation says *GPU*, which means the same thing everywhere you meet it.

## How the two kinds of GPU memory differ

CUDA has discrete video memory. vaultspec-rag checks free memory at load time, and roughly 3 GB free is the practical floor.

Apple silicon has unified memory, shared by the CPU, the GPU, and everything else on the machine. No discrete pool exists to measure, so vaultspec-rag reports allocator and recommended-working-set figures instead of inventing a video-memory number.

The project validates the dense, sparse, and reranker models running concurrently on an 8 GiB Apple silicon machine. That is a statement about function, not about throughput, battery, or thermals. Don't read it as parity with CUDA.

Memory figures use binary units (GiB) and video-memory figures follow the vendor's decimal convention (GB). The [installation guide](installation.md) and [configuration reference](configuration.md) carry the exact numbers.

## Where the models and the index live between searches

Loading three models is slow enough that paying that cost on every query would make the tool unusable. A background service holds them in memory instead, which is why the first start is the slow one and later searches aren't.

One service runs per machine. Each project keeps its own index, namespaced inside the service's storage. Opening a second project means indexing that project, not starting a second service. Returning tomorrow means starting the service again, but not re-indexing. While the service runs it watches your files and folds changes in as they happen.

## Server mode and local-only mode

Server mode and local-only mode are two storage arrangements, not a default and a downgrade.

**Server mode** is the default. vaultspec-rag runs the vector database as a supervised standalone server, so concurrent reads and writes go straight to it instead of queuing through one process. It downloads a checksum-verified pinned binary and supervises it, so you install no separate service yourself. The server holds a port, and its storage is shared across projects in your home directory at `~/.vaultspec-rag/qdrant-server/storage`.

**Local-only mode** runs the database in-process behind a single flag. Nothing is provisioned or supervised, and the storage stays inside the project at `.vault/data/search-data/`. Without a separate process, concurrent operations contend for the one process, so this mode trades throughput under load for a self-contained setup. It suits continuous integration runs, air-gapped machines, and anywhere a resident service is impractical.

Neither mode changes the GPU requirement. The [storage backends](backends.md) page covers switching between them and operating each.

## The words this page uses

Chunk, dense vector, sparse vector, reranker, unified memory, accelerator, and backend are all defined in the [glossary](glossary.md), which is the single place to resolve them.

## Where to go next

- [Getting started](getting-started.md) answers how to go from install to first search.
- [Installation](installation.md) answers what the hardware floor is and how to set it up. If the tool doesn't detect your GPU, start with that guide's recovery section, which covers driver and build faults, rather than the issue tracker.
- [Backends](backends.md) answers how to choose and operate the server or local-only mode.
- [Indexing internals](indexing.md) answers which models run and what the pipeline does with them.
- For anything else, the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues) takes questions as well as bug reports, and is the only support channel.
