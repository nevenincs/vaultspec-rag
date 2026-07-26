# Configuration reference

This page lists every `VAULTSPEC_RAG_*` environment variable vaultspec-rag declares. It gives the matching CLI flag where one exists and the rules for parsing values.

Every variable name, type, and default below is checked against the shipped settings object by a test in the suite, so a knob cannot be added, renamed, or re-defaulted without this page failing until it is updated.

See also:

- the [installation guide](installation.md) for where to set variables before first run
- the [CLI reference](cli.md) for the full flag context
- the [storage backends guide](backends.md) for the server-first backend model
- the [architecture overview](architecture.md) for the runtime concepts named here
- the [preprocessing hooks guide](preprocessing-hooks.md) for the `.vaultragpreprocess.toml` rule format

## Resolution order

Each setting resolves through a fixed precedence: CLI flag > environment variable > persisted local-only marker > built-in default.

The persisted local-only marker applies only to backend selection. It lives at `{status_dir}/local-only.json` and is written by `install --local-only` - `server start --local-only` applies to that run without persisting. A later `server start` with no flag and no environment variable then still selects the on-disk store.

Four variables sit outside this chain and resolve their values their own way; they have their own section below.

## Backend selection

These variables choose between the supervised Qdrant server (the default) and the on-disk store. They also configure a remote or managed server.

| Variable                             | Type    | Default                                  | Controls                                                               | CLI flag                   |
| ------------------------------------ | ------- | ---------------------------------------- | ---------------------------------------------------------------------- | -------------------------- |
| `VAULTSPEC_RAG_QDRANT_SERVER`        | boolean | `1` (true)                               | Server-first default backend                                           | `--qdrant` / `--no-qdrant` |
| `VAULTSPEC_RAG_LOCAL_ONLY`           | boolean | `0` (false)                              | On-disk store opt-out; overrides the server default                    | `--local-only`             |
| `VAULTSPEC_RAG_QDRANT_PORT`          | integer | `8765`                                   | Managed server HTTP port (gRPC binds one below)                        | -                          |
| `VAULTSPEC_RAG_QDRANT_URL`           | string  | none                                     | Remote or managed server URL; selects server mode in the store         | -                          |
| `VAULTSPEC_RAG_QDRANT_API_KEY`       | string  | none                                     | Remote server API key                                                  | -                          |
| `VAULTSPEC_RAG_QDRANT_BINARY`        | string  | none                                     | Operator-supplied binary path (air-gapped escape hatch)                | -                          |
| `VAULTSPEC_RAG_QDRANT_STORAGE_DIR`   | string  | `~/.vaultspec-rag/qdrant-server/storage` | Shared multi-root server storage                                       | -                          |
| `VAULTSPEC_RAG_QDRANT_QUANTIZATION`  | string  | none                                     | Vector quantization (`scalar`, `turbo`, or `product`)                  | -                          |
| `VAULTSPEC_RAG_QDRANT_READY_TIMEOUT` | float   | `300`                                    | Seconds the supervisor waits for the managed server to accept requests | -                          |

## Core variables

The tables in this section, together with the backend selection table, list every `VAULTSPEC_RAG_*` variable resolved through the standard chain.

### Project and data locations

| Variable                        | Type | Default                   | Controls                                               | CLI flag        |
| ------------------------------- | ---- | ------------------------- | ------------------------------------------------------ | --------------- |
| `VAULTSPEC_RAG_DATA_DIR`        | path | `.vault/data/search-data` | Directory holding the on-disk store and index metadata | `--data-dir`    |
| `VAULTSPEC_RAG_QDRANT_DIR`      | path | `qdrant`                  | On-disk store subdirectory inside the data dir         | `--storage-dir` |
| `VAULTSPEC_RAG_INDEX_META`      | path | `index_meta.json`         | Vault index metadata filename inside the data dir      | -               |
| `VAULTSPEC_RAG_CODE_INDEX_META` | path | `code_index_meta.json`    | Codebase index metadata filename inside the data dir   | -               |

### Service runtime and logging

