---
title: RAG Architecture Migration Research
source: Qdrant, LlamaIndex, FastEmbed, HuggingFace TEI documentation, web search, codebase analysis
relevance: 10
---

# RAG Architecture Migration Research

## 0. Current State Analysis

**Current Implementation:**
The `vaultspec_rag` module is tightly coupled to `sentence-transformers>=5.0.0` and `torch` (CUDA 13.0 strict requirement via `pyproject.toml`). It uses `nomic-embed-text-v1.5` (768 dim). The vector backend is embedded `lancedb` utilizing Tantivy for FTS and `RRFReranker` for hybrid search. Orchestration is custom-built (e.g., `VaultSearcher`, `VaultStore`, `mcp_server.py`).

**Identified Limitations:**

- **Hardware Lock-in:** The strict PyTorch/CUDA requirement prevents running the tool on Mac (Apple Silicon) or CPU-only environments.
- **Monolithic Architecture:** Embedding generation runs in the same process as the CLI/MCP server, consuming massive VRAM locally.
- **Maintenance:** Custom orchestration (`search.py`) requires manual maintenance of hybrid search, filtering, and graph-aware re-ranking logic.

---

## 1. Embedding Model: Qwen3-Embedding vs Alternatives

**Subject:** Migrating from `nomic-embed-text-v1.5` to `Qwen3-Embedding` (0.6B or 4B variants) or other frontier models like BGE-M3, OpenAI `text-embedding-3-small`.
**Research Findings:**

- **Qwen3-Embedding:** Released June 2025, supports up to 32,768 tokens, inherently multilingual. It features Matryoshka Representation Learning (MRL), allowing truncation of dimensions (e.g., from 4096 to 512) to save space with minimal accuracy loss.
- **Performance:** The 0.6B variant is highly performant and designed to run efficiently on CPUs, directly addressing the CUDA-only lock-in issue of the current implementation.

## 2. Inference Engine: FastEmbed vs Sentence-Transformers

**Subject:** Utilizing `fastembed` (Python wrapper over ONNX Runtime) to replace `sentence-transformers`.
**Research Findings:**

- **Dependency Overhead:** `sentence-transformers` requires downloading large PyTorch binaries and heavily utilizes GPUs.
- **FastEmbed:** Operates via ONNX Runtime. It has zero GPU requirements and performs extremely fast on CPU architectures.
- **Model Support:** While Qwen3-Embedding is relatively new, FastEmbed provides a built-in `TextEmbedding.add_custom_model` method to load custom ONNX files directly from HuggingFace, allowing for immediate integration even before official default registry support.

## 3. Vector Database: Qdrant vs LanceDB

**Subject:** Comparing LanceDB's embedded database against Qdrant's Local Mode.
**Research Findings:**

- **Current Setup (LanceDB):** Operates as an embedded DB relying heavily on Tantivy FTS integration and a Python-level `RRFReranker`, which can introduce initialization latency and fragility.
- **Qdrant Local Mode:** The `qdrant-client` provides a lightweight, Rust-backed `:memory:` or `path="path/to/db"` mode. The Python API in Local Mode is 100% identical to the server mode, operating with zero container overhead.
- **Sparse Vectors (BM42):** Traditional BM25 relies on exact term frequency, which can fail on short RAG chunks. FastEmbed can generate **BM42 sparse vectors** (transformer-based attention matrices) locally. Qdrant natively stores these alongside dense vectors, negating the need for an external text indexing engine like Tantivy.
- **Universal Query API & Fusion:** Qdrant's Universal Query API utilizes a `prefetch` parameter to execute Dense and Sparse searches in parallel. Results are fused natively at the Rust engine level using `models.FusionQuery(fusion=models.Fusion.RRF)`, offloading hybrid search and reranking logic from the Python layer.

## 4. Orchestration: LlamaIndex Server vs Custom Pipeline

**Subject:** Comparing the current custom pipeline with LlamaIndex Workflows & LlamaDeploy.
**Research Findings:**

- **Custom Pipeline (Current):** `VaultSearcher` processes queries and scores results synchronously in-process.
  - *Characteristics:* Near-zero "framework tax" latency (< 5ms orchestration overhead) and complete control over custom graph-aware scoring (`rerank_with_graph`). It is, however, tightly coupled and requires manual maintenance for query routing and asynchronous retrieval.
