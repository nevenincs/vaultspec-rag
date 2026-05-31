# Architecture and concepts

This page answers four questions: what RAG means and what this tool does, how indexing and searching actually work, why you would reach for semantic search instead of grep, and why a GPU is required. Read top to bottom for the full picture, or jump to the heading that matches your question.

## What RAG means and what this tool does

RAG stands for retrieval-augmented generation. It is an approach where an AI assistant looks things up in your files before answering, instead of relying only on what it was trained on. The "retrieval" half finds the relevant passages; the "generation" half is the assistant that reads them and writes a reply.

vaultspec-rag is the retrieval half. It indexes your vault and your source code, accepts a query, and returns a ranked list of file locations with snippets. A separate program does the generation half by reading those locations and turning them into prose. That program is typically a large language model running inside a client that speaks the Model Context Protocol, a JSON-RPC interface that AI clients use to call external tools. See [mcp.md](mcp.md) for how to wire vaultspec-rag into Claude Desktop, Claude Code, and similar clients.

This is why the `search` command returns a table of file paths and snippets rather than a written answer. Do not expect a chatbot; expect a very good librarian. For commands and usage, see [search-and-index.md](search-and-index.md).

## How indexing and searching work

The mental model worth holding in your head is a card catalogue. Indexing fills the catalogue once. Searching looks things up in it. Everything else is detail.

Indexing reads each markdown file in your vault and each source file in your project, splits them into chunks (paragraphs for prose, functions and classes for code), and stores a numeric representation of each chunk in a local vector database. The numeric representation captures meaning rather than exact spelling, which is what makes the next step possible.

Searching computes the same kind of numeric representation for your query, then asks the database for the closest stored chunks. Closeness is what produces the score column you see in the results. Closer chunks rank higher; less close chunks rank lower or fall off the list.

Three models run on the GPU to make this work. Two of them compute the numeric representations from different angles, and combining their views improves precision. A third re-ranks the top candidates after the initial lookup, which cleans up the ordering when the first two disagree. The names of those models are an implementation detail and do not affect how you use the tool. For the commands that drive indexing and searching, see [search-and-index.md](search-and-index.md); for the daemon that keeps the models warm between calls, see [service-mode.md](service-mode.md).

## Why semantic search instead of grep

Grep is not going anywhere. Ripgrep and its cousins are excellent at what they do, and if you know the exact string you are looking for, keyword search is faster, more precise, and more exhaustive than anything vaultspec-rag will give you. This page is not an argument against grep.

The problem semantic search solves is the one keyword search cannot. A question about "rate limiting" will never surface a file titled "request throttling". A question about "feature flag" will never reach an ADR that talks about "rollout gates". The vocabulary mismatch between the question and the file is invisible to grep, because grep only sees characters. Semantic search sees meaning, and so it finds the file anyway.

The trade-offs are real. Semantic search has an upfront cost (indexing time, GPU memory, model downloads on first use), it can miss exact-string matches that grep would find without thinking, and its results are ranked rather than exhaustive. The honest recommendation is to use both. Reach for grep when you know the string. Reach for vaultspec-rag when you know the concept but not the words the author used.

## Why a GPU is required

The GPU does two jobs. It turns text into numeric representations during both indexing and searching, and it runs the re-ranker that orders the final results. These are matrix-heavy workloads that GPUs are built for and CPUs are not.

The hardware floor is about 3 GB of GPU memory on an NVIDIA card with CUDA support. No AMD, no Apple Silicon. The project ships and tests against the CUDA build of PyTorch only. Supporting other backends would mean a second toolchain, a second test matrix, and a second class of bugs to triage, and the maintainers have chosen to keep the surface area small rather than spread it thin.

There is no CPU fallback. A CPU path would technically run, but it would be far slower than the GPU path; slow enough that the tool would not feel responsive in interactive use, though the maintainers have not formally benchmarked CPU latency. Rather than ship a fallback that lets users discover its unsuitability for themselves, vaultspec-rag refuses to start with a clear error when no GPU is available. For install and verification steps, see [installation.md](installation.md); for batch-size knobs on smaller cards, see [configuration.md](configuration.md).

## Need help?

If something on this page raises more questions than it answers, the [Support](../README.md#support-and-help) section of the repo README is the right place to start.