| Variable                                 | Type    | Default             | Controls                                                                  | CLI flag                              |
| ---------------------------------------- | ------- | ------------------- | ------------------------------------------------------------------------- | ------------------------------------- |
| `VAULTSPEC_RAG_STATUS_DIR`               | path    | `~/.vaultspec-rag`  | Directory for service status, marker, binary, and log files               | `--status-dir`                        |
| `VAULTSPEC_RAG_LOG_FILE`                 | path    | `service.log`       | Resident service log filename inside the status dir                       | `--log-file`                          |
| `VAULTSPEC_RAG_PORT`                     | integer | `8766`              | HTTP service port and MCP fast path                                       | `--port`                              |
| `VAULTSPEC_RAG_LOG_LEVEL`                | string  | `WARNING`           | Root logger level                                                         | `--verbose` (INFO), `--debug` (DEBUG) |
| `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS` | integer | `1800`              | Seconds an idle project slot stays resident before eviction               | -                                     |
| `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS`     | integer | `16`                | Maximum simultaneously cached project slots                               | -                                     |
| `VAULTSPEC_RAG_ADMIN_TIMEOUT`            | float   | `30`                | Client connection and read budget for lifecycle and admin calls (seconds) | -                                     |
| `VAULTSPEC_RAG_MANAGED_LOG_MAX_BYTES`    | integer | `10485760` (10 MiB) | Active-file size threshold for each managed log source                    | -                                     |
| `VAULTSPEC_RAG_MANAGED_LOG_BACKUP_COUNT` | integer | `5`                 | Rotated backups retained for each managed log source                      | -                                     |

The log policy applies independently to `service.log` and `qdrant.log`. With the defaults, each source keeps one active file and five backups. The aggregate budget is approximately 120 MiB.

### Job lifecycle

| Variable                                     | Type    | Default | Controls                                                          | CLI flag |
| -------------------------------------------- | ------- | ------- | ----------------------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_JOB_MAX_NONTERMINAL`          | integer | `64`    | Maximum simultaneously tracked non-terminal (queued/running) jobs | -        |
| `VAULTSPEC_RAG_JOB_SHUTDOWN_TIMEOUT_SECONDS` | float   | `300`   | Seconds to drain running jobs during a graceful daemon stop       | -        |

### Store write resilience

A transient store-write failure (disk pressure, a write-ahead-log stall) is retried with bounded exponential backoff before the operation is abandoned.

| Variable                                        | Type    | Default | Controls                                                 | CLI flag |
| ----------------------------------------------- | ------- | ------- | -------------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_STORE_OPERATION_TIMEOUT_SECONDS` | float   | `120`   | Per-operation deadline before a store write is abandoned | -        |
| `VAULTSPEC_RAG_STORE_WRITE_RETRY_ATTEMPTS`      | integer | `5`     | Retry attempts for a transient store-write failure       | -        |
| `VAULTSPEC_RAG_STORE_WRITE_RETRY_BASE_SECONDS`  | float   | `0.5`   | Initial backoff before the first store-write retry       | -        |
| `VAULTSPEC_RAG_STORE_WRITE_RETRY_MAX_SECONDS`   | float   | `8`     | Maximum backoff between store-write retries              | -        |

### Model selection

Changing a model against an index built with another one is an operator decision with consequences: the stored vectors belong to the previous model's space. Reindex after any change here. A dense width that disagrees with the dense model is rejected by the store on the first upsert rather than silently written.

| Variable                            | Type    | Default                     | Controls                                       | CLI flag |
| ----------------------------------- | ------- | --------------------------- | ---------------------------------------------- | -------- |
| `VAULTSPEC_RAG_EMBEDDING_MODEL`     | string  | `Qwen/Qwen3-Embedding-0.6B` | Dense embedding model id                       | -        |
| `VAULTSPEC_RAG_EMBEDDING_DIMENSION` | integer | `1024`                      | Dense vector width; must match the dense model | -        |
| `VAULTSPEC_RAG_SPARSE_MODEL`        | string  | `naver/splade-v3`           | SPLADE sparse model id                         | -        |
| `VAULTSPEC_RAG_RERANKER_MODEL`      | string  | `BAAI/bge-reranker-v2-m3`   | CrossEncoder reranker model id                 | -        |

### Embedding and reranking