- **LlamaIndex Workflows & Microservices:** As of late 2024/2025, LlamaIndex uses event-driven `Workflows` and `LlamaDeploy` to wrap RAG pipelines into independent, decoupled microservices.
  - *Capabilities:* Utilizing `llamactl serve`, a workflow deploys as a standalone, scalable HTTP API. This decouples the embedding/retrieval server from the local CLI entirely.
  - *Performance overhead:* Introduces a "framework tax" (~20-50ms per request) due to event loop routing, but offsets this by providing built-in asynchronous retrieval, query decomposition, and advanced context compression to reduce LLM tokens.
  - *Integration Considerations:* Adopting LlamaIndex would require rewriting the current `search.py` and `indexer.py` into `Workflow` steps, and porting the custom `rerank_with_graph` logic into a `NodePostprocessor` or a discrete Workflow step.

## 5. Reference Implementations & Community Examples

**Subject:** Analyzing how the community orchestrates Qdrant, FastEmbed, and BM42/Qwen in practice.
**Research Findings:**

- **Official Qdrant Examples (`qdrant/workshop-ultimate-hybrid-search`):** Qdrant's official repositories heavily utilize FastEmbed for generating both Dense embeddings and BM42 sparse embeddings. They demonstrate how to use `qdrant-client`'s Universal Query API to prefetch both vectors and apply Reciprocal Rank Fusion (RRF) natively.
- **Docker Orchestration (`Lokesh-Chimakurthi/Reliable_RAG` & community patterns):** A common Docker Compose pattern has emerged for this stack:
  - *Qdrant Container:* `qdrant/qdrant:latest` exposing ports 6333/6334 for storage and search.
  - *LLM Container:* `ollama/ollama:latest` for serving local language models (like Qwen2.5) via an OpenAI-compatible API.
  - *App Container:* The main Python application utilizing `qdrant-client[fastembed]` to handle the orchestration (embedding generation via CPU) and retrieval logic.
- **LlamaIndex Integration (`pavannagula/Hybrid-RAG-Using-Qdrant-BM42-Llamaindex`):** Community examples validate that LlamaIndex fully supports the FastEmbed+BM42+Qdrant stack out-of-the-box, bridging the gap between exact keyword matching and semantic relationships using LlamaIndex's built-in `VectorStoreIndex` and `StorageContext` abstractions.

## 6. LlamaIndex Deep-Dive: Usage, Containerization, and Stack Integration

**Subject:** Detailed analysis of deploying LlamaIndex in a production Docker environment and integrating it with the proposed stack (Qdrant, FastEmbed, Qwen/Ollama).
**Research Findings:**

- **Stack Integration API:** In a modern (2025/2026) LlamaIndex setup, the components integrate seamlessly using specialized extensions:
  - `llama-index-vector-stores-qdrant` connects directly to the Qdrant instance.
  - `llama-index-embeddings-fastembed` offloads embedding generation locally.
  - `llama-index-llms-ollama` interfaces with local LLMs like Qwen.
  - *Data Flow:* `Settings.embed_model = FastEmbedEmbedding(...)` configures the global embedding process, while `QdrantVectorStore(client=client)` provides the storage context. This is highly standard and avoids custom boilerplate.
- **Docker Containerization (LlamaDeploy):** In late 2024/2025, LlamaIndex transitioned from simple FastAPI scripts to a robust microservices architecture called **LlamaDeploy** (formerly LlamaAgents).
  - *Architecture:* A production LlamaDeploy Docker architecture splits the pipeline into three distinct container types:
    1. **Message Queue:** A lightweight broker (like Redis or Kafka) handling asynchronous events between workflows.
    2. **Control Plane:** The central gateway/hub managing service registration and state tracking.
    3. **Workflow Services:** Independent containers running the actual RAG pipelines (e.g., executing the Qdrant retrieval and Qwen generation steps).
  - *Best Practices:* Use multi-stage Docker builds (`python:3.11-slim`) to minimize image sizes. Connect these containers via `docker-compose.yaml`. The vector store (Qdrant) and LLM server (Ollama) should be deployed as separate, stateful containers, ensuring the Workflow logic remains entirely stateless.
- **The `llamactl` CLI:** LlamaIndex provides `llamactl` to abstract the orchestration. Instead of writing custom API routers, developers configure a `pyproject.toml` or `deployment.yml` mapping Python workflows to endpoint names. Running `llamactl serve` inside the Docker container automatically exposes these workflows as robust HTTP APIs.
