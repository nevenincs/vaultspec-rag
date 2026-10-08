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

A query returns its closest matches. Local ranking applies no relevance threshold, so a weak answer arrives as poor results rather than as the empty response a keyword search would give. Two things do still empty a result list: a hard filter such as `--include-path` or `only:` that no indexed file satisfies, and an index with nothing in it yet.

The optional Typesafe stage is the exception. When `VAULTSPEC_RAG_TYPESAFE_API_KEY` is set in the service's environment, a hosted classifier can reweight candidates and drop the ones it judges confidently irrelevant, which can return fewer results or none. See [Typesafe enrollment](configuration.md#typesafe-enrollment). The scores in this documentation's examples come from local ranking.

Two consequences follow. An exact string can rank below a looser conceptual hit, because the ranking weighs meaning alongside wording. And a query with nothing genuinely relevant to match still returns up to ten results, which look like poor results rather than an empty answer. Vault results are grouped per document, so a vault search can return fewer than ten. [Writing a query](query-craft.md) covers how to tell the two apart.

## Why vaultspec-rag needs a GPU

Every dense, sparse, and reranker pass runs on the GPU, at index time and again at search time. On a central processing unit (CPU) those models are too slow to be useful, so vaultspec-rag ships no CPU fallback at all.

It resolves CUDA first, then Apple silicon Metal Performance Shaders (MPS). When neither is available, startup refuses with an accelerator-required error rather than degrading.

That refusal is deliberate. A search that silently ran a hundred times longer would look as though the tool had stopped responding. A background service that appeared to start and then never returned results would be harder to diagnose than a refusal at launch.

When `PYTORCH_ENABLE_MPS_FALLBACK` is exactly `1`, vaultspec-rag refuses MPS too: that setting moves unsupported operators to the CPU and reintroduces the behavior the refusal exists to prevent. PyTorch reads only the value `1`, so other values do not trigger the refusal.

### Accelerator and GPU

The code and the [glossary](glossary.md) say *accelerator*, because the resolved device is either CUDA or MPS and the error messages name which. Elsewhere the documentation says *GPU*, which means the same thing everywhere you meet it.

## How the two kinds of GPU memory differ

CUDA has discrete video memory. Before loading models, vaultspec-rag checks it
against the configured admission limit.

Apple silicon has unified memory shared by the CPU and GPU. vaultspec-rag reports
allocator and recommended-working-set figures; the CUDA admission limit does not
apply to this shared memory.

See the [installation requirements](installation.md#what-you-need-before-you-start)
for profile minimums and [GPU memory settings](configuration.md#index-resource-bounds-and-memory-ceilings)
for admission and runtime limits.

## Where the models and the index live between searches

Loading three models is slow enough that paying that cost on every query would make the tool unusable. A background service holds them in memory instead, which is why the first start is the slow one and later searches aren't.

One service runs per machine. Each project keeps its own index, namespaced inside the service's storage. Opening a second project means indexing that project, not starting a second service. Returning tomorrow means starting the service again, but not re-indexing. While the service runs it watches your files and folds changes in as they happen.

## Server mode and local-only mode

Server mode and local-only mode are two storage arrangements, not a default and a downgrade.

**Server mode** is the default. vaultspec-rag runs the vector database as a supervised standalone server, so concurrent reads and writes go straight to it instead of queuing through one process. The binary is pinned and checksum-verified: the archive before it is unpacked, and the executable before every launch. `install` provisions it, and a host `server start` downloads it when it is missing, unless you pass `--no-qdrant-auto-provision`, in which case it prints the install command. A binary on `PATH` is never used; an operator names their own explicitly. vaultspec-rag then supervises the server, so you run no separate service yourself. The server holds a port, and its storage is shared across projects in your home directory at `~/.vaultspec-rag/qdrant-server/storage`.

**Local-only mode** runs the database in-process when selected with `--local-only` and supported by the `embedded-local` index profile. No separate Qdrant server binary is provisioned or supervised; the model files are still provisioned and loaded as usual. The storage stays inside the project: the data directory is `.vault/data/search-data/`, and the store itself lives in its `qdrant/` subfolder. Without a separate process, concurrent operations contend for the one process, so this mode trades throughput under load for a self-contained setup. It suits continuous integration runs, air-gapped machines, and anywhere a resident service is impractical. See [storage backends](backends.md) for configuration.

Neither mode changes the GPU requirement. The [storage backends](backends.md) page covers switching between them and operating each.

## The words this page uses

Chunk, dense vector, sparse vector, reranker, unified memory, accelerator, and backend are all defined in the [glossary](glossary.md), which is the single place to resolve them.

## Where to go next

- [Getting started](getting-started.md) answers how to go from install to first search.
- [Installation](installation.md) answers what the hardware floor is and how to set it up. If the tool doesn't detect your GPU, start with that guide's recovery section, which covers driver and build faults, rather than the issue tracker.
- [Backends](backends.md) answers how to choose and operate the server or local-only mode.
- [Indexing internals](indexing.md) answers which models run and what the pipeline does with them.
- For anything else, the [issue tracker](https://github.com/nevenincs/vaultspec-rag/issues) takes questions as well as bug reports, and is the only support channel.
