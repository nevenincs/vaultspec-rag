# Configuration reference

This page lists every `VAULTSPEC_RAG_*` environment variable vaultspec-rag reads. It gives the matching CLI flag where one exists and the rules for parsing values.

See also:

- the [installation guide](installation.md) for where to set variables before first run
- the [CLI reference](cli.md) for the full flag context
- the [storage backends guide](backends.md) for the server-first backend model
- the [architecture overview](architecture.md) for the runtime concepts named here
- the [preprocessing hooks guide](preprocessing-hooks.md) for the `.vaultragpreprocess.toml` rule format

## Resolution order

Each setting resolves through a fixed precedence: CLI flag > environment variable > persisted local-only marker > built-in default.

The persisted local-only marker applies only to backend selection. It lives at `{status_dir}/local-only.json` and is written by `install --local-only`. A later `server start` with no flag or environment variable then still selects the on-disk store.

## Backend selection

These variables choose between the supervised Qdrant server (the default) and the on-disk store. They also configure a remote or managed server.

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

| Variable                                 | Type    | Default            | Controls                                                       | CLI flag                              |
| ---------------------------------------- | ------- | ------------------ | -------------------------------------------------------------- | ------------------------------------- |
| `VAULTSPEC_RAG_STATUS_DIR`               | path    | `~/.vaultspec-rag` | Directory for service status, marker, binary, and log files    | `--status-dir`                        |
| `VAULTSPEC_RAG_LOG_FILE`                 | path    | `service.log`      | Resident service log filename inside the status dir            | `--log-file`                          |
| `VAULTSPEC_RAG_PORT`                     | integer | `8766`             | HTTP service port and MCP fast path                            | `--port`                              |
| `VAULTSPEC_RAG_LOG_LEVEL`                | string  | `WARNING`          | Root logger level                                              | `--verbose` (INFO), `--debug` (DEBUG) |
| `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS` | integer | `1800`             | Seconds an idle project slot stays resident before eviction    | -                                     |
| `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS`     | integer | `16`               | Maximum simultaneously cached project slots                    | -                                     |
| `VAULTSPEC_RAG_MANAGED_LOG_MAX_BYTES`    | integer | `10485760`         | Active-file size threshold for each managed log source (10 MiB) | -                                     |
| `VAULTSPEC_RAG_MANAGED_LOG_BACKUP_COUNT` | integer | `5`                | Rotated backups retained for each managed log source           | -                                     |

The policy applies independently to `service.log` and `qdrant.log`. With the defaults, each source keeps one active file and five backups. The aggregate budget is approximately 120 MiB.

### Job lifecycle

| Variable                                  | Type    | Default | Controls                                                       | CLI flag |
| ----------------------------------------- | ------- | ------- | -------------------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_JOB_MAX_NONTERMINAL`       | integer | `64`    | Maximum simultaneously tracked non-terminal (queued/running) jobs | -    |
| `VAULTSPEC_RAG_JOB_SHUTDOWN_TIMEOUT_SECONDS` | float | `300`   | Seconds to drain running jobs during a graceful daemon stop    | -        |

### Store write resilience

A transient store-write failure (disk pressure, a write-ahead-log stall) is retried with bounded exponential backoff before the operation is abandoned.

| Variable                                       | Type    | Default | Controls                                                    | CLI flag |
| ---------------------------------------------- | ------- | ------- | ----------------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_STORE_OPERATION_TIMEOUT_SECONDS` | float  | `120`   | Per-operation deadline before a store write is abandoned    | -        |
| `VAULTSPEC_RAG_STORE_WRITE_RETRY_ATTEMPTS`     | integer | `5`     | Retry attempts for a transient store-write failure          | -        |
| `VAULTSPEC_RAG_STORE_WRITE_RETRY_BASE_SECONDS` | float   | `0.5`   | Initial backoff before the first store-write retry          | -        |
| `VAULTSPEC_RAG_STORE_WRITE_RETRY_MAX_SECONDS`  | float   | `8`     | Maximum backoff between store-write retries                 | -        |

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

