# Configuration reference

This page lists every `VAULTSPEC_RAG_*` environment variable vaultspec-rag reads, the matching CLI flag where one exists, and the rules for parsing values.

See also:

- the [installation guide](installation.md) for where to set variables before first run
- the [CLI reference](cli.md) for the full flag context
- the [storage backends guide](backends.md) for the server-first backend model
- the [architecture overview](architecture.md) for the runtime concepts named here
- the [preprocessing hooks guide](preprocessing-hooks.md) for the `.vaultragpreprocess.toml` rule format

## Resolution order

Each setting resolves through a fixed precedence: CLI flag > environment variable > persisted local-only marker > built-in default. A flag on the invoked command wins over an exported environment variable, which wins over the persisted backend marker, which wins over the built-in default.

The persisted local-only marker applies only to backend selection. It lives at `{status_dir}/local-only.json` and is written by `install --local-only`, so a later `server start` with no flag or environment variable still selects the on-disk store.

## Backend selection

These variables choose between the supervised Qdrant server (the default) and the on-disk store, and configure a remote or managed server. The server is the assumed backend; local-only is the opt-out and always wins over the server default.

| Variable                            | Type    | Default                                  | Controls                                                       | CLI flag                   |
| ----------------------------------- | ------- | ---------------------------------------- | -------------------------------------------------------------- | -------------------------- |
| `VAULTSPEC_RAG_QDRANT_SERVER`       | boolean | `1` (true)                               | Server-first default backend                                   | `--qdrant` / `--no-qdrant` |
| `VAULTSPEC_RAG_LOCAL_ONLY`          | boolean | `0` (false)                              | On-disk store opt-out; overrides the server default            | `--local-only`             |
| `VAULTSPEC_RAG_QDRANT_PORT`         | integer | `8765`                                   | Managed server HTTP port (gRPC binds one below)                | -                          |
| `VAULTSPEC_RAG_QDRANT_URL`          | string  | none                                     | Remote or managed server URL; selects server mode in the store | -                          |
| `VAULTSPEC_RAG_QDRANT_API_KEY`      | string  | none                                     | Remote server API key                                          | -                          |
| `VAULTSPEC_RAG_QDRANT_BINARY`       | string  | none                                     | Operator-supplied binary path (air-gapped escape hatch)        | -                          |
| `VAULTSPEC_RAG_QDRANT_STORAGE_DIR`  | string  | `~/.vaultspec-rag/qdrant-server/storage` | Shared multi-root server storage                               | -                          |
| `VAULTSPEC_RAG_QDRANT_QUANTIZATION` | string  | none                                     | Vector quantization (`scalar`, `turbo`, or `product`)          | -                          |

## Core variables

The tables in this section, together with the backend selection table, list every `VAULTSPEC_RAG_*` variable vaultspec-rag reads.

### Project and data locations

| Variable                        | Type | Default                   | Controls                                                  | CLI flag        |
| ------------------------------- | ---- | ------------------------- | --------------------------------------------------------- | --------------- |
| `VAULTSPEC_RAG_ROOT`            | path | current working directory | Project root used to resolve `.vault/` and indexing scope | `--target`      |
| `VAULTSPEC_RAG_DATA_DIR`        | path | `.vault/data/search-data` | Directory holding the on-disk store and index metadata    | `--data-dir`    |
| `VAULTSPEC_RAG_QDRANT_DIR`      | path | `qdrant`                  | On-disk store subdirectory inside the data dir            | `--storage-dir` |
| `VAULTSPEC_RAG_INDEX_META`      | path | `index_meta.json`         | Vault index metadata filename inside the data dir         | -               |
| `VAULTSPEC_RAG_CODE_INDEX_META` | path | `code_index_meta.json`    | Codebase index metadata filename inside the data dir      | -               |

### Service runtime and logging

| Variable                                 | Type    | Default            | Controls                                                    | CLI flag                              |
| ---------------------------------------- | ------- | ------------------ | ----------------------------------------------------------- | ------------------------------------- |
| `VAULTSPEC_RAG_STATUS_DIR`               | path    | `~/.vaultspec-rag` | Directory for service status, marker, binary, and log files | `--status-dir`                        |
| `VAULTSPEC_RAG_LOG_FILE`                 | path    | `service.log`      | Log filename inside the status dir                          | `--log-file`                          |
| `VAULTSPEC_RAG_PORT`                     | integer | `8766`             | HTTP service port and MCP fast path                         | `--port`                              |
| `VAULTSPEC_RAG_LOG_LEVEL`                | string  | `WARNING`          | Root logger level                                           | `--verbose` (INFO), `--debug` (DEBUG) |
| `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS` | integer | `1800`             | Seconds an idle project slot stays resident before eviction | -                                     |
| `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS`     | integer | `16`               | Maximum simultaneously cached project slots                 | -                                     |
| `VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES`    | integer | `10485760`         | Rotating log file size cap in bytes (10 MiB)                | -                                     |
| `VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT` | integer | `5`                | Number of rotated log backups retained                      | -                                     |

### Embedding and reranking

