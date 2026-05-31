# JSON envelope reference

Every `vaultspec-rag` command invoked with `--json` writes exactly one JSON document to stdout, terminated by a single newline. Rich console output is bypassed: the bytes come straight from `sys.stdout.write`, so the stream is safe to pipe into `jq`, redirect to a file, or stream to a parser.

## Envelope shape

Every envelope contains two mandatory fields:

| Field     | Type    | Description                                                                                                                          |
| --------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `ok`      | boolean | `true` for success, `false` for any error path.                                                                                      |
| `command` | string  | The dotted command name (`search`, `index`, `status`, `service.status`, `service.projects.list`, `service.projects.evict`, `clean`). |

On success, the envelope adds:

| Field  | Type   | Description                                          |
| ------ | ------ | ---------------------------------------------------- |
| `data` | object | Command-specific payload. Always present on success. |

On error, the envelope adds:

| Field     | Type   | Description                                             |
| --------- | ------ | ------------------------------------------------------- |
| `error`   | string | Stable machine code from the taxonomy below.            |
| `message` | string | Human-readable prose for terminal output and log lines. |

Commands may attach extra top-level keys alongside `error` (for example `port`, `target`, `root`, `state`, `remediation`, `value`, `offending`, `db_path`, `backend_capabilities`, `raw_response`). Treat unknown keys as forward-compatible additions and never rely on key order.

## Success envelopes

### search

```json
{
  "ok": true,
  "command": "search",
  "data": {
    "query": "qdrant hybrid query",
    "search_type": "vault",
    "via": "in-process",
    "results": [
      {"id": "adr/gpu-only-rag-stack", "path": ".vault/adr/gpu-only-rag-stack.md", "title": "GPU-only RAG stack", "score": 0.81, "snippet": "...", "source": "vault"}
    ]
  }
}
```

`via` is `"in-process"` when the CLI ran the search locally and `"mcp"` when it delegated to a running service via `--port`. `search_type` is `vault` or `code`. Exit code 0.

### index

```json
{
  "ok": true,
  "command": "index",
  "data": {
    "via": "in-process",
    "sources": [
      {"source": "vault",    "added": 3, "updated": 1, "removed": 0, "total": 142, "duration_ms": 1820},
      {"source": "codebase", "added": 0, "updated": 7, "removed": 2, "total": 9876, "duration_ms": 4410}
    ]
  }
}
```

`--dry-run --type code` returns `{"dry_run": true, "count": N, "files": [...]}` instead of `sources`. Exit code 0.

### status

```json
{
  "ok": true,
  "command": "status",
  "data": {
    "cuda": true,
    "gpu_name": "NVIDIA GeForce RTX 4080",
    "vram_mb": 16376,
    "storage_path": "/abs/path/.vault/data/search-data",
    "vault_documents": 142,
    "codebase_chunks": 9876,
    "target_dir": "/abs/path",
    "backend_capabilities": {"...": "..."}
  }
}
```

Exit code 0.

### server service status

```json
{
  "ok": true,
  "command": "service.status",
  "data": {
    "service_json_present": true,
    "pid": 12345,
    "port": 8766,
    "started_at": "2026-05-31T09:14:22Z",
    "pid_alive": true,
    "pid_matches_service": true,
    "port_listening": true,
    "heartbeat_age_seconds": 3.2,
    "heartbeat_stale": false,
    "service_token_match": true,
    "state": "running",
    "health": {"...": "..."}
  }
}
```

`ok` is `true` only when `state` is `running`. Any other state produces an error envelope with the matching `state` value and a non-zero exit code (see the divergence rows below).

### server service projects list

```json
{
  "ok": true,
  "command": "service.projects.list",
  "data": {
    "projects": [
      {"root": "/abs/proj-a", "idle_seconds": 12.4, "ref_count": 0, "last_access_iso": "2026-05-31T09:20:11Z"}
    ],
    "max_projects": 4,
    "idle_ttl_seconds": 1800
  }
}
```

Exit code 0.

### server service projects evict

```json
{
  "ok": true,
  "command": "service.projects.evict",
  "data": {"evicted": true, "reason": "ok", "root": "/abs/proj-a"}
}
```

Exit code 0.

## Error envelopes

The most common shape, using `search` as an example:

```json
{
  "ok": false,
  "command": "search",
  "error": "invalid_filter_for_search_type",
  "message": "--language only applies to --type code.",
  "filter_kind": "language",
  "offending": "python"
}
```

## Error code taxonomy

| Code                             | Meaning                                                          | Emitted by                                        |
| -------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------- |
| `invalid_filter_for_search_type` | Code-only filter passed to vault search, or vice versa.          | `search`                                          |
| `invalid_prefer_value`           | `--prefer` not in \`prod                                         | tests                                             |
| `rebuild_requires_explicit_type` | `index --rebuild` without an explicit `--type`.                  | `index`                                           |
| `dry_run_requires_code`          | `index --dry-run` without `--type code`.                         | `index`                                           |
| `rebuild_locked`                 | Cannot drop a collection because another process holds the lock. | `index`                                           |
| `json_requires_yes`              | Destructive `--json` command would need an interactive confirm.  | `clean`                                           |
| `port_unreachable`               | `--port N` not listening; no silent in-process fallback.         | `search`, `index`                                 |
| `mcp_call_failed`                | MCP service is alive but rejected the call.                      | `search`, `index`                                 |
| `local_store_locked`             | Local Qdrant store is held by another process.                   | Any command that opens the store                  |
| `gpu_unavailable`                | No CUDA device, or no torch installed.                           | Any GPU-touching command                          |
| `service_not_running`            | Admin call routed to a stopped service.                          | `service.projects.list`, `service.projects.evict` |
| `stopped`                        | `server service status`: no `service.json`.                      | `service.status`                                  |
| `crashed_pid_dead`               | `service.json` present, PID gone (file is cleaned).              | `service.status`                                  |
| `crashed_pid_reused`             | PID belongs to an unrelated process.                             | `service.status`                                  |
| `crashed_port_silent`            | PID alive, port not accepting connections.                       | `service.status`                                  |
| `crashed_heartbeat_stale`        | PID alive, port open, heartbeat too old.                         | `service.status`                                  |
| `divergent`                      | Signals disagree without matching any specific crash variant.    | `service.status`                                  |
| `busy`                           | Slot eviction refused; slot is in use.                           | `service.projects.evict`                          |
| `not_found`                      | Slot eviction refused; no such slot.                             | `service.projects.evict`                          |
| `unexpected_response`            | Admin call returned an unrecognized payload.                     | `service.projects.evict`                          |

## Exit code matrix

| Exit | Meaning                       | Error codes that pair with it                                                                                                                         |
| ---- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | Success.                      | none (success envelope only)                                                                                                                          |
| 1    | Operational failure.          | `port_unreachable`, `mcp_call_failed`, `local_store_locked`, `gpu_unavailable`, `rebuild_locked`, `busy`                                              |
| 2    | Usage error.                  | `invalid_filter_for_search_type`, `invalid_prefer_value`, `rebuild_requires_explicit_type`, `dry_run_requires_code`, `json_requires_yes`, `not_found` |
| 3    | Service stopped.              | `stopped`, `service_not_running`                                                                                                                      |
| 4    | Service divergent or crashed. | `crashed_pid_dead`, `crashed_pid_reused`, `crashed_port_silent`, `crashed_heartbeat_stale`, `divergent`                                               |

Scripts can branch on the exit code alone for the common "is the service healthy" check, and parse `error` for fine-grained handling.
