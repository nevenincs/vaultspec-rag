# Why a GPU is required

vaultspec-rag refuses to start without an NVIDIA GPU. That is a real cost, and worth explaining honestly: this page covers what the GPU does, what the floor looks like, and why there is no CPU fallback.

## What the GPU actually does

Two things, both numeric. First, it turns text into vectors - a few hundred numbers per chunk - using a transformer model. Second, it ranks candidate results by scoring query and document pairs through a smaller cross-encoder. Both operations are dense matrix multiplications, which is exactly the workload GPUs were built for.

A CPU can do the same arithmetic. The problem is latency. A single search touches three models and several hundred candidate chunks; on a CPU, the round trip stretches from sub-second into tens of seconds. Nothing about the result is wrong, but the tool stops feeling like search and starts feeling like a batch job. Interactive use collapses.

## The hardware floor

The minimum is an NVIDIA card with CUDA support and roughly 3 GB of free VRAM. The three resident models weigh about 1.9 GB together; the remainder is working memory for batches and the Qdrant vector store sitting in the same process.

There is no AMD or Apple Silicon support. The project ships and tests against the CUDA build of PyTorch and only that build. ROCm and Metal backends exist upstream, but supporting them means a second toolchain, a second test matrix, and a second class of bugs to triage. For a small project, that cost is too high to carry without a maintainer who runs on that hardware daily. Without an NVIDIA card, vaultspec-rag will not run.

## What lives on disk

Three model files download from HuggingFace on first run: a dense embedder, a sparse embedder, and a cross-encoder reranker. Together they occupy roughly 1.9 GB in the HuggingFace cache, which defaults to `~/.cache/huggingface`. The download happens once. Subsequent starts load from disk in a few seconds.

## How memory is managed

One instance of each model lives in GPU memory for the lifetime of the process. A single lock serialises GPU operations so concurrent requests queue rather than collide; this trades a little throughput for predictable VRAM usage and avoids the failure mode where two requests allocate simultaneously and one falls over.

Default batch sizes assume a 16 GB card. Smaller cards work, but you may need to lower batch sizes through environment variables; the [configuration reference](../reference/configuration.md) lists the relevant knobs.

## Why no CPU fallback

A fallback is the obvious feature to ask for, and it is deliberately absent. The reason is that a CPU path would technically run while being unusable in practice: queries taking tens of seconds, indexing taking hours, and a steady stream of bug reports from users who reasonably assumed the documented experience applied to them. Refusing to start, with a clear error and a remediation hint, is more honest than degrading silently. The constraint is visible at install time rather than discovered after a week of frustration.