| Variable                                             | Type    | Default | Controls                                            | CLI flag |
| ---------------------------------------------------- | ------- | ------- | --------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE`                 | integer | `64`    | Outer batch size fed to the embedding pipeline      | -        |
| `VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE`          | integer | `32`    | Vault inner encode sub-batch size                   | -        |
| `VAULTSPEC_RAG_EMBEDDING_CODE_ENCODE_BATCH_SIZE`     | integer | `32`    | Code inner encode sub-batch size                    | -        |
| `VAULTSPEC_RAG_EMBEDDING_DOCUMENT_ENCODE_BATCH_SIZE` | integer | `12`    | Document inner encode sub-batch size                | -        |
| `VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH`             | integer | `2048`  | Hard cap on sequence length advertised to the model | -        |
| `VAULTSPEC_RAG_MAX_EMBED_CHARS`                      | integer | `8000`  | Character cap applied to each text before encoding  | -        |
| `VAULTSPEC_RAG_RERANKER_MAX_LENGTH`                  | integer | `1024`  | Reranker token bound                                | -        |
| `VAULTSPEC_RAG_RERANKER_BATCH_SIZE`                  | integer | `32`    | Candidate pairs per reranker forward pass           | -        |
| `VAULTSPEC_RAG_VAULT_CHUNK_CHARS`                    | integer | `3000`  | Vault chunk character budget                        | -        |
| `VAULTSPEC_RAG_DOCUMENT_CHUNK_CHARS_PER_TOKEN`        | integer | `3`     | Chars-per-token ratio turning the model's token window into a document chunk budget | -        |
| `VAULTSPEC_RAG_DOCUMENT_CHUNK_OVERLAP_CHARS`          | integer | `256`   | Overlap carried across a document chunk boundary    | -        |

### Indexing

| Variable                                    | Type    | Default              | Controls                                                            | CLI flag |
| ------------------------------------------- | ------- | -------------------- | ------------------------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_INDEX_CHUNK_WORKERS`         | integer | `0` (auto)           | Code-chunk process-pool size                                        | -        |
| `VAULTSPEC_RAG_INDEX_PARALLEL_MIN_BYTES`    | integer | `8388608` (8 MiB)    | Auto-parallel chunking threshold in bytes                           | -        |
| `VAULTSPEC_RAG_INDEX_REUSE`                 | boolean | `1` (true)           | Reuse sibling-namespace vectors across worktrees                    | -        |
| `VAULTSPEC_RAG_INDEX_CACHE_FLUSH_SLICES`    | integer | `8`                  | CUDA allocator flush cadence on the codebase encode path, in slices | -        |
| `VAULTSPEC_RAG_VAULT_CACHE_FLUSH_SLICES`    | integer | `1`                  | CUDA allocator flush cadence on the vault encode path, in slices    | -        |
| `VAULTSPEC_RAG_DOCUMENT_CACHE_FLUSH_SLICES` | integer | `1`                  | CUDA allocator flush cadence on the document encode path, in slices | -        |
| `VAULTSPEC_RAG_DENSE_BACKEND`               | string  | `torch`              | Dense encoder backend (`onnx` experimental)                         | -        |
| `VAULTSPEC_RAG_DENSE_ONNX_FILE`             | string  | `onnx/model_O4.onnx` | ONNX model file relative path                                       | -        |

### Index resource bounds and memory ceilings

These bound one index run's segment/queue geometry, its memory use, and its liveness. The defaults suit a managed multi-root service; lower them on a smaller host.

The CUDA ceiling is derived from the real device by default rather than fixed: at `0` the ceiling is the device's total memory minus `VAULTSPEC_RAG_INDEX_CUDA_HEADROOM_MB`, so a larger card gets a larger budget without any tuning. Setting a positive value is an authoritative override that raises or lowers the effective ceiling.

