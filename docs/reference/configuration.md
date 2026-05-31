# Configuration reference

This page lists every environment variable that vaultspec-rag reads, the matching CLI flag where one exists, and the rules for parsing values.

## Resolution order

vaultspec-rag resolves each setting from the first source that provides a value:

1. CLI flag on the invoked command
1. Environment variable
1. Built-in default

A flag passed on the command line always wins. An exported environment variable overrides the built-in default. If nothing is set, the default applies.

## Entry format

Every variable below uses the same format:

- **Name:** the exact environment variable.
- **Default:** the built-in value if neither flag nor env var is set.
- **Controls:** what the value affects at runtime.
- **CLI override:** the matching flag, if any.
- **Example:** a short shell snippet.

## Core variables

| Variable                                    | Default                   | Controls                                          | CLI override                                              |
| ------------------------------------------- | ------------------------- | ------------------------------------------------- | --------------------------------------------------------- |
| `VAULTSPEC_RAG_ROOT`                        | current working directory | Project root used to resolve `.vault/` and config | `--target`                                                |
| `VAULTSPEC_RAG_DATA_DIR`                    | `.vault/data/search-data` | Index data directory (relative to project root)   | `--data-dir`                                              |
| `VAULTSPEC_RAG_QDRANT_DIR`                  | `qdrant`                  | Qdrant storage subdirectory under the data dir    | `--qdrant-dir`                                            |
| `VAULTSPEC_RAG_INDEX_META`                  | `index_meta.json`         | Vault index metadata filename                     | `--index-meta`                                            |
| `VAULTSPEC_RAG_CODE_INDEX_META`             | `code_index_meta.json`    | Code index metadata filename                      | `--code-index-meta`                                       |
| `VAULTSPEC_RAG_STATUS_DIR`                  | `~/.vaultspec-rag`        | Service status and log directory                  | `--status-dir`                                            |
| `VAULTSPEC_RAG_LOG_FILE`                    | `service.log`             | Service log filename within the status dir        | `--log-file`                                              |
| `VAULTSPEC_RAG_PORT`                        | `8766`                    | HTTP service port                                 | `--port` (on relevant commands)                           |
| `VAULTSPEC_RAG_LOG_LEVEL`                   | `WARNING`                 | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`    | `--verbose` raises to `INFO`; `--debug` raises to `DEBUG` |
| `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS`    | `1800`                    | Seconds before an idle project slot is evicted    | none                                                      |
| `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS`        | `16`                      | Soft cap on concurrent project slots              | none                                                      |
| `VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES`       | `10485760`                | Log rotation threshold in bytes (10 MB)           | none                                                      |
| `VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT`    | `5`                       | Number of rotated log files to keep               | none                                                      |
| `VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE`        | `64`                      | Embedding batch size used during indexing         | none                                                      |
| `VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE` | `8`                       | Encode-time batch size for the dense encoder      | none                                                      |
| `VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH`    | `2048`                    | Max sequence length for the dense encoder         | none                                                      |
| `VAULTSPEC_RAG_MAX_EMBED_CHARS`             | `8000`                    | Per-chunk character cap before truncation         | none                                                      |

### Examples

```bash
# Use a non-default project root
export VAULTSPEC_RAG_ROOT=/srv/projects/docs-site

# Move the index data outside the vault
export VAULTSPEC_RAG_DATA_DIR=/var/lib/vaultspec-rag/data

# Run the HTTP service on port 9000
vaultspec-rag server service start --port 9000

# Raise log verbosity for one invocation
vaultspec-rag --debug search "qdrant prefetch"

# Cap the service at four concurrent project slots
export VAULTSPEC_RAG_SERVICE_MAX_PROJECTS=4
```

## Type coercion

The config loader parses every environment value on first access. An invalid integer or float raises at that point, not at startup.

- **Booleans:** case-insensitive. `1`, `true`, and `yes` parse as true. Any other string parses as false.
- **Integers and floats:** parsed with `int()` and `float()`. Non-numeric strings such as `"32k"` raise on the first read of the value. Negative values are accepted by the parser; downstream code rejects nonsensical ranges.
- **Paths:** kept as strings. Relative paths resolve against the project root (`VAULTSPEC_RAG_ROOT`). Absolute paths are used as given. Use forward slashes on Windows.

## HuggingFace cache

vaultspec-rag downloads dense, sparse, and reranker models through the HuggingFace Hub. The Hub client honors its own environment variables; vaultspec-rag does not wrap them.

| Variable                         | Default                | Controls                                                                                                             |
| -------------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `HF_HOME`                        | `~/.cache/huggingface` | Root cache directory for HuggingFace models and datasets                                                             |
| `HF_HUB_DOWNLOAD_TIMEOUT`        | HF default (10)        | Per-file download timeout in seconds. `vaultspec-rag server service warmup` raises this to `300` for the warmup run. |
| `DISABLE_SAFETENSORS_CONVERSION` | unset                  | Set to `1` to skip the safetensors conversion step on weight downloads                                               |

### Examples

```bash
# Share a single cache across users on a shared machine
export HF_HOME=/srv/cache/huggingface

# Raise the download timeout on slow networks
export HF_HUB_DOWNLOAD_TIMEOUT=120

# Skip safetensors conversion for legacy weights
export DISABLE_SAFETENSORS_CONVERSION=1
```

## Precedence cheatsheet

If you set `VAULTSPEC_RAG_PORT=9000` in your shell and then run `vaultspec-rag server service start --port 9100`, the service binds to `9100`. Removing the flag and rerunning the command binds to `9000`. Unsetting the variable falls back to `8766`.
