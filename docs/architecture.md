# Architecture and concepts

This page explains what vaultspec-rag is and how it works, so you can decide whether it fits your project before you install it. It answers a handful of questions. Jump to the heading that matches yours:

- What does retrieval-augmented generation mean, and what does this tool actually do?
- How do indexing and searching work at a high level?
- Why does semantic search beat keyword search for some queries?
- Why is a GPU required?
- Why does a database server run by default?

For real depth on the models and data structures, the [indexing internals](indexing.md) page goes deeper. This page stays conceptual.

## What RAG means and what this tool is

Retrieval-augmented generation (RAG) is a two-part pattern. The retrieval half finds the most relevant material for a question. The generation half - an AI assistant, usually a large language model - reads that material and writes an answer grounded in it.

vaultspec-rag is only the retrieval half. It's the semantic-search companion to vaultspec-core, which manages a `.vault/` directory of markdown documents. vaultspec-rag indexes that vault and your project's source code, so you can search both by meaning.

A search returns a ranked list of file locations with snippets, not prose. Think of it as a good librarian, not a chatbot: it points you to the right shelf, it doesn't read the book to you. The generation half is a separate AI assistant that reads those locations, typically through a client that speaks the Model Context Protocol (MCP). For how that connection works, see the [MCP integration guide](mcp.md).

## How indexing and searching work

The mental model is a card catalogue. Before you can look anything up, the tool reads through your vault and source code and writes a card for each piece.

Indexing splits every document and source file into **chunks** - small, self-contained passages. For each chunk, the tool computes a meaning-capturing numeric form and stores it in a local search database. Searching computes the same numeric form for your query, then asks the database for the chunks that sit closest to it. That closeness becomes the relevance score.

Three models run on the GPU to make this work. Two capture meaning from different angles; combining them improves precision. The third re-orders the top candidates so the best matches rise to the top. The [indexing internals](indexing.md) page names the specific models and explains the data flow. Because loading these models takes time, a [background service](service-mode.md) keeps them warm between searches.

## Why semantic search instead of keyword search

Keyword search matches the exact string you type. That fails on the **vocabulary-mismatch** problem: a question about "rate limiting" won't find a file titled "request throttling," even though they're the same idea. Semantic search closes that gap by matching meaning rather than letters.

The trade-offs are honest ones. Indexing has an upfront cost. Results are ranked rather than exhaustive, so a match always comes back even when nothing is relevant. And an exact string you know is present can be ranked below a fuzzier conceptual hit.

So this isn't an argument against grep. Use both: keyword search such as grep or ripgrep when you know the exact string, and vaultspec-rag when you know the concept but not the words.

## Why a GPU is required

Turning text into its numeric form and re-ordering results are matrix-heavy workloads. GPUs are built for that kind of math; general-purpose CPUs are not, and they run it slowly enough to be impractical.

By design, the tool has no CPU fallback. Rather than start and crawl, it refuses to run when no GPU is present and tells you why. You're never left wondering whether it's broken or slow. The hardware floor is modest: an NVIDIA card with CUDA support and roughly 3 GB of free GPU memory. For specifics, see the [installation guide](installation.md) and the [configuration reference](configuration.md).

## Why a database server runs by default

The local search database can run two ways. The default is server-first: vaultspec-rag runs a managed, supervised local search-database server.

The older mode embedded the database as files inside the tool's own process, which serialized work through a single process and became a bottleneck under concurrent load. The supervised server removes that limit and is measurably faster under load. "Managed and supervised" means the tool downloads a verified, pinned binary, then runs and monitors it for you - you don't install or maintain a separate service.

A single-flag **local-only** mode stays available as the minimal alternative, suited to constrained environments such as CI runs or air-gapped machines, where you don't want to run a server. For how to choose between the two and operate each, see the [storage backends](backends.md) page.

## Where to go next

- [Getting started](getting-started.md) - a hands-on tutorial that takes you from install to first search.
- [Installation guide](installation.md) - prerequisites, the hardware floor, and setup.
- [Storage backends](backends.md) - choosing and operating the server or local-only mode.
- [Indexing internals](indexing.md) - the models and data structures behind the concepts on this page.
- Need help? See the [Support section of the README](../README.md#support-and-help) for the issue tracker.
