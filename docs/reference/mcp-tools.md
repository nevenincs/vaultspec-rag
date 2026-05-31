# MCP tools reference

The vaultspec-rag MCP server exposes eight tools that MCP clients invoke over either stdio (one project per process) or streamable HTTP at `/mcp` (multi-tenant). Each tool name, parameter list, and return shape below mirrors the canonical signatures in `src/vaultspec_rag/mcp_server.py`. For client setup, see the [MCP client how-to](../how-to/use-with-mcp-clients.md).

Two transport rules apply to every tool:

- **stdio mode:** `project_root` is optional. The server falls back to the `VAULTSPEC_RAG_ROOT` environment variable, then to the current working directory.
- **HTTP service mode:** `project_root` is required on every call. The service has no default project and refuses calls without it. The exception is `evict_project`, which uses the parameter name `root`.

All search and admin tools that resolve a project root validate that the directory contains a `.vault/` subdirectory.

## search_vault

Semantic search over vault documents (ADRs, plans, research, audits, references, execution records).

| Name           | Type           | Default  | Description                                                                                                        |
| -------------- | -------------- | -------- | ------------------------------------------------------------------------------------------------------------------ |
| `query`        | string         | required | Natural language query. Supports inline tokens like `type:adr` and `feature:name`. Truncated to 10,000 characters. |
| `top_k`        | int            | `5`      | Number of results. Clamped to the range 1-100.                                                                     |
| `doc_type`     | string \| null | `None`   | Vault doc-type filter (for example `"adr"`, `"plan"`). Equivalent to the `type:` query token.                      |
| `feature`      | string \| null | `None`   | Feature-tag filter (kebab-case).                                                                                   |
| `date`         | string \| null | `None`   | Exact ISO-date filter.                                                                                             |
| `tag`          | string \| null | `None`   | Free-form tag, matched against the `tags` payload array.                                                           |
| `project_root` | string \| null | `None`   | Project root path. Required in HTTP mode.                                                                          |

Returns `SearchResponse`:

- `results`: list of result items with `id`, `path`, `title`, `score`, `snippet`, `source`, `doc_type`, `feature`, `date`.
- `summary`: human-readable summary string.
- `backend_capabilities`: backend concurrency contract.

Example:

```json
{"tool": "search_vault", "arguments": {"query": "feature:scheduler retry policy", "top_k": 10, "project_root": "/repo/app"}}
```

## search_codebase

Semantic search over indexed source code, with AST-aware filters from tree-sitter.

| Name            | Type                 | Default  | Description                                                                                                              |
| --------------- | -------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------ |
| `query`         | string               | required | Natural language string or code snippet. Truncated to 10,000 characters.                                                 |
| `top_k`         | int                  | `5`      | Number of chunks. Clamped to 1-100.                                                                                      |
| `language`      | string \| null       | `None`   | Language filter (for example `"python"`, `"rust"`).                                                                      |
| `path`          | string \| null       | `None`   | Exact-match filter against the project-relative file path.                                                               |
| `node_type`     | string \| null       | `None`   | AST node type filter (for example `"function_definition"`).                                                              |
| `function_name` | string \| null       | `None`   | Function or method name filter.                                                                                          |
| `class_name`    | string \| null       | `None`   | Class or struct name filter.                                                                                             |
| `include_paths` | list[string] \| null | `None`   | fnmatch globs kept by a post-query filter (for example `["src/foo/**"]`).                                                |
| `exclude_paths` | list[string] \| null | `None`   | fnmatch globs dropped by a post-query filter (for example `["tests/**"]`).                                               |
| `dedup_locales` | bool                 | `False`  | When true, collapse near-tie locale variants (for example `locales/{en,es}.yml`) into one canonical result after rerank. |
| `prefer`        | string \| null       | `None`   | One of `"prod"`, `"tests"`, `"docs"`. Applies a small score nudge to the matching category.                              |
| `project_root`  | string \| null       | `None`   | Project root path. Required in HTTP mode.                                                                                |

Returns `SearchResponse`:

- `results`: list of result items with `id`, `path`, `title`, `score`, `snippet`, `source`, `language`, `line_start`, `line_end`, `node_type`, `function_name`, `class_name`.
- `summary`: human-readable summary string.
- `backend_capabilities`: backend concurrency contract.

Example:

```json
{"tool": "search_codebase", "arguments": {"query": "retry backoff loop", "language": "python", "node_type": "function_definition", "project_root": "/repo/app"}}
```

## reindex_vault

Re-index vault documentation. Invalidates the document-graph cache so the next search picks up updated relationships.