| Variable                                          | Type    | Default               | Controls                                                                   | CLI flag |
| ------------------------------------------------- | ------- | --------------------- | -------------------------------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_INDEX_SEGMENT_MAX_CHUNKS`          | integer | `64`                  | Chunks per index upsert segment                                            | -        |
| `VAULTSPEC_RAG_INDEX_SEGMENT_MAX_BYTES`           | integer | `8388608` (8 MiB)     | Byte cap per index upsert segment                                          | -        |
| `VAULTSPEC_RAG_INDEX_QUEUE_MAX_CHUNKS`            | integer | `512`                 | Chunks buffered in the producer-to-consumer index queue                    | -        |
| `VAULTSPEC_RAG_INDEX_QUEUE_MAX_BYTES`             | integer | `134217728` (128 MiB) | Byte cap on the buffered index queue, applying backpressure                | -        |
| `VAULTSPEC_RAG_INDEX_NO_PROGRESS_TIMEOUT_SECONDS` | float   | `900`                 | Seconds without index progress before the run is failed                    | -        |
| `VAULTSPEC_RAG_INDEX_RSS_CEILING_MB`              | float   | `16384`               | Resident-memory ceiling enforced at index checkpoints (MiB)                | -        |
| `VAULTSPEC_RAG_INDEX_CUDA_CEILING_MB`             | float   | `0` (auto-derive)     | CUDA-memory ceiling override in MiB; `0` derives one from the device       | -        |
| `VAULTSPEC_RAG_INDEX_CUDA_HEADROOM_MB`            | float   | `2048`                | Memory reserved below the device total when the ceiling auto-derives (MiB) | -        |
| `VAULTSPEC_RAG_INDEX_CUDA_ALLOCATOR_FRACTION`     | float   | `0.8`                 | Fraction of CUDA memory the index allocator may reserve                    | -        |
| `VAULTSPEC_RAG_INDEX_SUPPORT_PROFILE`             | string  | `managed-service`     | Index resource profile advertised to the service                           | -        |

### Concurrency limits

| Variable                              | Type    | Default | Controls              | CLI flag |
| ------------------------------------- | ------- | ------- | --------------------- | -------- |
| `VAULTSPEC_RAG_SEARCH_CONCURRENCY`    | integer | `16`    | Search worker limiter | -        |
| `VAULTSPEC_RAG_INDEX_JOB_CONCURRENCY` | integer | `4`     | Index job limiter     | -        |

### Search and model toggles

| Variable                                     | Type    | Default                      | Controls                                                                             | CLI flag                                 |
| -------------------------------------------- | ------- | ---------------------------- | ------------------------------------------------------------------------------------ | ---------------------------------------- |
| `VAULTSPEC_RAG_SPARSE_ENABLED`               | boolean | `1` (true)                   | SPLADE sparse vectors on/off                                                         | -                                        |
| `VAULTSPEC_RAG_VAULT_INTENT_DEFAULT`         | string  | `orientation`                | Default vault ranking intent when a search names none (`orientation` or `debugging`) | -                                        |
| `VAULTSPEC_RAG_VAULT_INTENT_RANKING_ENABLED` | boolean | `1` (true)                   | Intent-aware vault re-ranking on/off (`0` restores the bare-reranker ordering)       | -                                        |
| `VAULTSPEC_RAG_VAULT_INTENT_TYPE_CAP`        | integer | `4`                          | Maximum results of one doc type on a vault page (`0` disables the cap)               | -                                        |
| `VAULTSPEC_RAG_RERANKER_ENABLED`             | boolean | `1` (true)                   | CrossEncoder rerank on/off                                                           | -                                        |
| `VAULTSPEC_RAG_SEARCH_TIMEOUT`               | float   | `300`                        | Client connection and read budget for service-handled searches (seconds)             | `--timeout`                              |
| `VAULTSPEC_RAG_CODE_NOISE_HIDE_DOMAINS`      | string  | `worktree,generated`         | Code domains hidden from results by default                                          | -                                        |
| `VAULTSPEC_RAG_CODE_NOISE_DEMOTE_DOMAINS`    | string  | `tests,docs,locale,vendored` | Code domains demoted (not hidden) by default                                         | -                                        |
| `VAULTSPEC_RAG_CODE_NOISE_DEMOTE_PENALTY`    | float   | `0.3`                        | Score subtracted from a demoted code result                                          | -                                        |
| `VAULTSPEC_RAG_DEDUP_LOCALES_DEFAULT`        | boolean | `1` (true)                   | Collapse locale-variant code results by default                                      | `--dedup-locales` / `--no-dedup-locales` |
| `VAULTSPEC_RAG_GRAPH_TTL_SECONDS`            | float   | `300`                        | Vault graph cache lifetime backing link and grounding lookups (seconds)              | -                                        |

### Automatic updates

| Variable                          | Type    | Default    | Controls                                                     | CLI flag                     |
| --------------------------------- | ------- | ---------- | ------------------------------------------------------------ | ---------------------------- |
| `VAULTSPEC_RAG_WATCH_ENABLED`     | boolean | `1` (true) | Filesystem auto-reindex on/off (`0` = pull-only)             | `--updates` / `--no-updates` |
| `VAULTSPEC_RAG_WATCH_DEBOUNCE_MS` | integer | `2000`     | Debounce window coalescing change events before reindex (ms) | `--update-delay-ms`          |
| `VAULTSPEC_RAG_WATCH_COOLDOWN_S`  | float   | `30`       | Per-source re-index cooldown after a completed run (s)       | `--repeat-update-delay-s`    |

A failed auto-reindex retries with exponential backoff and a circuit breaker that stops retrying a persistently failing source.

| Variable                                        | Type    | Default | Controls                                              | CLI flag |
| ----------------------------------------------- | ------- | ------- | ----------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_WATCH_RETRY_BASE_SECONDS`        | float   | `30`    | Initial backoff before retrying a failed auto-reindex | -        |
| `VAULTSPEC_RAG_WATCH_RETRY_MAX_SECONDS`         | float   | `1800`  | Maximum backoff between auto-reindex retries          | -        |
| `VAULTSPEC_RAG_WATCH_RETRY_JITTER_FRACTION`     | float   | `0.1`   | Random jitter fraction added to each retry backoff    | -        |
| `VAULTSPEC_RAG_WATCH_CIRCUIT_FAILURE_THRESHOLD` | integer | `3`     | Consecutive failures before the watch circuit opens   | -        |

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