### Index resource bounds and memory ceilings

These bound one index run's segment/queue geometry, its memory use, and its liveness. The defaults suit a managed multi-root service; lower them on a smaller host.

| Variable                                        | Type    | Default     | Controls                                                              | CLI flag |
| ----------------------------------------------- | ------- | ----------- | -------------------------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_INDEX_SEGMENT_MAX_CHUNKS`        | integer | `64`        | Chunks per index upsert segment                                      | -        |
| `VAULTSPEC_RAG_INDEX_SEGMENT_MAX_BYTES`         | integer | `8388608`   | Byte cap per index upsert segment (8 MiB)                            | -        |
| `VAULTSPEC_RAG_INDEX_QUEUE_MAX_CHUNKS`          | integer | `512`       | Chunks buffered in the producer-to-consumer index queue             | -        |
| `VAULTSPEC_RAG_INDEX_QUEUE_MAX_BYTES`           | integer | `134217728` | Byte cap on the buffered index queue, applying backpressure (128 MiB) | -        |
| `VAULTSPEC_RAG_INDEX_NO_PROGRESS_TIMEOUT_SECONDS` | float | `900`       | Seconds without index progress before the run is failed             | -        |
| `VAULTSPEC_RAG_INDEX_RSS_CEILING_MB`            | float   | `16384`     | Resident-memory ceiling enforced at index checkpoints (MiB)         | -        |
| `VAULTSPEC_RAG_INDEX_CUDA_CEILING_MB`           | float   | `12288`     | CUDA-memory ceiling enforced at index checkpoints (MiB)             | -        |
| `VAULTSPEC_RAG_INDEX_CUDA_ALLOCATOR_FRACTION`   | float   | `0.8`       | Fraction of CUDA memory the index allocator may reserve             | -        |
| `VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE`           | string  | `managed-service` | Index resource profile advertised to the service              | -        |

### Concurrency limits

| Variable                              | Type    | Default | Controls              | CLI flag |
| ------------------------------------- | ------- | ------- | --------------------- | -------- |
| `VAULTSPEC_RAG_SEARCH_CONCURRENCY`    | integer | `16`    | Search worker limiter | -        |
| `VAULTSPEC_RAG_INDEX_JOB_CONCURRENCY` | integer | `4`     | Index job limiter     | -        |

### Search and model toggles

| Variable                                     | Type    | Default                      | Controls                                                                                                                                                    | CLI flag                                 |
| -------------------------------------------- | ------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| `VAULTSPEC_RAG_SPARSE_ENABLED`               | boolean | `1` (true)                   | SPLADE sparse vectors on/off                                                                                                                                | -                                        |
| `VAULTSPEC_RAG_VAULT_INTENT_DEFAULT`         | string  | `orientation`                | Default vault ranking intent when a search names none (`orientation` surfaces active ADRs and grounding; `debugging` surfaces execution records and audits) | -                                        |
| `VAULTSPEC_RAG_VAULT_INTENT_RANKING_ENABLED` | boolean | `1` (true)                   | Intent-aware vault re-ranking on/off (`0` restores the bare-reranker ordering)                                                                              | -                                        |
| `VAULTSPEC_RAG_VAULT_INTENT_TYPE_CAP`        | integer | `4`                          | Maximum results of one doc type on a vault page (`0` disables the cap)                                                                                      | -                                        |
| `VAULTSPEC_RAG_RERANKER_ENABLED`             | boolean | `1` (true)                   | CrossEncoder rerank on/off                                                                                                                                  | -                                        |
| `VAULTSPEC_RAG_SEARCH_TIMEOUT`               | float   | `300`                        | Connection and read budget for service-handled searches (seconds)                                                                                           | `--timeout`                              |
| `VAULTSPEC_RAG_CODE_NOISE_HIDE_DOMAINS`      | string  | `worktree,generated`         | Code domains hidden from results by default                                                                                                                 | -                                        |
| `VAULTSPEC_RAG_CODE_NOISE_DEMOTE_DOMAINS`    | string  | `tests,docs,locale,vendored` | Code domains demoted (not hidden) by default                                                                                                                | -                                        |
| `VAULTSPEC_RAG_CODE_NOISE_DEMOTE_PENALTY`    | float   | `0.3`                        | Score subtracted from a demoted code result                                                                                                                 | -                                        |
| `VAULTSPEC_RAG_DEDUP_LOCALES_DEFAULT`        | boolean | `1` (true)                   | Collapse locale-variant code results by default                                                                                                             | `--dedup-locales` / `--no-dedup-locales` |

### Automatic updates

| Variable                          | Type    | Default    | Controls                                                     | CLI flag                     |
| --------------------------------- | ------- | ---------- | ------------------------------------------------------------ | ---------------------------- |
| `VAULTSPEC_RAG_WATCH_ENABLED`     | boolean | `1` (true) | Filesystem auto-reindex on/off (`0` = pull-only)             | `--updates` / `--no-updates` |
| `VAULTSPEC_RAG_WATCH_DEBOUNCE_MS` | integer | `2000`     | Debounce window coalescing change events before reindex (ms) | `--update-delay-ms`          |
| `VAULTSPEC_RAG_WATCH_COOLDOWN_S`  | float   | `30`       | Per-source re-index cooldown after a completed run (s)       | `--repeat-update-delay-s`    |

A failed auto-reindex retries with exponential backoff and a circuit breaker that stops retrying a persistently failing source.

| Variable                                    | Type    | Default | Controls                                                     | CLI flag |
| ------------------------------------------- | ------- | ------- | ------------------------------------------------------------ | -------- |
| `VAULTSPEC_RAG_WATCH_RETRY_BASE_SECONDS`    | float   | `30`    | Initial backoff before retrying a failed auto-reindex        | -        |
| `VAULTSPEC_RAG_WATCH_RETRY_MAX_SECONDS`     | float   | `1800`  | Maximum backoff between auto-reindex retries                 | -        |
| `VAULTSPEC_RAG_WATCH_RETRY_JITTER_FRACTION` | float   | `0.1`   | Random jitter fraction added to each retry backoff           | -        |
| `VAULTSPEC_RAG_WATCH_CIRCUIT_FAILURE_THRESHOLD` | integer | `3`  | Consecutive failures before the watch circuit opens          | -        |

### Stdio MCP lifetime

| Variable                       | Type    | Default    | Controls                                                                | CLI flag       |
| ------------------------------ | ------- | ---------- | ----------------------------------------------------------------------- | -------------- |
| `VAULTSPEC_RAG_STDIO_WATCHDOG` | boolean | `1` (true) | Stdio shim self-reap when its spawning process chain breaks (`0` = off) | `--parent-pid` |

### Storage maintenance (auto-prune)

The daemon's scheduled storage-maintenance cycle - see the [storage and maintenance guide](storage-maintenance.md).

| Variable                                                 | Type    | Default    | Controls                                                                           | CLI flag |
| -------------------------------------------------------- | ------- | ---------- | ---------------------------------------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_STORAGE_AUTOPRUNE`                        | boolean | `1` (true) | Scheduled auto-prune on/off (server mode only)                                     | -        |
| `VAULTSPEC_RAG_STORAGE_AUTOPRUNE_INTERVAL_MINUTES`       | float   | `60`       | Minutes between maintenance cycles                                                 | -        |
| `VAULTSPEC_RAG_STORAGE_AUTOPRUNE_GRACE_HOURS`            | float   | `24`       | Continuous-orphan hours before an empty namespace is reclaimed                     | -        |
| `VAULTSPEC_RAG_STORAGE_AUTOPRUNE_GRACE_HOURS_DATA`       | float   | `168`      | Continuous-orphan hours before a point-bearing namespace is archived and reclaimed | -        |
| `VAULTSPEC_RAG_STORAGE_AUTOPRUNE_ARCHIVE_RETENTION_DAYS` | float   | `30`       | Days a snapshot archive is kept before the retention sweep deletes it              | -        |
| `VAULTSPEC_RAG_STORAGE_AUTOPRUNE_ARCHIVE_MAX_GB`         | float   | `20`       | Total-size cap on the archive directory (oldest evicted first)                     | -        |
| `VAULTSPEC_RAG_STORAGE_AUTOPRUNE_MAX_PER_CYCLE`          | integer | `16`       | Maximum namespaces reclaimed per cycle                                             | -        |
| `VAULTSPEC_RAG_STORAGE_AUTOPRUNE_EPHEMERAL_IDLE_HOURS`   | float   | `72`       | Idle hours before a live temp-rooted namespace is reclaimed (`0` disables)         | -        |
| `VAULTSPEC_RAG_STORAGE_RECONCILE`                        | boolean | `1` (true) | Shrink pre-existing collections onto the bounded segment geometry                  | -        |
| `VAULTSPEC_RAG_STORAGE_RECONCILE_MAX_PER_CYCLE`          | integer | `4`        | Maximum collections reconciled per cycle                                           | -        |
| `VAULTSPEC_RAG_STORAGE_RECONCILE_BUDGET_SECONDS`         | float   | `300`      | Per-collection wait for the merge to settle before reporting                       | -        |