| Name           | Type           | Default | Description                                                                                                                                                                       |
| -------------- | -------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `clean`        | bool           | `False` | If true, re-encode every vault document and purge rows absent from the new corpus. The rebuild is failure-safe: the old collection survives until the new slices stream in place. |
| `project_root` | string \| null | `None`  | Project root path. Required in HTTP mode.                                                                                                                                         |

Returns `IndexResponse`:

- `total`: total documents in the index after the operation.
- `added`: newly indexed documents.
- `updated`: re-indexed (modified) documents.
- `removed`: stale rows purged after the streaming rebuild (clean mode).
- `duration_ms`: wall-clock time in milliseconds.
- `files`: source files processed.

Example:

```json
{"tool": "reindex_vault", "arguments": {"clean": true, "project_root": "/repo/app"}}
```

## reindex_codebase

Re-index the source codebase.

| Name           | Type           | Default | Description                                                                                                                                                  |
| -------------- | -------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `clean`        | bool           | `False` | If true, re-encode every source chunk and purge chunk IDs absent from the new scan. Failure-safe: old chunks stay live until the new slices stream in place. |
| `project_root` | string \| null | `None`  | Project root path. Required in HTTP mode.                                                                                                                    |

Returns `IndexResponse` with the same fields as `reindex_vault`: `total`, `added`, `updated`, `removed`, `duration_ms`, `files`.

Example:

```json
{"tool": "reindex_codebase", "arguments": {"clean": false, "project_root": "/repo/app"}}
```

## get_index_status

Return the current state of the RAG index and GPU hardware for a single project.

| Name           | Type           | Default | Description                               |
| -------------- | -------------- | ------- | ----------------------------------------- |
| `project_root` | string \| null | `None`  | Project root path. Required in HTTP mode. |

Returns `IndexStatus`:

- `vault_count`: number of indexed vault documents.
- `code_count`: number of indexed codebase chunks.
- `storage_path`: absolute path to the Qdrant local database directory.
- `target_dir`: workspace root directory.
- `vram_gb`: total GPU VRAM in gigabytes (zero if CUDA is unavailable).
- `backend_capabilities`: backend concurrency contract.

Example:

```json
{"tool": "get_index_status", "arguments": {"project_root": "/repo/app"}}
```

## get_code_file

Return the full UTF-8 text of an indexed source file by relative path. Refuses paths that escape the workspace, paths that match sensitive patterns (for example `.env`, `*.pem`, `*secrets*`, anything inside `.git/`), and files larger than 10 MB.

| Name           | Type           | Default  | Description                               |
| -------------- | -------------- | -------- | ----------------------------------------- |
| `path`         | string         | required | File path relative to the project root.   |
| `project_root` | string \| null | `None`   | Project root path. Required in HTTP mode. |

Returns a single string: the UTF-8 file contents. Raises `ValueError` for path-escape, sensitive-path, and oversize errors, and `FileNotFoundError` if the file does not exist.

Example:

```json
{"tool": "get_code_file", "arguments": {"path": "src/vaultspec_rag/search.py", "project_root": "/repo/app"}}
```

## list_projects

Return a snapshot of every active project slot held by the service registry. Useful for monitoring tenancy under the HTTP service.

| Name           | Type           | Default | Description                                                                                   |
| -------------- | -------------- | ------- | --------------------------------------------------------------------------------------------- |
| `project_root` | string \| null | `None`  | Accepted for signature parity with the other admin tools. Ignored: the list is registry-wide. |

Returns a dict:

- `projects`: list of project entries, each with `root`, `last_access_iso` (ISO-8601 local timestamp), `idle_seconds`, and `ref_count`.
- `max_projects`: registry capacity.
- `idle_ttl_seconds`: idle TTL after which a slot is evictable.

Example:

```json
{"tool": "list_projects", "arguments": {}}
```

## evict_project

Force-evict a project slot from the service registry. Use to free a slot when the cap is reached, or to drop a slot whose files have changed under it.

| Name   | Type   | Default  | Description                                                                                           |
| ------ | ------ | -------- | ----------------------------------------------------------------------------------------------------- |
| `root` | string | required | Workspace root directory. Resolved internally. Note the parameter name is `root`, not `project_root`. |

Returns a dict with `evicted` (bool) and `reason` (string). The three documented outcomes are:

- `{"evicted": true,  "reason": "forced"}` - slot removed.
- `{"evicted": false, "reason": "busy"}` - slot had live leases; retry.
- `{"evicted": false, "reason": "not_found"}` - unknown root.

Example:

```json
{"tool": "evict_project", "arguments": {"root": "/repo/app"}}
```
