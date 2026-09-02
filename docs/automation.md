# Scripting and automation

Pass `--json` to get machine-readable output instead of a formatted table. The
flag suppresses console formatting and writes exactly one JSON document to
stdout, newline-terminated. Log lines at INFO, WARNING, and ERROR still go to
stderr or the service log, so add `2>/dev/null` when you want stdout alone.

Every command accepts `--json` except `server warmup`.

Scripts read three signals: the `ok` field, the `error` string when `ok` is
false, and the process exit code. None of them requires matching against prose.

## Before you start

You need vaultspec-rag installed and a project indexed. See
[Installation](installation.md) for setup and
[Getting started](getting-started.md) for indexing your first project.

`search` and `index` talk to the running service. With `--port` unset, they
read the port from the discovery record the daemon publishes at
`~/.vaultspec-rag/service.json`; pass `--port N` to target a specific service.
An unreachable service returns the `port_unreachable` error rather than
silently running the work in-process. Start the service with
`vaultspec-rag server start`. See [Service mode](service-mode.md) for the full
walkthrough and [Service discovery](service-discovery.md) for how the lookup
resolves.

## The envelope shape

Every `--json` response is one JSON object with `ok`, `command`, and then
either `data` on success or `error` and `message` on failure. Error envelopes
may carry extras such as `port` or a `remediation` array.

`command` is a stable identifier for the operation, not the command path you
typed. `search` reports `search`, but `index` reports `indexing` and
`server jobs` reports `service.jobs`. Match on it only against a value you have
observed.

Success, with most per-hit fields elided:

```json
{
  "ok": true,
  "command": "search",
  "data": {
    "request_id": "fccd0f1fb63343078dbc8f683aa314be",
    "results": [
      {
        "id": "audit/graph-embedding-round36-audit",
        "path": ".vault/audit/graph-embedding-round36-audit.md",
        "title": "Round 36: Graph/Embedding Domain Audit",
        "score": 0.8315700888633728,
        "snippet": "...",
        "source": "vault",
        "doc_type": "audit",
        "feature": "gpu-rag-stack"
      }
    ]
  }
}
```

Error:

```json
{
  "ok": false,
  "command": "search",
  "error": "port_unreachable",
  "message": "Service on port 8799 is unreachable. The CLI will not silently run search locally; start the service or re-run with --allow-fallback (one local user only).",
  "port": 8799,
  "remediation": [
    "vaultspec-rag server status",
    "vaultspec-rag server start",
    "rerun with --allow-fallback (one user only)"
  ]
}
```

## Parse a search with jq

With that shape in hand, a search reduces to one `jq` path:

```bash
vaultspec-rag search "graph rebuild race" --json \
  | jq -r '.data.results[].path'
```

`data.results` holds one object per hit. The fields you will usually want are
`id`, `path`, `title`, `score`, `snippet`, and `source`. Each object also
carries the retrieval metadata for its domain, such as `doc_type`, `feature`,
and `date` for vault hits, or `language`, `line_start`, `function_name`, and
`class_name` for code hits. Fields that do not apply to a hit are `null` rather
than absent, so `jq` paths stay stable across domains.

## Detect success vs error

`ok` is `true` on success and `false` on error. Gate further work on it:

```bash
out=$(vaultspec-rag search "graph rebuild race" --json)
if ! echo "$out" | jq -e '.ok' >/dev/null; then
  echo "$out" | jq -r '.error + ": " + .message' >&2
  exit 1
fi
```

The `message` field is written for people and gets reworded. Branch on the
`error` code:

```bash
case $(echo "$out" | jq -r '.error // empty') in
  port_unreachable)   echo "service unreachable; retry or start it";;
  local_store_locked) echo "another process holds the lock, aborting"; exit 1;;
  stopped)            echo "service not running, start it first"; exit 3;;
  "")                 echo "ok";;
esac
```

`port_unreachable` is retryable and exits `1`. For `search` you can also pass
`--allow-fallback` to run in-process against the on-disk store under
`.vault/data/`. `index` has no such flag: local indexing needs an exclusive
lease the service cannot hand out while it is down, so an unreachable service
is a hard failure there. Its `remediation` array reflects that, listing only
`server status` and `server start`.

## Indexing returns when the job is admitted, not when it finishes

With a service running, `vaultspec-rag index` hands the work to the service as
a background job and returns immediately. `ok: true` means the job was
admitted. It does not mean anything has been indexed:

```json
{
  "ok": true,
  "command": "indexing",
  "data": {
    "via": "service",
    "source": "combined",
    "outcome": {"ok": true, "partial": false, "status": "queued", "domains": {}}
  }
}
```

Note `"status": "queued"`. A script that reads that response as "indexing
succeeded" will pass while indexing is still running, and will keep passing if
the job later fails.

To watch the work itself, poll `vaultspec-rag server jobs --json` and read
`data.jobs[]`, where each job carries `id`, `state`, and a `progress` object
with `step`, `completed`, and `total`. To check the result instead, read the
index counts with `status`, as
[the CI example](#worked-example-gate-ci-on-index-health) does.

## Worked example: gate CI on index health

Fail the build when the code index is empty, which usually means misconfigured
ignore globs or source roots.

Ask `status` for the index counts. It reports what is stored, so it answers the
question `index` leaves open: did the work finish?

```bash
#!/usr/bin/env bash
set -euo pipefail

out=$(vaultspec-rag status --json)

if ! echo "$out" | jq -e '.ok' >/dev/null; then
  echo "status failed: $(echo "$out" | jq -r '.error')" >&2
  exit 1
fi

code_chunks=$(echo "$out" | jq '.data.codebase_chunks')

if [ "$code_chunks" -eq 0 ]; then
  echo "code index is empty; check ignore globs and source roots" >&2
  exit 1
fi
```

`status --json` also reports `vault_documents` and `document_chunks`, plus
accelerator and storage details. Gate on whichever domain your project
populates. A repository with no preprocessing hooks configured has
`document_chunks` at `0` legitimately.

## Exit codes and error strings

The exit code is the coarse signal; the `error` string names the specific
failure.

| Code | Meaning                                                    |
| ---- | ---------------------------------------------------------- |
| `0`  | success                                                    |
| `1`  | generic failure, including `port_unreachable`              |
| `2`  | usage error, such as an option the command does not accept |
| `3`  | service stopped                                            |
| `4`  | service crashed or divergent                               |
| `5`  | service warming: models loading, not yet serving           |

Code `5` is retryable; wait and re-run. The `error` field carries a code such
as `port_unreachable`, `local_store_locked`, or `stopped`. The
[CLI reference](cli.md) lists the exit codes and error strings each command can
return.

## Automatic re-indexing

A watcher keeps the index fresh, so a scripted pipeline does not need to call
`index` on every run. The running service re-indexes incrementally as files
change, and it is on by default. For headless or containerized deployments, set
`VAULTSPEC_RAG_WATCH_ENABLED=0` to run pull-only. Inspect and tune it with the
`vaultspec-rag server updates` verbs. See [Service mode](service-mode.md) for
the watcher in full and [Configuration](configuration.md) for the environment
variables.

## Where to go next

- [Getting started](getting-started.md) walks through indexing a project and running a first search.
- [Service mode](service-mode.md) covers running the background service and its watcher.
- [CLI reference](cli.md) lists every command's flags, exit codes, and error strings.
- [Configuration](configuration.md) covers the environment variables and tuning knobs.

For anything else, see [Status and help](../README.md#status-and-help) in the
repo README.