| Variable                                     | Type    | Default             | Controls                                                  | CLI flag |
| -------------------------------------------- | ------- | ------------------- | --------------------------------------------------------- | -------- |
| `VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES` | integer | `10485760` (10 MiB) | Cap on text a preprocess hook may emit per file, in bytes | -        |
| `VAULTSPEC_RAG_HTML_STRIP`                   | boolean | `1` (true)          | Strip tags from `.html` to plain text before chunking     | -        |

## Variables with their own parsing rules

These four do not resolve through the chain above. Each is read at its own call site with the rule stated here. One of them is not an operator knob at all.

The two booleans among them accept the same spellings as every other boolean - that part does not vary anywhere in vaultspec-rag. What they resolve differently is everything *else*: an empty value, and a word that spells neither state. The Controls column below states each one's rule, and the reason for it.

| Variable                       | Type    | Default           | Controls                                                                                                                                                                                                                                                     | CLI flag          |
| ------------------------------ | ------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| `VAULTSPEC_RAG_PREPROCESS`     | string  | unset             | `off` disables all preprocessing and wins over every other source; any other value, including unset, leaves rules enabled                                                                                                                                    | `--no-preprocess` |
| `VAULTSPEC_RAG_STDIO_WATCHDOG` | boolean | enabled           | Stdio shim self-reap when its spawning process chain breaks. Only an explicit `0`, `false`, `off`, or `no` disables it; unset, empty, and any unrecognised word all leave it **armed**, because disarming it by accident strands orphaned shim processes      | -                 |
| `VAULTSPEC_RAG_MEMORY_PROBE`   | boolean | disabled          | Diagnostic memory sampler. Follows the standard boolean rule in full, rejection included: unset and empty leave it off, and an unrecognised word is rejected rather than guessed at                                                                          | -                 |
| `VAULTSPEC_RAG_ROOT`           | path    | working directory | The project every entry point addresses when nothing else names one. `--target` outranks it on the CLI and a tool call's own `project_root` outranks it over MCP; below it sits the working directory. A value naming a directory that is not an enrolled workspace fails the run naming the variable, rather than being dropped for a directory that happens to resolve. The resident HTTP service is the exception: it serves every root at once, so the variable is stripped from its environment at spawn | `--target`        |

## Config-only keys

These keys exist in the configuration loader and read no environment variable of their own. Set them through a config source, not the environment.

| Config key                       | Type    | Default   | Controls                                                                                                                  |
| -------------------------------- | ------- | --------- | ------------------------------------------------------------------------------------------------------------------------- |
| `preprocess_mode`                | string  | `default` | Two-state preprocessing mode; the environment reaches it through `VAULTSPEC_RAG_PREPROCESS` rather than a direct override |

## Type coercion

The loader parses and validates every value when the settings are built, so a rejected value is reported once at startup rather than when the setting it belongs to happens to be read. One unusable value anywhere makes the whole settings object unbuildable.