| Variable                                         | Type    | Default | Controls                                            | CLI flag |
| ------------------------------------------------ | ------- | ------- | --------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE`             | integer | `64`    | Outer batch size fed to the embedding pipeline      | -        |
| `VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE`      | integer | `32`    | Vault inner encode sub-batch size                   | -        |
| `VAULTSPEC_RAG_EMBEDDING_CODE_ENCODE_BATCH_SIZE` | integer | `32`    | Code inner encode sub-batch size                    | -        |
| `VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH`         | integer | `2048`  | Hard cap on sequence length advertised to the model | -        |
| `VAULTSPEC_RAG_MAX_EMBED_CHARS`                  | integer | `8000`  | Character cap applied to each text before encoding  | -        |
| `VAULTSPEC_RAG_RERANKER_MAX_LENGTH`              | integer | `1024`  | Reranker token bound                                | -        |
| `VAULTSPEC_RAG_VAULT_CHUNK_CHARS`                | integer | `3000`  | Vault chunk character budget                        | -        |

### Indexing

| Variable                                 | Type    | Default              | Controls                                          | CLI flag |
| ---------------------------------------- | ------- | -------------------- | ------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_INDEX_CHUNK_WORKERS`      | integer | `0` (auto)           | Code-chunk process-pool size                      | -        |
| `VAULTSPEC_RAG_INDEX_PARALLEL_MIN_BYTES` | integer | `8388608`            | Auto-parallel chunking threshold in bytes (8 MiB) | -        |
| `VAULTSPEC_RAG_INDEX_CACHE_FLUSH_SLICES` | integer | `8`                  | CUDA allocator flush cadence in slices            | -        |
| `VAULTSPEC_RAG_DENSE_BACKEND`            | string  | `torch`              | Dense encoder backend (`onnx` experimental)       | -        |
| `VAULTSPEC_RAG_DENSE_ONNX_FILE`          | string  | `onnx/model_O4.onnx` | ONNX model file relative path                     | -        |

### Concurrency limits

| Variable                              | Type    | Default | Controls              | CLI flag |
| ------------------------------------- | ------- | ------- | --------------------- | -------- |
| `VAULTSPEC_RAG_SEARCH_CONCURRENCY`    | integer | `16`    | Search worker limiter | -        |
| `VAULTSPEC_RAG_INDEX_JOB_CONCURRENCY` | integer | `4`     | Index job limiter     | -        |

### Search and model toggles

| Variable                       | Type    | Default    | Controls                                                          | CLI flag    |
| ------------------------------ | ------- | ---------- | ----------------------------------------------------------------- | ----------- |
| `VAULTSPEC_RAG_SPARSE_ENABLED` | boolean | `1` (true) | SPLADE sparse vectors on/off                                      | -           |
| `VAULTSPEC_RAG_SEARCH_TIMEOUT` | integer | `300`      | Connection and read budget for service-handled searches (seconds) | `--timeout` |

### Automatic updates

| Variable                          | Type    | Default    | Controls                                                     | CLI flag                     |
| --------------------------------- | ------- | ---------- | ------------------------------------------------------------ | ---------------------------- |
| `VAULTSPEC_RAG_WATCH_ENABLED`     | boolean | `1` (true) | Filesystem auto-reindex on/off (`0` = pull-only)             | `--updates` / `--no-updates` |
| `VAULTSPEC_RAG_WATCH_DEBOUNCE_MS` | integer | `2000`     | Debounce window coalescing change events before reindex (ms) | `--update-delay-ms`          |
| `VAULTSPEC_RAG_WATCH_COOLDOWN_S`  | float   | `30`       | Per-source re-index cooldown after a completed run (s)       | `--repeat-update-delay-s`    |

### Preprocessing

| Variable                                     | Type    | Default    | Controls                                                          | CLI flag |
| -------------------------------------------- | ------- | ---------- | ----------------------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES` | integer | `10485760` | Cap on text a preprocess hook may emit per file in bytes (10 MiB) | -        |
| `VAULTSPEC_RAG_HTML_STRIP`                   | boolean | `1` (true) | Strip tags from `.html` to plain text before chunking             | -        |

## Config-only keys

These keys exist in the configuration loader but read no environment variable. Set them through a config source, not the environment.

| Config key            | Type    | Default                     | Controls                       |
| --------------------- | ------- | --------------------------- | ------------------------------ |
| `graph_ttl_seconds`   | float   | `300.0`                     | Vault graph cache time to live |
| `embedding_model`     | string  | `Qwen/Qwen3-Embedding-0.6B` | Dense model                    |
| `embedding_dimension` | integer | `1024`                      | Dense vector dimension         |
| `sparse_model`        | string  | `naver/splade-v3`           | Sparse model                   |
| `reranker_enabled`    | boolean | `True`                      | CrossEncoder rerank on/off     |
| `reranker_model`      | string  | `BAAI/bge-reranker-v2-m3`   | Reranker model                 |
| `reranker_batch_size` | integer | `32`                        | Reranker batch size            |

## Type coercion

The loader parses each value on first access. An invalid integer or float raises at that point, not at startup.

- Booleans: the strings `1`, `true`, and `yes` (case-insensitive) parse as true; anything else parses as false.
- Integers and floats: parsed with `int()` and `float()`; non-numeric strings raise on first read.
- Paths: relative paths resolve against the project root; absolute paths are used as given. Use forward slashes on Windows.

An unset variable falls back to the built-in default.

## Hugging Face cache

vaultspec-rag downloads its dense, sparse, and reranker model files through the Hugging Face Hub. The Hub client honours its own environment variables, which vaultspec-rag does not wrap: `HF_HOME`, `HF_HUB_DOWNLOAD_TIMEOUT`, and `DISABLE_SAFETENSORS_CONVERSION`. See the [Hugging Face environment variable reference](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables).

## Examples

Pin the project root for a single search invocation:

```bash
VAULTSPEC_RAG_ROOT=/srv/projects/acme vaultspec-rag search "billing flow"
```

Bind the HTTP service to a non-default port:

```bash
VAULTSPEC_RAG_PORT=9100 vaultspec-rag server start
```

Run the on-disk store instead of the supervised server:

```bash
VAULTSPEC_RAG_LOCAL_ONLY=1 vaultspec-rag server start
```

Raise the log level to DEBUG for one command:

```bash
vaultspec-rag --debug search "billing flow"
```

## Need help?

See the [Support](../README.md#support-and-help) section of the repo README.
