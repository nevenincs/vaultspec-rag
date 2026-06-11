# Configuration reference

This page lists every environment variable vaultspec-rag reads, the matching CLI flag where one exists, and the rules for parsing values. See [installation.md](installation.md) for where to set variables before first run, [cli.md](cli.md) for the full flag context, and [architecture.md](architecture.md) for the runtime concepts referenced below.

## Resolution order

1. CLI flag on the invoked command.
1. Environment variable.
1. Built-in default.

A flag passed on the command line always wins. An exported environment variable overrides the built-in default. If nothing is set, the default applies.

## Core variables

Every `VAULTSPEC_RAG_*` variable recognised by the loader, taken verbatim from the `EnvVar` enum and `_RAG_DEFAULTS` in `src/vaultspec_rag/config.py`.

| Variable                                     | Type    | Default                   | Controls                                                        | CLI override                          |
| -------------------------------------------- | ------- | ------------------------- | --------------------------------------------------------------- | ------------------------------------- |
| `VAULTSPEC_RAG_ROOT`                         | path    | current working directory | Project root used to resolve `.vault/` and indexing scope       | `--target`                            |
| `VAULTSPEC_RAG_DATA_DIR`                     | path    | `.vault/data/search-data` | Directory holding the Qdrant store and index metadata           | `--data-dir`                          |
| `VAULTSPEC_RAG_QDRANT_DIR`                   | path    | `qdrant`                  | Qdrant subdirectory inside the data dir                         | `--qdrant-dir`                        |
| `VAULTSPEC_RAG_INDEX_META`                   | path    | `index_meta.json`         | Vault index metadata filename inside the data dir               | `--index-meta`                        |
| `VAULTSPEC_RAG_CODE_INDEX_META`              | path    | `code_index_meta.json`    | Codebase index metadata filename inside the data dir            | `--code-index-meta`                   |
| `VAULTSPEC_RAG_STATUS_DIR`                   | path    | `~/.vaultspec-rag`        | Directory for service status, pid, and lock files               | `--status-dir`                        |
| `VAULTSPEC_RAG_LOG_FILE`                     | path    | `service.log`             | Log filename inside the status dir                              | `--log-file`                          |
| `VAULTSPEC_RAG_PORT`                         | integer | `8766`                    | HTTP port for the service and MCP fast path                     | `--port`                              |
| `VAULTSPEC_RAG_LOG_LEVEL`                    | string  | `WARNING`                 | Root logger level                                               | `--verbose` (INFO), `--debug` (DEBUG) |
| `VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS`     | integer | `1800`                    | Seconds an idle project engine is kept resident before eviction | none                                  |
| `VAULTSPEC_RAG_SERVICE_MAX_PROJECTS`         | integer | `16`                      | Maximum simultaneously cached project engines                   | none                                  |
| `VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES`        | integer | `10485760`                | Rotating log file size cap, in bytes (10 MB)                    | none                                  |
| `VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT`     | integer | `5`                       | Number of rotated log backups retained                          | none                                  |
| `VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE`         | integer | `64`                      | Outer batch size fed to the embedding pipeline                  | none                                  |
| `VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE`  | integer | `8`                       | Inner sub-batch size passed to `SentenceTransformer.encode()`   | none                                  |
| `VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH`     | integer | `2048`                    | Hard cap on sequence length advertised to the model             | none                                  |
| `VAULTSPEC_RAG_MAX_EMBED_CHARS`              | integer | `8000`                    | Character cap applied to each text before encoding              | none                                  |
| `VAULTSPEC_RAG_WATCH_ENABLED`                | boolean | `1` (on)                  | Filesystem auto-reindex watcher on/off (`0` = pull-only)        | `--watch` / `--no-watch`              |
| `VAULTSPEC_RAG_WATCH_DEBOUNCE_MS`            | integer | `2000`                    | Debounce window coalescing change events before reindex (ms)    | `--watch-debounce-ms`                 |
| `VAULTSPEC_RAG_WATCH_COOLDOWN_S`             | float   | `30`                      | Per-source re-index cooldown after a completed run (s)          | `--watch-cooldown-s`                  |
| `VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES` | integer | `10485760`                | Cap on text a preprocess hook may emit per file (bytes)         | -                                     |
| `VAULTSPEC_RAG_HTML_STRIP`                   | bool    | `1`                       | Strip tags from `.html` to plain text before chunking           | -                                     |

See [Preprocessing hooks](preprocessing-hooks.md) for the `.vaultragpreprocess.toml` rule
format and the preprocessor output schema.

## Examples

```bash
VAULTSPEC_RAG_ROOT=/srv/projects/acme vaultspec-rag search "billing flow"
```

Pin the project root for a single search invocation.

```bash
VAULTSPEC_RAG_PORT=9100 vaultspec-rag server service start
```

Bind the HTTP service to a non-default port.

```bash
vaultspec-rag --debug search "billing flow"
```

Raise the log level to DEBUG for one command.

## Type coercion

The loader parses each value on first access. An invalid integer or float raises at that point, not at startup.

- Booleans: the strings `1`, `true`, and `yes` (case-insensitive) parse as true; anything else parses as false.
- Integers and floats: parsed with `int()` and `float()`; non-numeric strings raise on first read. Negative values are accepted by the parser but downstream code rejects nonsensical ranges.
- Paths: kept as strings. Relative paths resolve against the project root; absolute paths are used as given. Use forward slashes on Windows.

An unset variable falls back to the built-in default. An explicitly empty string is treated as an explicit value, which usually parses to "no override" for paths and to coercion errors for integers and booleans.

## HuggingFace cache

vaultspec-rag downloads its three model files through the HuggingFace Hub. The Hub client honours its own environment variables and vaultspec-rag does not wrap them. See the [HuggingFace environment variable reference](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables).

| Variable                         | Default                                              | Controls                                                                        |
| -------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------- |
| `HF_HOME`                        | `~/.cache/huggingface`                               | Root directory for the Hub cache, tokens, and downloaded model snapshots        |
| `HF_HUB_DOWNLOAD_TIMEOUT`        | `10` (HF default); `300` during vaultspec-rag warmup | Per-request download timeout in seconds                                         |
| `DISABLE_SAFETENSORS_CONVERSION` | unset                                                | When set, suppresses on-the-fly conversion of legacy checkpoints to safetensors |

## Precedence in practice

If `VAULTSPEC_RAG_PORT=9000` is exported and you run `vaultspec-rag server service start --port 9100`, the service binds to 9100. Removing the flag binds to 9000. Unsetting the variable falls back to 8766.

## Need help?

See the [Support](../README.md#support-and-help) section of the repo README.