- Booleans: `1`, `true`, `yes` and `on` parse as true; `0`, `false`, `no` and `off` parse as false (case-insensitive). These spellings are the same for **every** boolean vaultspec-rag reads, including the ones in [Variables with their own parsing rules](#variables-with-their-own-parsing-rules) - no variable reads `off` as on. Any other value is rejected with a message naming the variable and listing the accepted spellings, so a typo such as `treu` is refused instead of silently reading as false and turning the feature off.
- Integers and floats: parsed with `int()` and `float()`; a non-numeric value is rejected the same way.
- Paths: relative paths resolve against the project root; absolute paths are used as given. Use forward slashes on Windows.
- Empty values: for a setting whose default is a string or a path, an empty or whitespace-only value is treated as unset and falls back to the default. This keeps an unexpanded `VAR="$UNSET"` from repointing a managed directory at the working directory. A boolean does **not** share that protection: an empty value reads as false, so an unexpanded `VAR="$UNSET"` on a boolean turns that setting off rather than leaving its default in place. `VAULTSPEC_RAG_STDIO_WATCHDOG` is the single exception, and says why in its own row.

An unset variable falls back to the built-in default.

The four variables in [Variables with their own parsing rules](#variables-with-their-own-parsing-rules) are resolved at their own call sites. The boolean *spellings* above still apply to the two booleans among them; what those two decide differently is how an empty or unrecognised value resolves, which their section states individually.

## Hugging Face cache

vaultspec-rag downloads its dense, sparse, and reranker model files through the Hugging Face Hub. These are third-party variables (no `VAULTSPEC_RAG_` prefix), so they sit outside the reference tables above. Most are honoured by the Hub client itself; the Controls column notes where vaultspec-rag reads or defaults one itself.

| Variable                         | Type    | Controls                                                                          |
| -------------------------------- | ------- | --------------------------------------------------------------------------------- |
| `HF_HOME`                        | path    | Hub cache root. Read directly when reporting cache location; falls back to `~/.cache/huggingface` |
| `HF_ENDPOINT`                    | string  | Hub mirror base URL                                                               |
| `HF_HUB_DOWNLOAD_TIMEOUT`        | integer | Per-file download timeout. The service defaults it to `300` when unset            |
| `HF_HUB_OFFLINE`                 | boolean | Cache-only mode; no network access to the Hub                                     |
| `TRANSFORMERS_OFFLINE`           | boolean | Cache-only model loading for Transformers                                         |
| `DISABLE_SAFETENSORS_CONVERSION` | boolean | Skip on-the-fly safetensors conversion                                            |

`HF_HUB_OFFLINE` is the authoritative offline switch; vaultspec-rag also honours `TRANSFORMERS_OFFLINE`, and when either is set to `1`, `true`, `yes`, or `on` it loads every model cache-only. See the [Hugging Face environment variable reference](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables).

Searches additionally quiet the Hub and Transformers loggers by defaulting `HF_HUB_DISABLE_PROGRESS_BARS`, `TRANSFORMERS_NO_ADVISORY_WARNINGS`, and `TRANSFORMERS_VERBOSITY` when they are unset. Set them yourself to keep the library output.

## Tuning for memory and speed

On a small GPU, the dense and sparse encoders halve their batch size and retry on a CUDA out-of-memory error, down to a batch of one. Most cards work without tuning. The knobs below reduce memory pressure before that automatic backoff has to engage, or raise throughput.

To fit a smaller GPU:

- Lower the inner encode sub-batches: `VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE` and `VAULTSPEC_RAG_EMBEDDING_CODE_ENCODE_BATCH_SIZE` (32 each), and `VAULTSPEC_RAG_EMBEDDING_DOCUMENT_ENCODE_BATCH_SIZE` (12, smaller because document fragments fill the model's whole window).
- Cap `VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH` (default 2048) to shrink padded-attention memory.
- Raise `VAULTSPEC_RAG_INDEX_CUDA_HEADROOM_MB` to leave more of the device outside the indexing budget, or set `VAULTSPEC_RAG_INDEX_CUDA_CEILING_MB` to pin an explicit ceiling.
- Set `VAULTSPEC_RAG_QDRANT_QUANTIZATION` to `scalar` to compress the stored vectors.
- Turn off a model to free the most memory. Set `VAULTSPEC_RAG_SPARSE_ENABLED=0` to drop the SPLADE encoder, or `VAULTSPEC_RAG_RERANKER_ENABLED=0` to drop the CrossEncoder.

To speed up indexing:

- Raise `VAULTSPEC_RAG_INDEX_CHUNK_WORKERS` (0 auto-sizes to the CPU count, 1 forces serial).
- Lower `VAULTSPEC_RAG_INDEX_PARALLEL_MIN_BYTES` so the process pool engages on smaller trees.
- Raise `VAULTSPEC_RAG_INDEX_JOB_CONCURRENCY` (default 4) if the host has spare cores.

Each variable's default and meaning is listed in the preceding variable tables.

## Examples

Point a single command at another project:

```bash
vaultspec-rag --target /srv/projects/acme search "billing flow"
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