### Preprocessing

| Variable                                     | Type    | Default    | Controls                                                          | CLI flag          |
| -------------------------------------------- | ------- | ---------- | ----------------------------------------------------------------- | ----------------- |
| `VAULTSPEC_RAG_PREPROCESS`                   | string  | unset      | `off` disables all preprocessing; wins over everything            | `--no-preprocess` |
| `VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES` | integer | `10485760` | Cap on text a preprocess hook may emit per file in bytes (10 MiB) | -                 |
| `VAULTSPEC_RAG_HTML_STRIP`                   | boolean | `1` (true) | Strip tags from `.html` to plain text before chunking             | -                 |

## Config-only keys

These keys exist in the configuration loader but read no environment variable. Set them through a config source, not the environment.

| Config key            | Type    | Default                     | Controls                       |
| --------------------- | ------- | --------------------------- | ------------------------------ |
| `graph_ttl_seconds`   | float   | `300.0`                     | Vault graph cache time to live |
| `embedding_model`     | string  | `Qwen/Qwen3-Embedding-0.6B` | Dense model                    |
| `embedding_dimension` | integer | `1024`                      | Dense vector dimension         |
| `sparse_model`        | string  | `naver/splade-v3`           | Sparse model                   |
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

## Tuning for memory and speed

On a small GPU, the dense and sparse encoders halve their batch size and retry on a CUDA out-of-memory error, down to a batch of one. Most cards work without tuning. The knobs below reduce memory pressure before that automatic backoff has to engage, or raise throughput.

To fit a smaller GPU:

- Lower `VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE` and `VAULTSPEC_RAG_EMBEDDING_CODE_ENCODE_BATCH_SIZE` (default 32 each).
- Cap `VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH` (default 2048) to shrink padded-attention memory.
- Set `VAULTSPEC_RAG_QDRANT_QUANTIZATION` to `scalar` to compress the stored vectors.
- Turn off a model to free the most memory. Set `VAULTSPEC_RAG_SPARSE_ENABLED=0` to drop the SPLADE encoder, or `VAULTSPEC_RAG_RERANKER_ENABLED=0` to drop the CrossEncoder.

To speed up indexing:

- Raise `VAULTSPEC_RAG_INDEX_CHUNK_WORKERS` (0 auto-sizes to the CPU count, 1 forces serial).
- Lower `VAULTSPEC_RAG_INDEX_PARALLEL_MIN_BYTES` so the process pool engages on smaller trees.
- Raise `VAULTSPEC_RAG_INDEX_JOB_CONCURRENCY` (default 4) if the host has spare cores.

Each variable's default and meaning is listed in the preceding variable tables.

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

## Where to go next

See the [Support](../README.md#support-and-help) section of the repo README.
